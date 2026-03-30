from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import func

from retriqs.base import QueryParam
from retriqs.api.database.models import (
    RetrievalChat,
    RetrievalChatMessage,
    RetrievalSnapshot,
    SessionLocal,
    init_db,
)
from retriqs.utils import logger


MAX_MCP_CONTEXT_PREVIEW_CHARS = 20000


def build_mcp_query_param(
    *,
    mode: str = "mix",
    top_k: int = 10,
    chunk_top_k: int | None = None,
    max_entity_tokens: int | None = None,
    max_relation_tokens: int | None = None,
    max_total_tokens: int | None = None,
    hl_keywords: list[str] | None = None,
    ll_keywords: list[str] | None = None,
    enable_rerank: bool | None = None,
) -> QueryParam:
    """
    Build a retrieval-only QueryParam for MCP calls.

    Important:
    - stream=False
    - do NOT set only_need_context=True, because that makes the result
      behave more like the context-only /query branch instead of /query/data
    """
    kwargs = {
        "mode": mode,
        "top_k": top_k,
        "stream": False,
    }

    if chunk_top_k is not None:
        kwargs["chunk_top_k"] = chunk_top_k
    if max_entity_tokens is not None:
        kwargs["max_entity_tokens"] = max_entity_tokens
    if max_relation_tokens is not None:
        kwargs["max_relation_tokens"] = max_relation_tokens
    if max_total_tokens is not None:
        kwargs["max_total_tokens"] = max_total_tokens
    if hl_keywords:
        kwargs["hl_keywords"] = hl_keywords
    if ll_keywords:
        kwargs["ll_keywords"] = ll_keywords
    if enable_rerank is not None:
        kwargs["enable_rerank"] = enable_rerank

    param = QueryParam(**kwargs)
    param.stream = False
    return param

def normalize_retrieval_result(result: Any) -> dict[str, Any]:
    """
    Normalize the output of rag.aquery_data(...).

    Supports both patterns seen in the codebase:
    1) dict with {status, message, data, metadata}
    2) object with .content and .raw_data
    """
    if result is None:
        return {
            "status": "success",
            "message": "No relevant context found.",
            "context_text": "",
            "data": {
                "entities": [],
                "relationships": [],
                "relations": [],
                "chunks": [],
                "references": [],
            },
            "metadata": {},
            "references": [],
        }

    if isinstance(result, dict):
        data = result.get("data", {}) or {}
        metadata = result.get("metadata", {}) or {}
        context_text = (
            result.get("context_text")
            or result.get("content")
            or data.get("context_text")
            or ""
        )
        status = result.get("status", "success")
        message = result.get("message", "Query executed successfully")
    else:
        data = getattr(result, "raw_data", {}) or {}
        metadata = getattr(result, "metadata", {}) or {}
        context_text = getattr(result, "content", "") or ""
        status = "success"
        message = "Query executed successfully"

    entities = data.get("entities", []) or []
    relationships = data.get("relationships", data.get("relations", [])) or []
    chunks = data.get("chunks", []) or []
    references = data.get("references", []) or []

    if not context_text:
        chunk_texts = []
        for chunk in chunks:
            if isinstance(chunk, dict):
                content = (chunk.get("content") or "").strip()
                if content:
                    chunk_texts.append(content)
        context_text = "\n\n".join(chunk_texts)

    normalized_data = dict(data)
    normalized_data["entities"] = entities
    normalized_data["relationships"] = relationships
    normalized_data["relations"] = relationships
    normalized_data["chunks"] = chunks
    normalized_data["references"] = references

    return {
        "status": status,
        "message": message,
        "context_text": context_text,
        "data": normalized_data,
        "metadata": metadata,
        "references": references,
    }


def _next_sequence_no(db, chat_id: int) -> int:
    current_max = (
        db.query(func.max(RetrievalChatMessage.sequence_no))
        .filter(RetrievalChatMessage.chat_id == chat_id)
        .scalar()
    )
    return (current_max or 0) + 1


def _ensure_chat(
    db,
    *,
    storage_id: int,
    chat_id: int | None,
    title_hint: str,
) -> RetrievalChat:
    if chat_id is not None:
        chat = (
            db.query(RetrievalChat)
            .filter(
                RetrievalChat.id == chat_id,
                RetrievalChat.storage_id == storage_id,
            )
            .first()
        )
        if not chat:
            raise ValueError(
                f"Chat {chat_id} was not found for storage {storage_id}."
            )
        return chat

    chat = RetrievalChat(
        storage_id=storage_id,
        title=title_hint[:255] if title_hint else "MCP retrieval",
        is_pinned=False,
    )
    db.add(chat)
    db.flush()
    return chat


def build_mcp_assistant_content(
    *,
    provider: str,
    tool_name: str,
    context_text: str,
    data: dict[str, Any] | None,
) -> str:
    data = data or {}
    entities = data.get("entities", []) or []
    relationships = data.get("relationships", data.get("relations", [])) or []
    chunks = data.get("chunks", []) or []
    references = data.get("references", []) or []

    return (
        "This question was answered by an external agent using the MCP tool.\n\n"
        f"Provider: {provider}\n"
        f"Tool: {tool_name}\n\n"
        "Retrieved context summary\n"
        f"- Entities: {len(entities)}\n"
        f"- Relationships: {len(relationships)}\n"
        f"- Chunks: {len(chunks)}\n"
        f"- References: {len(references)}"
    )


def normalize_snapshot_data(data: dict[str, Any] | None) -> dict[str, Any]:
    """
    Normalize retrieval data into the shape the UI/query routes expect.
    """
    raw = dict(data or {})

    entities = raw.get("entities", []) or []
    relationships = raw.get("relationships", raw.get("relations", [])) or []
    chunks = raw.get("chunks", []) or []
    references = raw.get("references", []) or []

    raw["entities"] = entities
    raw["relationships"] = relationships
    raw["relations"] = relationships
    raw["chunks"] = chunks
    raw["references"] = references

    return raw

def persist_mcp_retrieval_turn(
    *,
    storage_id: int,
    query: str,
    provider: str,
    tool_name: str,
    mode: str,
    context_text: str,
    data: dict[str, Any] | None,
    metadata: dict[str, Any] | None,
    references: list[dict[str, Any]] | None,
    chat_id: Optional[int] = None,
) -> dict[str, Optional[int]]:
    """
    Persist an MCP retrieval call as a visible chat in the app.

    Result:
    - user message = original query
    - retrieval snapshot on user message
    - assistant message = retrieved context note, clearly marked as MCP retrieval
    """
    init_db()
    db = SessionLocal()

    try:
        normalized_data = normalize_snapshot_data(data)
        normalized_references = references or normalized_data.get("references", []) or []

        entities = normalized_data.get("entities", []) or []
        relationships = normalized_data.get("relationships", []) or []
        chunks = normalized_data.get("chunks", []) or []

        logger.info(
            "Persisting MCP retrieval turn: storage_id=%s entities=%s relationships=%s chunks=%s references=%s",
            storage_id,
            len(entities),
            len(relationships),
            len(chunks),
            len(normalized_references),
        )

        title = f"[MCP][{provider}] {query.strip()}"
        chat = _ensure_chat(
            db,
            storage_id=storage_id,
            chat_id=chat_id,
            title_hint=title,
        )

        question_seq = _next_sequence_no(db, chat.id)

        user_message = RetrievalChatMessage(
            chat_id=chat.id,
            sequence_no=question_seq,
            role="user",
            content=query.strip(),
        )
        db.add(user_message)
        db.flush()

        snapshot_metadata = dict(metadata or {})
        snapshot_metadata.update(
            {
                "origin": "mcp",
                "provider": provider,
                "tool_name": tool_name,
                "answer_generated_locally": False,
                "answered_by": "external_model",
                "query_mode": mode,
                "counts": {
                    "entities": len(entities),
                    "relationships": len(relationships),
                    "chunks": len(chunks),
                    "references": len(normalized_references),
                },
            }
        )

        snapshot_trace = {
            "origin": "mcp",
            "provider": provider,
            "tool_name": tool_name,
            "answer_generated_locally": False,
            "context_text": context_text,
            "data": normalized_data,
            "metadata": snapshot_metadata,
        }

        snapshot = RetrievalSnapshot(
            message_id=user_message.id,
            mode=mode,
            data=normalized_data,
            metadata_json=snapshot_metadata,
            references=normalized_references,
            trace=snapshot_trace,
        )
        db.add(snapshot)

        assistant_content = build_mcp_assistant_content(
            provider=provider,
            tool_name=tool_name,
            context_text=context_text,
            data=normalized_data,
        )

        assistant_message = RetrievalChatMessage(
            chat_id=chat.id,
            sequence_no=question_seq + 1,
            role="assistant",
            content=assistant_content,
        )
        db.add(assistant_message)
        db.flush()

        chat.updated_at = datetime.now(timezone.utc)
        db.commit()

        return {
            "chat_id": chat.id,
            "user_message_id": user_message.id,
            "assistant_message_id": assistant_message.id,
        }

    except Exception:
        db.rollback()
        logger.exception(
            "Failed to persist MCP retrieval turn for storage_id=%s", storage_id
        )
        raise
    finally:
        db.close()