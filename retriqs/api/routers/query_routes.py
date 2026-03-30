"""
This module contains all query-related routes for the LightRAG API.
"""

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional
from fastapi import APIRouter, Depends, HTTPException, Request
from retriqs.base import QueryParam
from retriqs.api.database.models import (
    RetrievalChat,
    RetrievalChatMessage,
    RetrievalSnapshot,
    SessionLocal,
    init_db,
)
from retriqs.api.utils_api import get_combined_auth_dependency
from retriqs.utils import logger
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func
from sqlalchemy.orm import selectinload

router = APIRouter(tags=["query"])


class QueryRequest(BaseModel):
    query: str = Field(
        min_length=3,
        description="The query text",
    )

    mode: Literal["local", "global", "hybrid", "naive", "mix", "bypass"] = Field(
        default="mix",
        description="Query mode",
    )

    only_need_context: Optional[bool] = Field(
        default=None,
        description="If True, only returns the retrieved context without generating a response.",
    )

    only_need_prompt: Optional[bool] = Field(
        default=None,
        description="If True, only returns the generated prompt without producing a response.",
    )

    response_type: Optional[str] = Field(
        min_length=1,
        default=None,
        description="Defines the response format. Examples: 'Multiple Paragraphs', 'Single Paragraph', 'Bullet Points'.",
    )

    top_k: Optional[int] = Field(
        ge=1,
        default=None,
        description="Number of top items to retrieve. Represents entities in 'local' mode and relationships in 'global' mode.",
    )

    chunk_top_k: Optional[int] = Field(
        ge=1,
        default=None,
        description="Number of text chunks to retrieve initially from vector search and keep after reranking.",
    )

    max_entity_tokens: Optional[int] = Field(
        default=None,
        description="Maximum number of tokens allocated for entity context in unified token control system.",
        ge=1,
    )

    max_relation_tokens: Optional[int] = Field(
        default=None,
        description="Maximum number of tokens allocated for relationship context in unified token control system.",
        ge=1,
    )

    max_total_tokens: Optional[int] = Field(
        default=None,
        description="Maximum total tokens budget for the entire query context (entities + relations + chunks + system prompt).",
        ge=1,
    )

    hl_keywords: list[str] = Field(
        default_factory=list,
        description="List of high-level keywords to prioritize in retrieval. Leave empty to use the LLM to generate the keywords.",
    )

    ll_keywords: list[str] = Field(
        default_factory=list,
        description="List of low-level keywords to refine retrieval focus. Leave empty to use the LLM to generate the keywords.",
    )

    conversation_history: Optional[List[Dict[str, Any]]] = Field(
        default=None,
        description="Stores past conversation history to maintain context. Format: [{'role': 'user/assistant', 'content': 'message'}].",
    )

    user_prompt: Optional[str] = Field(
        default=None,
        description="User-provided prompt for the query. If provided, this will be used instead of the default value from prompt template.",
    )

    enable_rerank: Optional[bool] = Field(
        default=None,
        description="Enable reranking for retrieved text chunks. If True but no rerank model is configured, a warning will be issued. Default is True.",
    )

    include_references: Optional[bool] = Field(
        default=True,
        description="If True, includes reference list in responses. Affects /query and /query/stream endpoints. /query/data always includes references.",
    )

    include_chunk_content: Optional[bool] = Field(
        default=False,
        description="If True, includes actual chunk text content in references. Only applies when include_references=True. Useful for evaluation and debugging.",
    )

    include_trace: Optional[bool] = Field(
        default=False,
        description="If True, includes full retrieval trace data (entities, relationships, chunks, references, metadata) tied to this same query run.",
    )

    stream: Optional[bool] = Field(
        default=True,
        description="If True, enables streaming output for real-time responses. Only affects /query/stream endpoint.",
    )

    chat_id: Optional[int] = Field(
        default=None,
        ge=1,
        description="Existing chat id to append this turn to. If omitted, a new chat is created.",
    )

    context_only: Optional[bool] = Field(
        default=None,
        description="Alias for only_need_context. If True, only stores user question + retrieved data in chat history.",
    )

    @field_validator("query", mode="after")
    @classmethod
    def query_strip_after(cls, query: str) -> str:
        return query.strip()

    @field_validator("conversation_history", mode="after")
    @classmethod
    def conversation_history_role_check(
        cls, conversation_history: List[Dict[str, Any]] | None
    ) -> List[Dict[str, Any]] | None:
        if conversation_history is None:
            return None
        for msg in conversation_history:
            if "role" not in msg:
                raise ValueError("Each message must have a 'role' key.")
            if not isinstance(msg["role"], str) or not msg["role"].strip():
                raise ValueError("Each message 'role' must be a non-empty string.")
        return conversation_history

    def to_query_params(self, is_stream: bool) -> "QueryParam":
        """Converts a QueryRequest instance into a QueryParam instance."""
        # Use Pydantic's `.model_dump(exclude_none=True)` to remove None values automatically
        # Exclude API-level parameters that don't belong in QueryParam
        request_data = self.model_dump(
            exclude_none=True,
            exclude={
                "query",
                "include_chunk_content",
                "include_trace",
                "chat_id",
                "context_only",
            },
        )

        if self.context_only is not None and "only_need_context" not in request_data:
            request_data["only_need_context"] = self.context_only

        # Ensure `mode` and `stream` are set explicitly
        param = QueryParam(**request_data)
        param.stream = is_stream
        return param




class ReferenceItem(BaseModel):
    """A single reference item in query responses."""

    reference_id: str = Field(description="Unique reference identifier")
    file_path: str = Field(description="Path to the source file")
    content: Optional[List[str]] = Field(
        default=None,
        description="List of chunk contents from this file (only present when include_chunk_content=True)",
    )

class QueryEvalResponse(BaseModel):
    response: str = Field(description="The generated response")
    references: List[ReferenceItem] = Field(
        default_factory=list,
        description="Reference list with optional chunk content",
    )
    data: Dict[str, Any] = Field(
        default_factory=dict,
        description="Structured retrieval data for the same query run",
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Metadata for the same query run",
    )
    chat_id: Optional[int] = Field(default=None, description="Persisted chat id")
    user_message_id: Optional[int] = Field(
        default=None, description="Persisted user question message id"
    )
    assistant_message_id: Optional[int] = Field(
        default=None, description="Persisted assistant message id"
    )

class QueryResponse(BaseModel):
    response: str = Field(
        description="The generated response",
    )
    references: Optional[List[ReferenceItem]] = Field(
        default=None,
        description="Reference list (Disabled when include_references=False, /query/data always includes references.)",
    )
    trace: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Full retrieval trace payload for the same query run (included when include_trace=True).",
    )
    chat_id: Optional[int] = Field(default=None, description="Persisted chat id")
    user_message_id: Optional[int] = Field(
        default=None, description="Persisted user question message id"
    )
    assistant_message_id: Optional[int] = Field(
        default=None, description="Persisted assistant message id"
    )


class QueryDataResponse(BaseModel):
    status: str = Field(description="Query execution status")
    message: str = Field(description="Status message")
    data: Dict[str, Any] = Field(
        description="Query result data containing entities, relationships, chunks, and references"
    )
    metadata: Dict[str, Any] = Field(
        description="Query metadata including mode, keywords, and processing information"
    )
    chat_id: Optional[int] = Field(default=None, description="Persisted chat id")
    user_message_id: Optional[int] = Field(
        default=None, description="Persisted user question message id"
    )


class StreamChunkResponse(BaseModel):
    """Response model for streaming chunks in NDJSON format"""

    references: Optional[List[Dict[str, str]]] = Field(
        default=None,
        description="Reference list (only in first chunk when include_references=True)",
    )
    trace: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Trace payload (only in first chunk when include_trace=True)",
    )
    response: Optional[str] = Field(
        default=None, description="Response content chunk or complete response"
    )
    error: Optional[str] = Field(
        default=None, description="Error message if processing fails"
    )


class QueryChatSummaryResponse(BaseModel):
    id: int
    storage_id: int
    title: Optional[str] = None
    is_pinned: bool = False
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    message_count: int
    last_message_preview: Optional[str] = None


class QueryChatMessageResponse(BaseModel):
    id: int
    role: str
    content: str
    sequence_no: int
    created_at: Optional[datetime] = None
    retrieval_snapshot: Optional[Dict[str, Any]] = None


class QueryChatDetailResponse(BaseModel):
    id: int
    storage_id: int
    title: Optional[str] = None
    is_pinned: bool = False
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    messages: List[QueryChatMessageResponse] = Field(default_factory=list)


class QueryChatCreateRequest(BaseModel):
    title: Optional[str] = Field(default=None, max_length=255)


class QueryChatUpdateRequest(BaseModel):
    title: Optional[str] = Field(default=None, max_length=255)
    is_pinned: Optional[bool] = None


def _extract_storage_id(request_obj: Request) -> int:
    storage_id_raw = request_obj.path_params.get("storage_id")
    if storage_id_raw is None:
        raise HTTPException(
            status_code=400,
            detail="Missing storage_id in route. Query chat history requires tenant-scoped routes.",
        )
    try:
        return int(storage_id_raw)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Invalid storage_id") from exc


def _populate_history_if_needed(request: QueryRequest, storage_id: int):
    if request.chat_id and not request.conversation_history:
        init_db()
        db = SessionLocal()
        try:
            chat = (
                db.query(RetrievalChat)
                .filter(
                    RetrievalChat.id == request.chat_id,
                    RetrievalChat.storage_id == storage_id,
                )
                .options(selectinload(RetrievalChat.messages))
                .first()
            )
            if chat and chat.messages:
                ordered_messages = sorted(chat.messages, key=lambda m: m.sequence_no)
                request.conversation_history = [
                    {"role": m.role, "content": m.content} for m in ordered_messages
                ]
                logger.debug(f"Populated {len(request.conversation_history)} messages from chat_id={request.chat_id} into conversation_history")
            elif chat:
                logger.debug(f"Chat {request.chat_id} found but has no messages.")
        except Exception as e:
            logger.error(f"Failed to populate history for chat_id={request.chat_id}: {str(e)}")
        finally:
            db.close()


def _is_context_only(request: QueryRequest) -> bool:
    v1 = getattr(request, 'only_need_context', False)
    v2 = getattr(request, 'context_only', False)
    result = bool(v1 or v2)
    logger.info(f"[_is_context_only] only_need_context={v1}, context_only={v2} -> {result}")
    return result


def _question_content_for_chat(request: QueryRequest) -> str:
    query_text = request.query.strip()
    if not request.hl_keywords and not request.ll_keywords:
        return query_text

    lines = [query_text]
    if request.hl_keywords:
        lines.append(f"HL Keywords: {', '.join(request.hl_keywords)}")
    if request.ll_keywords:
        lines.append(f"LL Keywords: {', '.join(request.ll_keywords)}")
    return "\n".join(lines)


def _ensure_chat(
    db,
    *,
    storage_id: int,
    chat_id: int | None,
    title_hint: str,
) -> RetrievalChat:
    if chat_id is not None:
        logger.debug(f"Ensuring chat exists for chat_id={chat_id}, storage_id={storage_id}")
        chat = (
            db.query(RetrievalChat)
            .filter(
                RetrievalChat.id == chat_id,
                RetrievalChat.storage_id == storage_id,
            )
            .first()
        )
        if not chat:
            logger.error(f"Chat {chat_id} was not found for storage {storage_id}.")
            raise HTTPException(
                status_code=404,
                detail=f"Chat {chat_id} was not found for storage {storage_id}.",
            )
        logger.debug(f"Found existing chat: {chat.id}")
        return chat

    title_preview = (title_hint[:50] + "...") if title_hint else "N/A"
    logger.info(f"Creating new chat for storage_id={storage_id} with title hint: '{title_preview}'")
    chat = RetrievalChat(
        storage_id=storage_id,
        title=title_hint[:255] if title_hint else None,
        is_pinned=False,
    )
    db.add(chat)
    db.flush()
    logger.info(f"Successfully created new chat with id={chat.id}")
    return chat


def _next_sequence_no(db, chat_id: int) -> int:
    current_max = (
        db.query(func.max(RetrievalChatMessage.sequence_no))
        .filter(RetrievalChatMessage.chat_id == chat_id)
        .scalar()
    )
    return (current_max or 0) + 1


def _persist_query_turn(
    *,
    storage_id: int,
    request: QueryRequest,
    data: Dict[str, Any] | None,
    metadata: Dict[str, Any] | None,
    references: List[Dict[str, Any]] | None,
    trace: Dict[str, Any] | None,
    assistant_content: str | None,
    save_assistant_message: bool,
) -> Dict[str, Optional[int]]:
    query_preview = (request.query[:100] + "...") if request.query else "N/A"
    logger.info(f"Persisting query turn for storage_id={storage_id}. Query: '{query_preview}'")
    init_db()
    db = SessionLocal()
    try:
        chat = _ensure_chat(
            db,
            storage_id=storage_id,
            chat_id=request.chat_id,
            title_hint=request.query,
        )
        question_seq = _next_sequence_no(db, chat.id)
        logger.debug(f"Saving user message at sequence {question_seq}")
        user_message = RetrievalChatMessage(
            chat_id=chat.id,
            sequence_no=question_seq,
            role="user",
            content=_question_content_for_chat(request),
        )
        db.add(user_message)
        db.flush()

        logger.debug(f"Creating retrieval snapshot for message_id={user_message.id}")
        snapshot = RetrievalSnapshot(
            message_id=user_message.id,
            mode=request.mode,
            data=data or {},
            metadata_json=metadata or {},
            references=references or [],
            trace=trace,
        )
        db.add(snapshot)

        assistant_message_id: Optional[int] = None
        if save_assistant_message and assistant_content is not None:
            logger.info(f"Saving assistant message directly for chat_id={chat.id}. Content length: {len(assistant_content)}")
            assistant_message = RetrievalChatMessage(
                chat_id=chat.id,
                sequence_no=question_seq + 1,
                role="assistant",
                content=assistant_content,
            )
            db.add(assistant_message)
            db.flush()
            assistant_message_id = assistant_message.id
        elif not save_assistant_message:
            logger.debug("save_assistant_message is False, skipping direct assistant message save")

        chat.updated_at = datetime.now(timezone.utc)
        db.commit()
        logger.info(f"Successfully committed query turn persistence. chat_id={chat.id}, user_msg={user_message.id}, assistant_msg={assistant_message_id}")
        return {
            "chat_id": chat.id,
            "user_message_id": user_message.id,
            "assistant_message_id": assistant_message_id,
        }
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        logger.exception("Failed to persist query turn for storage_id=%s", storage_id)
        raise
    finally:
        db.close()


def _persist_assistant_message(*, chat_id: int, content: str) -> Optional[int]:
    logger.info(f"Starting to persist assistant message for chat_id={chat_id}. Content length: {len(content)}")
    if not content:
        logger.warning(f"Assistant content is empty for chat_id={chat_id}! Not persisting.")
        return None
    init_db()
    db = SessionLocal()
    try:
        chat = db.query(RetrievalChat).filter(RetrievalChat.id == chat_id).first()
        if not chat:
            logger.error(f"Chat {chat_id} not found when trying to persist assistant message!")
            return None
        assistant_message = RetrievalChatMessage(
            chat_id=chat.id,
            sequence_no=_next_sequence_no(db, chat.id),
            role="assistant",
            content=content,
        )
        db.add(assistant_message)
        db.flush()
        chat.updated_at = datetime.now(timezone.utc)
        db.commit()
        logger.info(f"Successfully saved assistant message {assistant_message.id} for chat {chat.id}")
        return assistant_message.id
    except Exception as e:
        db.rollback()
        logger.exception("Failed to persist assistant message for chat_id=%s: %s", chat_id, str(e))
        return None
    finally:
        db.close()



def create_query_routes(rag_dependency, api_key: Optional[str] = None):
    combined_auth = get_combined_auth_dependency(api_key)
    
    # Create new router instance
    router = APIRouter(tags=["query"])
    from retriqs import LightRAG

    @router.get(
        "/query/chats",
        response_model=List[QueryChatSummaryResponse],
        dependencies=[Depends(combined_auth)],
    )
    async def list_query_chats(request_obj: Request):
        storage_id = _extract_storage_id(request_obj)
        init_db()
        db = SessionLocal()
        try:
            chats = (
                db.query(RetrievalChat)
                .filter(RetrievalChat.storage_id == storage_id)
                .options(selectinload(RetrievalChat.messages))
                .order_by(RetrievalChat.is_pinned.desc(), RetrievalChat.updated_at.desc())
                .all()
            )

            summaries: List[QueryChatSummaryResponse] = []
            for chat in chats:
                ordered_messages = sorted(chat.messages, key=lambda m: m.sequence_no)
                last_message = ordered_messages[-1].content if ordered_messages else None
                previews = (
                    f"{last_message[:120]}..."
                    if last_message and len(last_message) > 120
                    else last_message
                )
                summaries.append(
                    QueryChatSummaryResponse(
                        id=chat.id,
                        storage_id=chat.storage_id,
                        title=chat.title,
                        is_pinned=bool(chat.is_pinned),
                        created_at=chat.created_at,
                        updated_at=chat.updated_at,
                        message_count=len(ordered_messages),
                        last_message_preview=previews,
                    )
                )
            return summaries
        finally:
            db.close()

    @router.post(
        "/query/chats",
        response_model=QueryChatSummaryResponse,
        dependencies=[Depends(combined_auth)],
    )
    async def create_query_chat(data: QueryChatCreateRequest, request_obj: Request):
        storage_id = _extract_storage_id(request_obj)
        init_db()
        db = SessionLocal()
        try:
            title = (data.title or "").strip()
            chat = RetrievalChat(
                storage_id=storage_id,
                title=title[:255] if title else "New chat",
                is_pinned=False,
            )
            db.add(chat)
            db.commit()
            db.refresh(chat)
            return QueryChatSummaryResponse(
                id=chat.id,
                storage_id=chat.storage_id,
                title=chat.title,
                is_pinned=bool(chat.is_pinned),
                created_at=chat.created_at,
                updated_at=chat.updated_at,
                message_count=0,
                last_message_preview=None,
            )
        except Exception as e:
            db.rollback()
            logger.error("Failed to create chat: %s", e, exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))
        finally:
            db.close()

    @router.get(
        "/query/chats/{chat_id}",
        response_model=QueryChatDetailResponse,
        dependencies=[Depends(combined_auth)],
    )
    async def get_query_chat(chat_id: int, request_obj: Request):
        storage_id = _extract_storage_id(request_obj)
        init_db()
        db = SessionLocal()
        try:
            chat = (
                db.query(RetrievalChat)
                .filter(
                    RetrievalChat.id == chat_id,
                    RetrievalChat.storage_id == storage_id,
                )
                .options(
                    selectinload(RetrievalChat.messages).selectinload(
                        RetrievalChatMessage.retrieval_snapshot
                    )
                )
                .first()
            )
            if not chat:
                raise HTTPException(
                    status_code=404,
                    detail=f"Chat {chat_id} was not found for storage {storage_id}.",
                )

            messages = []
            for msg in sorted(chat.messages, key=lambda m: m.sequence_no):
                snapshot_payload = None
                if msg.retrieval_snapshot:
                    snapshot_payload = {
                        "mode": msg.retrieval_snapshot.mode,
                        "data": msg.retrieval_snapshot.data or {},
                        "metadata": msg.retrieval_snapshot.metadata_json or {},
                        "references": msg.retrieval_snapshot.references or [],
                        "trace": msg.retrieval_snapshot.trace,
                        "created_at": msg.retrieval_snapshot.created_at,
                    }
                messages.append(
                    QueryChatMessageResponse(
                        id=msg.id,
                        role=msg.role,
                        content=msg.content,
                        sequence_no=msg.sequence_no,
                        created_at=msg.created_at,
                        retrieval_snapshot=snapshot_payload,
                    )
                )

            return QueryChatDetailResponse(
                id=chat.id,
                storage_id=chat.storage_id,
                title=chat.title,
                is_pinned=bool(chat.is_pinned),
                created_at=chat.created_at,
                updated_at=chat.updated_at,
                messages=messages,
            )
        finally:
            db.close()

    @router.patch(
        "/query/chats/{chat_id}",
        response_model=QueryChatSummaryResponse,
        dependencies=[Depends(combined_auth)],
    )
    async def update_query_chat(
        chat_id: int, data: QueryChatUpdateRequest, request_obj: Request
    ):
        storage_id = _extract_storage_id(request_obj)
        init_db()
        db = SessionLocal()
        try:
            chat = (
                db.query(RetrievalChat)
                .filter(
                    RetrievalChat.id == chat_id,
                    RetrievalChat.storage_id == storage_id,
                )
                .options(selectinload(RetrievalChat.messages))
                .first()
            )
            if not chat:
                raise HTTPException(
                    status_code=404,
                    detail=f"Chat {chat_id} was not found for storage {storage_id}.",
                )

            if data.title is not None:
                chat.title = data.title.strip()[:255] or "New chat"
            if data.is_pinned is not None:
                chat.is_pinned = data.is_pinned
            chat.updated_at = datetime.now(timezone.utc)
            db.commit()
            db.refresh(chat)

            ordered_messages = sorted(chat.messages, key=lambda m: m.sequence_no)
            last_message = ordered_messages[-1].content if ordered_messages else None
            preview = (
                f"{last_message[:120]}..."
                if last_message and len(last_message) > 120
                else last_message
            )
            return QueryChatSummaryResponse(
                id=chat.id,
                storage_id=chat.storage_id,
                title=chat.title,
                is_pinned=bool(chat.is_pinned),
                created_at=chat.created_at,
                updated_at=chat.updated_at,
                message_count=len(ordered_messages),
                last_message_preview=preview,
            )
        except HTTPException:
            db.rollback()
            raise
        except Exception as e:
            db.rollback()
            logger.error("Failed to update chat %s: %s", chat_id, e, exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))
        finally:
            db.close()

    @router.delete(
        "/query/chats/{chat_id}",
        dependencies=[Depends(combined_auth)],
    )
    async def delete_query_chat(chat_id: int, request_obj: Request):
        storage_id = _extract_storage_id(request_obj)
        init_db()
        db = SessionLocal()
        try:
            chat = (
                db.query(RetrievalChat)
                .filter(
                    RetrievalChat.id == chat_id,
                    RetrievalChat.storage_id == storage_id,
                )
                .first()
            )
            if not chat:
                raise HTTPException(
                    status_code=404,
                    detail=f"Chat {chat_id} was not found for storage {storage_id}.",
                )
            db.delete(chat)
            db.commit()
            return {"status": "deleted", "chat_id": chat_id}
        except HTTPException:
            db.rollback()
            raise
        except Exception as e:
            db.rollback()
            logger.error("Failed to delete chat %s: %s", chat_id, e, exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))
        finally:
            db.close()

    @router.post(
        "/query",
        response_model=QueryResponse,
        dependencies=[Depends(combined_auth)],
        responses={
            200: {
                "description": "Successful RAG query response",
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "response": {
                                    "type": "string",
                                    "description": "The generated response from the RAG system",
                                },
                                "references": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "reference_id": {"type": "string"},
                                            "file_path": {"type": "string"},
                                            "content": {
                                                "type": "array",
                                                "items": {"type": "string"},
                                                "description": "List of chunk contents from this file (only included when include_chunk_content=True)",
                                            },
                                        },
                                    },
                                    "description": "Reference list (only included when include_references=True)",
                                },
                            },
                            "required": ["response"],
                        },
                        "examples": {
                            "with_references": {
                                "summary": "Response with references",
                                "description": "Example response when include_references=True",
                                "value": {
                                    "response": "Artificial Intelligence (AI) is a branch of computer science that aims to create intelligent machines capable of performing tasks that typically require human intelligence, such as learning, reasoning, and problem-solving.",
                                    "references": [
                                        {
                                            "reference_id": "1",
                                            "file_path": "/documents/ai_overview.pdf",
                                        },
                                        {
                                            "reference_id": "2",
                                            "file_path": "/documents/machine_learning.txt",
                                        },
                                    ],
                                },
                            },
                            "with_chunk_content": {
                                "summary": "Response with chunk content",
                                "description": "Example response when include_references=True and include_chunk_content=True. Note: content is an array of chunks from the same file.",
                                "value": {
                                    "response": "Artificial Intelligence (AI) is a branch of computer science that aims to create intelligent machines capable of performing tasks that typically require human intelligence, such as learning, reasoning, and problem-solving.",
                                    "references": [
                                        {
                                            "reference_id": "1",
                                            "file_path": "/documents/ai_overview.pdf",
                                            "content": [
                                                "Artificial Intelligence (AI) represents a transformative field in computer science focused on creating systems that can perform tasks requiring human-like intelligence. These tasks include learning from experience, understanding natural language, recognizing patterns, and making decisions.",
                                                "AI systems can be categorized into narrow AI, which is designed for specific tasks, and general AI, which aims to match human cognitive abilities across a wide range of domains.",
                                            ],
                                        },
                                        {
                                            "reference_id": "2",
                                            "file_path": "/documents/machine_learning.txt",
                                            "content": [
                                                "Machine learning is a subset of AI that enables computers to learn and improve from experience without being explicitly programmed. It focuses on the development of algorithms that can access data and use it to learn for themselves."
                                            ],
                                        },
                                    ],
                                },
                            },
                            "without_references": {
                                "summary": "Response without references",
                                "description": "Example response when include_references=False",
                                "value": {
                                    "response": "Artificial Intelligence (AI) is a branch of computer science that aims to create intelligent machines capable of performing tasks that typically require human intelligence, such as learning, reasoning, and problem-solving."
                                },
                            },
                            "different_modes": {
                                "summary": "Different query modes",
                                "description": "Examples of responses from different query modes",
                                "value": {
                                    "local_mode": "Focuses on specific entities and their relationships",
                                    "global_mode": "Provides broader context from relationship patterns",
                                    "hybrid_mode": "Combines local and global approaches",
                                    "naive_mode": "Simple vector similarity search",
                                    "mix_mode": "Integrates knowledge graph and vector retrieval",
                                },
                            },
                        },
                    }
                },
            },
            400: {
                "description": "Bad Request - Invalid input parameters",
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {"detail": {"type": "string"}},
                        },
                        "example": {
                            "detail": "Query text must be at least 3 characters long"
                        },
                    }
                },
            },
            500: {
                "description": "Internal Server Error - Query processing failed",
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {"detail": {"type": "string"}},
                        },
                        "example": {
                            "detail": "Failed to process query: LLM service unavailable"
                        },
                    }
                },
            },
        },
    )
    async def query_text(
        request: QueryRequest,
        request_obj: Request,
        rag: LightRAG = Depends(rag_dependency),
    ):
        """
        Comprehensive RAG query endpoint with non-streaming response. Parameter "stream" is ignored.

        This endpoint performs Retrieval-Augmented Generation (RAG) queries using various modes
        to provide intelligent responses based on your knowledge base.

        **Query Modes:**
        - **local**: Focuses on specific entities and their direct relationships
        - **global**: Analyzes broader patterns and relationships across the knowledge graph
        - **hybrid**: Combines local and global approaches for comprehensive results
        - **naive**: Simple vector similarity search without knowledge graph
        - **mix**: Integrates knowledge graph retrieval with vector search (recommended)
        - **bypass**: Direct LLM query without knowledge retrieval

        conversation_history parameteris sent to LLM only, does not affect retrieval results.

        **Usage Examples:**

        Basic query:
        ```json
        {
            "query": "What is machine learning?",
            "mode": "mix"
        }
        ```

        Bypass initial LLM call by providing high-level and low-level keywords:
        ```json
        {
            "query": "What is Retrieval-Augmented-Generation?",
            "hl_keywords": ["machine learning", "information retrieval", "natural language processing"],
            "ll_keywords": ["retrieval augmented generation", "RAG", "knowledge base"],
            "mode": "mix"
        }
        ```

        Advanced query with references:
        ```json
        {
            "query": "Explain neural networks",
            "mode": "hybrid",
            "include_references": true,
            "response_type": "Multiple Paragraphs",
            "top_k": 10
        }
        ```

        Conversation with history:
        ```json
        {
            "query": "Can you give me more details?",
            "conversation_history": [
                {"role": "user", "content": "What is AI?"},
                {"role": "assistant", "content": "AI is artificial intelligence..."}
            ]
        }
        ```

        Args:
            request (QueryRequest): The request object containing query parameters:
                - **query**: The question or prompt to process (min 3 characters)
                - **mode**: Query strategy - "mix" recommended for best results
                - **include_references**: Whether to include source citations
                - **response_type**: Format preference (e.g., "Multiple Paragraphs")
                - **top_k**: Number of top entities/relations to retrieve
                - **conversation_history**: Previous dialogue context
                - **max_total_tokens**: Token budget for the entire response

        Returns:
            QueryResponse: JSON response containing:
                - **response**: The generated answer to your query
                - **references**: Source citations (if include_references=True)

        Raises:
            HTTPException:
                - 400: Invalid input parameters (e.g., query too short)
                - 500: Internal processing error (e.g., LLM service unavailable)
        """
        try:
            query_preview = (request.query[:100] + "...") if request.query else "N/A"
            logger.info(f"Processing query request: '{query_preview}' (mode={request.mode})")
            
            storage_id = _extract_storage_id(request_obj)
            _populate_history_if_needed(request, storage_id)

            param = request.to_query_params(
                False
            )  # Ensure stream=False for non-streaming endpoint
            # Force stream=False for /query endpoint regardless of include_references setting
            param.stream = False

            # Check if this is a context-only retrieval
            is_context_only = _is_context_only(request)

            if is_context_only:
                logger.info("Context-only retrieval requested. Calling rag.aquery_data...")
                result = await rag.aquery_data(request.query, param=param)
                
                # For context-only, we treat the formatted context as the response
                response_content = getattr(result, "content", "No relevant context found.")
                data = getattr(result, "raw_data", {})
                references = data.get("references", [])
                metadata = {} # aquery_data might not return metadata in the same way
            else:
                # Unified approach: always use aquery_llm for normal queries
                logger.debug("Calling rag.aquery_llm...")
                result = await rag.aquery_llm(request.query, param=param)
                logger.debug("Result received from rag.aquery_llm")

                # Extract LLM response and references from unified result
                llm_response = result.get("llm_response", {})
                data = result.get("data", {})
                references = data.get("references", [])
                metadata = result.get("metadata", {}) or {}

                # Get the non-streaming response content
                response_content = llm_response.get("content", "")
                if not response_content:
                    response_content = "No relevant context found for the query."

            # Enrich references with chunk content if requested
            if request.include_references and request.include_chunk_content:
                chunks = data.get("chunks", [])
                # Create a mapping from reference_id to chunk content
                ref_id_to_content = {}
                for chunk in chunks:
                    ref_id = chunk.get("reference_id", "")
                    content = chunk.get("content", "")
                    if ref_id and content:
                        # Collect chunk content; join later to avoid quadratic string concatenation
                        ref_id_to_content.setdefault(ref_id, []).append(content)

                # Add content to references
                enriched_references = []
                for ref in references:
                    ref_copy = ref.copy()
                    ref_id = ref.get("reference_id", "")
                    if ref_id in ref_id_to_content:
                        # Keep content as a list of chunks (one file may have multiple chunks)
                        ref_copy["content"] = ref_id_to_content[ref_id]
                    enriched_references.append(ref_copy)
                references = enriched_references

            # Return response with or without references based on request
            trace = None
            if request.include_trace:
                trace = {
                    "data": data,
                    "metadata": metadata,
                }

            persistence = _persist_query_turn(
                storage_id=storage_id,
                request=request,
                data=data,
                metadata=metadata,
                references=references,
                trace=trace if trace else {"data": data, "metadata": metadata},
                assistant_content=response_content,
                save_assistant_message=True,
            )

            if request.include_references:
                return QueryResponse(
                    response=response_content,
                    references=references,
                    trace=trace,
                    chat_id=persistence["chat_id"],
                    user_message_id=persistence["user_message_id"],
                    assistant_message_id=persistence["assistant_message_id"],
                )
            else:
                return QueryResponse(
                    response=response_content,
                    references=None,
                    trace=trace,
                    chat_id=persistence["chat_id"],
                    user_message_id=persistence["user_message_id"],
                    assistant_message_id=persistence["assistant_message_id"],
                )
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error processing query: {str(e)}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))

    @router.post(
        "/query/stream",
        dependencies=[Depends(combined_auth)],
        responses={
            200: {
                "description": "Flexible RAG query response - format depends on stream parameter",
                "content": {
                    "application/x-ndjson": {
                        "schema": {
                            "type": "string",
                            "format": "ndjson",
                            "description": "Newline-delimited JSON (NDJSON) format used for both streaming and non-streaming responses. For streaming: multiple lines with separate JSON objects. For non-streaming: single line with complete JSON object.",
                            "example": '{"references": [{"reference_id": "1", "file_path": "/documents/ai.pdf"}]}\n{"response": "Artificial Intelligence is"}\n{"response": " a field of computer science"}\n{"response": " that focuses on creating intelligent machines."}',
                        },
                        "examples": {
                            "streaming_with_references": {
                                "summary": "Streaming mode with references (stream=true)",
                                "description": "Multiple NDJSON lines when stream=True and include_references=True. First line contains references, subsequent lines contain response chunks.",
                                "value": '{"references": [{"reference_id": "1", "file_path": "/documents/ai_overview.pdf"}, {"reference_id": "2", "file_path": "/documents/ml_basics.txt"}]}\n{"response": "Artificial Intelligence (AI) is a branch of computer science"}\n{"response": " that aims to create intelligent machines capable of performing"}\n{"response": " tasks that typically require human intelligence, such as learning,"}\n{"response": " reasoning, and problem-solving."}',
                            },
                            "streaming_with_chunk_content": {
                                "summary": "Streaming mode with chunk content (stream=true, include_chunk_content=true)",
                                "description": "Multiple NDJSON lines when stream=True, include_references=True, and include_chunk_content=True. First line contains references with content arrays (one file may have multiple chunks), subsequent lines contain response chunks.",
                                "value": '{"references": [{"reference_id": "1", "file_path": "/documents/ai_overview.pdf", "content": ["Artificial Intelligence (AI) represents a transformative field...", "AI systems can be categorized into narrow AI and general AI..."]}, {"reference_id": "2", "file_path": "/documents/ml_basics.txt", "content": ["Machine learning is a subset of AI that enables computers to learn..."]}]}\n{"response": "Artificial Intelligence (AI) is a branch of computer science"}\n{"response": " that aims to create intelligent machines capable of performing"}\n{"response": " tasks that typically require human intelligence."}',
                            },
                            "streaming_without_references": {
                                "summary": "Streaming mode without references (stream=true)",
                                "description": "Multiple NDJSON lines when stream=True and include_references=False. Only response chunks are sent.",
                                "value": '{"response": "Machine learning is a subset of artificial intelligence"}\n{"response": " that enables computers to learn and improve from experience"}\n{"response": " without being explicitly programmed for every task."}',
                            },
                            "non_streaming_with_references": {
                                "summary": "Non-streaming mode with references (stream=false)",
                                "description": "Single NDJSON line when stream=False and include_references=True. Complete response with references in one message.",
                                "value": '{"references": [{"reference_id": "1", "file_path": "/documents/neural_networks.pdf"}], "response": "Neural networks are computational models inspired by biological neural networks that consist of interconnected nodes (neurons) organized in layers. They are fundamental to deep learning and can learn complex patterns from data through training processes."}',
                            },
                            "non_streaming_without_references": {
                                "summary": "Non-streaming mode without references (stream=false)",
                                "description": "Single NDJSON line when stream=False and include_references=False. Complete response only.",
                                "value": '{"response": "Deep learning is a subset of machine learning that uses neural networks with multiple layers (hence deep) to model and understand complex patterns in data. It has revolutionized fields like computer vision, natural language processing, and speech recognition."}',
                            },
                            "error_response": {
                                "summary": "Error during streaming",
                                "description": "Error handling in NDJSON format when an error occurs during processing.",
                                "value": '{"references": [{"reference_id": "1", "file_path": "/documents/ai.pdf"}]}\n{"response": "Artificial Intelligence is"}\n{"error": "LLM service temporarily unavailable"}',
                            },
                        },
                    }
                },
            },
            400: {
                "description": "Bad Request - Invalid input parameters",
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {"detail": {"type": "string"}},
                        },
                        "example": {
                            "detail": "Query text must be at least 3 characters long"
                        },
                    }
                },
            },
            500: {
                "description": "Internal Server Error - Query processing failed",
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {"detail": {"type": "string"}},
                        },
                        "example": {
                            "detail": "Failed to process streaming query: Knowledge graph unavailable"
                        },
                    }
                },
            },
        },
    )
    async def query_text_stream(
        request: QueryRequest,
        request_obj: Request,
        rag: LightRAG = Depends(rag_dependency),
    ):
        """
        Advanced RAG query endpoint with flexible streaming response.

        This endpoint provides the most flexible querying experience, supporting both real-time streaming
        and complete response delivery based on your integration needs.

        **Response Modes:**
        - Real-time response delivery as content is generated
        - NDJSON format: each line is a separate JSON object
        - First line: `{"references": [...]}` (if include_references=True)
        - Subsequent lines: `{"response": "content chunk"}`
        - Error handling: `{"error": "error message"}`

        > If stream parameter is False, or the query hit LLM cache, complete response delivered in a single streaming message.

        **Response Format Details**
        - **Content-Type**: `application/x-ndjson` (Newline-Delimited JSON)
        - **Structure**: Each line is an independent, valid JSON object
        - **Parsing**: Process line-by-line, each line is self-contained
        - **Headers**: Includes cache control and connection management

        **Query Modes (same as /query endpoint)**
        - **local**: Entity-focused retrieval with direct relationships
        - **global**: Pattern analysis across the knowledge graph
        - **hybrid**: Combined local and global strategies
        - **naive**: Vector similarity search only
        - **mix**: Integrated knowledge graph + vector retrieval (recommended)
        - **bypass**: Direct LLM query without knowledge retrieval

        conversation_history parameteris sent to LLM only, does not affect retrieval results.

        **Usage Examples**

        Real-time streaming query:
        ```json
        {
            "query": "Explain machine learning algorithms",
            "mode": "mix",
            "stream": true,
            "include_references": true
        }
        ```

        Bypass initial LLM call by providing high-level and low-level keywords:
        ```json
        {
            "query": "What is Retrieval-Augmented-Generation?",
            "hl_keywords": ["machine learning", "information retrieval", "natural language processing"],
            "ll_keywords": ["retrieval augmented generation", "RAG", "knowledge base"],
            "mode": "mix"
        }
        ```

        Complete response query:
        ```json
        {
            "query": "What is deep learning?",
            "mode": "hybrid",
            "stream": false,
            "response_type": "Multiple Paragraphs"
        }
        ```

        Conversation with context:
        ```json
        {
            "query": "Can you elaborate on that?",
            "stream": true,
            "conversation_history": [
                {"role": "user", "content": "What is neural network?"},
                {"role": "assistant", "content": "A neural network is..."}
            ]
        }
        ```

        **Response Processing:**

        ```python
        async for line in response.iter_lines():
            data = json.loads(line)
            if "references" in data:
                # Handle references (first message)
                references = data["references"]
            if "response" in data:
                # Handle content chunk
                content_chunk = data["response"]
            if "error" in data:
                # Handle error
                error_message = data["error"]
        ```

        **Error Handling:**
        - Streaming errors are delivered as `{"error": "message"}` lines
        - Non-streaming errors raise HTTP exceptions
        - Partial responses may be delivered before errors in streaming mode
        - Always check for error objects when processing streaming responses

        Args:
            request (QueryRequest): The request object containing query parameters:
                - **query**: The question or prompt to process (min 3 characters)
                - **mode**: Query strategy - "mix" recommended for best results
                - **stream**: Enable streaming (True) or complete response (False)
                - **include_references**: Whether to include source citations
                - **response_type**: Format preference (e.g., "Multiple Paragraphs")
                - **top_k**: Number of top entities/relations to retrieve
                - **conversation_history**: Previous dialogue context for multi-turn conversations
                - **max_total_tokens**: Token budget for the entire response

        Returns:
            StreamingResponse: NDJSON streaming response containing:
                - **Streaming mode**: Multiple JSON objects, one per line
                  - References object (if requested): `{"references": [...]}`
                  - Content chunks: `{"response": "chunk content"}`
                  - Error objects: `{"error": "error message"}`
                - **Non-streaming mode**: Single JSON object
                  - Complete response: `{"references": [...], "response": "complete content"}`

        Raises:
            HTTPException:
                - 400: Invalid input parameters (e.g., query too short, invalid mode)
                - 500: Internal processing error (e.g., LLM service unavailable)

        Note:
            This endpoint is ideal for applications requiring flexible response delivery.
            Use streaming mode for real-time interfaces and non-streaming for batch processing.
        """
        try:
            query_preview = (request.query[:100] + "...") if request.query else "N/A"
            logger.info(f"Processing streaming query request: '{query_preview}' (mode={request.mode})")
            
            storage_id = _extract_storage_id(request_obj)
            _populate_history_if_needed(request, storage_id)

            # Use the stream parameter from the request, defaulting to True if not specified
            stream_mode = request.stream if request.stream is not None else True
            param = request.to_query_params(stream_mode)
            
            # Check if this is a context-only retrieval
            is_context_only = _is_context_only(request)

            from fastapi.responses import StreamingResponse

            if is_context_only:
                # Force stream=False for context-only retrieval
                param.stream = False
                logger.info("Context-only retrieval requested for stream endpoint. Calling rag.aquery_data...")
                result = await rag.aquery_data(request.query, param=param)
                
                # For context-only, we treat the formatted context as the response
                response_content = getattr(result, "content", "No relevant context found.")
                data = getattr(result, "raw_data", {})
                metadata = {}
                references = data.get("references", []) or []
                trace = {"data": data, "metadata": metadata}

                # We bypass the complex stream generator and just yield one record
                async def context_stream_generator():
                    persisted_ids = _persist_query_turn(
                        storage_id=storage_id,
                        request=request,
                        data=data,
                        metadata=metadata,
                        references=references,
                        trace=trace,
                        assistant_content=response_content,
                        save_assistant_message=True,
                    )
                    
                    complete_response = {
                        "response": response_content,
                        "references": references,
                        "trace": trace,
                        "chat_id": persisted_ids["chat_id"],
                        "user_message_id": persisted_ids["user_message_id"],
                        "assistant_message_id": persisted_ids["assistant_message_id"],
                    }
                    yield f"{json.dumps(complete_response)}\n"
                
                return StreamingResponse(
                    context_stream_generator(),
                    media_type="application/x-ndjson",
                    headers={
                        "Cache-Control": "no-cache",
                        "Connection": "keep-alive",
                        "Content-Type": "application/x-ndjson",
                        "X-Accel-Buffering": "no",
                    },
                )

            # Unified approach: always use aquery_llm for normal streaming queries
            logger.debug("Calling rag.aquery_llm (streaming)...")
            result = await rag.aquery_llm(request.query, param=param)
            logger.debug("Result received from rag.aquery_llm")
            data = result.get("data", {}) or {}
            metadata = result.get("metadata", {}) or {}
            references = data.get("references", []) or []
            trace = {"data": data, "metadata": metadata}
            llm_response = result.get("llm_response", {})

            if request.include_references and request.include_chunk_content:
                chunks = data.get("chunks", [])
                ref_id_to_content = {}
                for chunk in chunks:
                    ref_id = chunk.get("reference_id", "")
                    content = chunk.get("content", "")
                    if ref_id and content:
                        ref_id_to_content.setdefault(ref_id, []).append(content)

                enriched_references = []
                for ref in references:
                    ref_copy = ref.copy()
                    ref_id = ref.get("reference_id", "")
                    if ref_id in ref_id_to_content:
                        ref_copy["content"] = ref_id_to_content[ref_id]
                    enriched_references.append(ref_copy)
                refs_for_response = enriched_references
            else:
                refs_for_response = references

            persisted_ids = _persist_query_turn(
                storage_id=storage_id,
                request=request,
                data=data,
                metadata=metadata,
                references=refs_for_response,
                trace=trace,
                assistant_content=None,
                save_assistant_message=True,
            )

            async def stream_generator():
                response_chunks: List[str] = []

                if llm_response.get("is_streaming"):
                    # Streaming mode: send references first, then stream response chunks
                    first_payload = {}
                    if request.include_references:
                        first_payload["references"] = refs_for_response
                    if request.include_trace:
                        first_payload["trace"] = trace
                    first_payload["chat"] = {
                        "chat_id": persisted_ids["chat_id"],
                        "user_message_id": persisted_ids["user_message_id"],
                        "assistant_message_id": persisted_ids["assistant_message_id"],
                    }
                    if first_payload:
                        yield f"{json.dumps(first_payload)}\n"

                    response_stream = llm_response.get("response_iterator")
                    if response_stream:
                        try:
                            logger.info(f"Starting to yield stream chunks for chat {persisted_ids.get('chat_id')}.")
                            async for chunk in response_stream:
                                if chunk:  # Only send non-empty content
                                    response_chunks.append(chunk)
                                    yield f"{json.dumps({'response': chunk})}\n"
                        except Exception as e:
                            logger.error(f"Streaming error: {str(e)}")
                            yield f"{json.dumps({'error': str(e)})}\n"

                        logger.info(f"Stream generating finished. Received {len(response_chunks)} chunks.")
                        full_content = "".join(response_chunks)
                        logger.info(f"Full streaming generated response length: {len(full_content)}. Persisting...")

                        # Save the assistant message to db only on the last chunk
                        if persisted_ids["chat_id"]:
                            persisted_ids["assistant_message_id"] = _persist_assistant_message(
                                chat_id=persisted_ids["chat_id"],
                                content=full_content,
                            )
                        
                        # Signal to the frontend that generation and persistence is fully complete
                        yield f"{json.dumps({'done': True, 'assistant_message_id': persisted_ids.get('assistant_message_id')})}\n"
                else:
                    # Non-streaming mode: send complete response in one message
                    response_content = llm_response.get("content", "")
                    if not response_content:
                        response_content = "No relevant context found for the query."
                    if not _is_context_only(request) and persisted_ids["chat_id"]:
                        persisted_ids["assistant_message_id"] = _persist_assistant_message(
                            chat_id=persisted_ids["chat_id"],
                            content=response_content,
                        )

                    # Create complete response object
                    complete_response = {
                        "response": response_content,
                        "chat_id": persisted_ids["chat_id"],
                        "user_message_id": persisted_ids["user_message_id"],
                        "assistant_message_id": persisted_ids["assistant_message_id"],
                    }
                    if request.include_references:
                        complete_response["references"] = refs_for_response
                    if request.include_trace:
                        complete_response["trace"] = trace

                    yield f"{json.dumps(complete_response)}\n"

            return StreamingResponse(
                stream_generator(),
                media_type="application/x-ndjson",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "Content-Type": "application/x-ndjson",
                    "X-Accel-Buffering": "no",  # Ensure proper handling of streaming response when proxied by Nginx
                },
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error processing streaming query: {str(e)}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))

    @router.post(
        "/query/data",
        response_model=QueryDataResponse,
        dependencies=[Depends(combined_auth)],
        responses={
            200: {
                "description": "Successful data retrieval response with structured RAG data",
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "status": {
                                    "type": "string",
                                    "enum": ["success", "failure"],
                                    "description": "Query execution status",
                                },
                                "message": {
                                    "type": "string",
                                    "description": "Status message describing the result",
                                },
                                "data": {
                                    "type": "object",
                                    "properties": {
                                        "entities": {
                                            "type": "array",
                                            "items": {
                                                "type": "object",
                                                "properties": {
                                                    "entity_name": {"type": "string"},
                                                    "entity_type": {"type": "string"},
                                                    "description": {"type": "string"},
                                                    "source_id": {"type": "string"},
                                                    "file_path": {"type": "string"},
                                                    "reference_id": {"type": "string"},
                                                },
                                            },
                                            "description": "Retrieved entities from knowledge graph",
                                        },
                                        "relationships": {
                                            "type": "array",
                                            "items": {
                                                "type": "object",
                                                "properties": {
                                                    "src_id": {"type": "string"},
                                                    "tgt_id": {"type": "string"},
                                                    "description": {"type": "string"},
                                                    "keywords": {"type": "string"},
                                                    "weight": {"type": "number"},
                                                    "source_id": {"type": "string"},
                                                    "file_path": {"type": "string"},
                                                    "reference_id": {"type": "string"},
                                                },
                                            },
                                            "description": "Retrieved relationships from knowledge graph",
                                        },
                                        "chunks": {
                                            "type": "array",
                                            "items": {
                                                "type": "object",
                                                "properties": {
                                                    "content": {"type": "string"},
                                                    "file_path": {"type": "string"},
                                                    "chunk_id": {"type": "string"},
                                                    "reference_id": {"type": "string"},
                                                },
                                            },
                                            "description": "Retrieved text chunks from vector database",
                                        },
                                        "references": {
                                            "type": "array",
                                            "items": {
                                                "type": "object",
                                                "properties": {
                                                    "reference_id": {"type": "string"},
                                                    "file_path": {"type": "string"},
                                                },
                                            },
                                            "description": "Reference list for citation purposes",
                                        },
                                    },
                                    "description": "Structured retrieval data containing entities, relationships, chunks, and references",
                                },
                                "metadata": {
                                    "type": "object",
                                    "properties": {
                                        "query_mode": {"type": "string"},
                                        "keywords": {
                                            "type": "object",
                                            "properties": {
                                                "high_level": {
                                                    "type": "array",
                                                    "items": {"type": "string"},
                                                },
                                                "low_level": {
                                                    "type": "array",
                                                    "items": {"type": "string"},
                                                },
                                            },
                                        },
                                        "processing_info": {
                                            "type": "object",
                                            "properties": {
                                                "total_entities_found": {
                                                    "type": "integer"
                                                },
                                                "total_relations_found": {
                                                    "type": "integer"
                                                },
                                                "entities_after_truncation": {
                                                    "type": "integer"
                                                },
                                                "relations_after_truncation": {
                                                    "type": "integer"
                                                },
                                                "final_chunks_count": {
                                                    "type": "integer"
                                                },
                                            },
                                        },
                                    },
                                    "description": "Query metadata including mode, keywords, and processing information",
                                },
                            },
                            "required": ["status", "message", "data", "metadata"],
                        },
                        "examples": {
                            "successful_local_mode": {
                                "summary": "Local mode data retrieval",
                                "description": "Example of structured data from local mode query focusing on specific entities",
                                "value": {
                                    "status": "success",
                                    "message": "Query executed successfully",
                                    "data": {
                                        "entities": [
                                            {
                                                "entity_name": "Neural Networks",
                                                "entity_type": "CONCEPT",
                                                "description": "Computational models inspired by biological neural networks",
                                                "source_id": "chunk-123",
                                                "file_path": "/documents/ai_basics.pdf",
                                                "reference_id": "1",
                                            }
                                        ],
                                        "relationships": [
                                            {
                                                "src_id": "Neural Networks",
                                                "tgt_id": "Machine Learning",
                                                "description": "Neural networks are a subset of machine learning algorithms",
                                                "keywords": "subset, algorithm, learning",
                                                "weight": 0.85,
                                                "source_id": "chunk-123",
                                                "file_path": "/documents/ai_basics.pdf",
                                                "reference_id": "1",
                                            }
                                        ],
                                        "chunks": [
                                            {
                                                "content": "Neural networks are computational models that mimic the way biological neural networks work...",
                                                "file_path": "/documents/ai_basics.pdf",
                                                "chunk_id": "chunk-123",
                                                "reference_id": "1",
                                            }
                                        ],
                                        "references": [
                                            {
                                                "reference_id": "1",
                                                "file_path": "/documents/ai_basics.pdf",
                                            }
                                        ],
                                    },
                                    "metadata": {
                                        "query_mode": "local",
                                        "keywords": {
                                            "high_level": ["neural", "networks"],
                                            "low_level": [
                                                "computation",
                                                "model",
                                                "algorithm",
                                            ],
                                        },
                                        "processing_info": {
                                            "total_entities_found": 5,
                                            "total_relations_found": 3,
                                            "entities_after_truncation": 1,
                                            "relations_after_truncation": 1,
                                            "final_chunks_count": 1,
                                        },
                                    },
                                },
                            },
                            "global_mode": {
                                "summary": "Global mode data retrieval",
                                "description": "Example of structured data from global mode query analyzing broader patterns",
                                "value": {
                                    "status": "success",
                                    "message": "Query executed successfully",
                                    "data": {
                                        "entities": [],
                                        "relationships": [
                                            {
                                                "src_id": "Artificial Intelligence",
                                                "tgt_id": "Machine Learning",
                                                "description": "AI encompasses machine learning as a core component",
                                                "keywords": "encompasses, component, field",
                                                "weight": 0.92,
                                                "source_id": "chunk-456",
                                                "file_path": "/documents/ai_overview.pdf",
                                                "reference_id": "2",
                                            }
                                        ],
                                        "chunks": [],
                                        "references": [
                                            {
                                                "reference_id": "2",
                                                "file_path": "/documents/ai_overview.pdf",
                                            }
                                        ],
                                    },
                                    "metadata": {
                                        "query_mode": "global",
                                        "keywords": {
                                            "high_level": [
                                                "artificial",
                                                "intelligence",
                                                "overview",
                                            ],
                                            "low_level": [],
                                        },
                                    },
                                },
                            },
                            "naive_mode": {
                                "summary": "Naive mode data retrieval",
                                "description": "Example of structured data from naive mode using only vector search",
                                "value": {
                                    "status": "success",
                                    "message": "Query executed successfully",
                                    "data": {
                                        "entities": [],
                                        "relationships": [],
                                        "chunks": [
                                            {
                                                "content": "Deep learning is a subset of machine learning that uses neural networks with multiple layers...",
                                                "file_path": "/documents/deep_learning.pdf",
                                                "chunk_id": "chunk-789",
                                                "reference_id": "3",
                                            }
                                        ],
                                        "references": [
                                            {
                                                "reference_id": "3",
                                                "file_path": "/documents/deep_learning.pdf",
                                            }
                                        ],
                                    },
                                    "metadata": {
                                        "query_mode": "naive",
                                        "keywords": {"high_level": [], "low_level": []},
                                    },
                                },
                            },
                        },
                    }
                },
            },
            400: {
                "description": "Bad Request - Invalid input parameters",
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {"detail": {"type": "string"}},
                        },
                        "example": {
                            "detail": "Query text must be at least 3 characters long"
                        },
                    }
                },
            },
            500: {
                "description": "Internal Server Error - Data retrieval failed",
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {"detail": {"type": "string"}},
                        },
                        "example": {
                            "detail": "Failed to retrieve data: Knowledge graph unavailable"
                        },
                    }
                },
            },
        },
    )
    async def query_data(
        request: QueryRequest,
        request_obj: Request,
        rag: LightRAG = Depends(rag_dependency),
    ):
        """
        Advanced data retrieval endpoint for structured RAG analysis.

        This endpoint provides raw retrieval results without LLM generation, perfect for:
        - **Data Analysis**: Examine what information would be used for RAG
        - **System Integration**: Get structured data for custom processing
        - **Debugging**: Understand retrieval behavior and quality
        - **Research**: Analyze knowledge graph structure and relationships

        **Key Features:**
        - No LLM generation - pure data retrieval
        - Complete structured output with entities, relationships, and chunks
        - Always includes references for citation
        - Detailed metadata about processing and keywords
        - Compatible with all query modes and parameters

        **Query Mode Behaviors:**
        - **local**: Returns entities and their direct relationships + related chunks
        - **global**: Returns relationship patterns across the knowledge graph
        - **hybrid**: Combines local and global retrieval strategies
        - **naive**: Returns only vector-retrieved text chunks (no knowledge graph)
        - **mix**: Integrates knowledge graph data with vector-retrieved chunks
        - **bypass**: Returns empty data arrays (used for direct LLM queries)

        **Data Structure:**
        - **entities**: Knowledge graph entities with descriptions and metadata
        - **relationships**: Connections between entities with weights and descriptions
        - **chunks**: Text segments from documents with source information
        - **references**: Citation information mapping reference IDs to file paths
        - **metadata**: Processing information, keywords, and query statistics

        **Usage Examples:**

        Analyze entity relationships:
        ```json
        {
            "query": "machine learning algorithms",
            "mode": "local",
            "top_k": 10
        }
        ```

        Explore global patterns:
        ```json
        {
            "query": "artificial intelligence trends",
            "mode": "global",
            "max_relation_tokens": 2000
        }
        ```

        Vector similarity search:
        ```json
        {
            "query": "neural network architectures",
            "mode": "naive",
            "chunk_top_k": 5
        }
        ```

        Bypass initial LLM call by providing high-level and low-level keywords:
        ```json
        {
            "query": "What is Retrieval-Augmented-Generation?",
            "hl_keywords": ["machine learning", "information retrieval", "natural language processing"],
            "ll_keywords": ["retrieval augmented generation", "RAG", "knowledge base"],
            "mode": "mix"
        }
        ```

        **Response Analysis:**
        - **Empty arrays**: Normal for certain modes (e.g., naive mode has no entities/relationships)
        - **Processing info**: Shows retrieval statistics and token usage
        - **Keywords**: High-level and low-level keywords extracted from query
        - **Reference mapping**: Links all data back to source documents

        Args:
            request (QueryRequest): The request object containing query parameters:
                - **query**: The search query to analyze (min 3 characters)
                - **mode**: Retrieval strategy affecting data types returned
                - **top_k**: Number of top entities/relationships to retrieve
                - **chunk_top_k**: Number of text chunks to retrieve
                - **max_entity_tokens**: Token limit for entity context
                - **max_relation_tokens**: Token limit for relationship context
                - **max_total_tokens**: Overall token budget for retrieval

        Returns:
            QueryDataResponse: Structured JSON response containing:
                - **status**: "success" or "failure"
                - **message**: Human-readable status description
                - **data**: Complete retrieval results with entities, relationships, chunks, references
                - **metadata**: Query processing information and statistics

        Raises:
            HTTPException:
                - 400: Invalid input parameters (e.g., query too short, invalid mode)
                - 500: Internal processing error (e.g., knowledge graph unavailable)

        Note:
            This endpoint always includes references regardless of the include_references parameter,
            as structured data analysis typically requires source attribution.
        """
        try:
            param = request.to_query_params(False)  # No streaming for data endpoint
            response = await rag.aquery_data(request.query, param=param)

            # aquery_data returns the new format with status, message, data, and metadata
            if isinstance(response, dict):
                storage_id = _extract_storage_id(request_obj)
                data_payload = response.get("data", {}) or {}
                metadata_payload = response.get("metadata", {}) or {}
                persistence = _persist_query_turn(
                    storage_id=storage_id,
                    request=request,
                    data=data_payload,
                    metadata=metadata_payload,
                    references=data_payload.get("references", []) or [],
                    trace={"data": data_payload, "metadata": metadata_payload},
                    assistant_content=None,
                    save_assistant_message=False,
                )
                return QueryDataResponse(
                    **response,
                    chat_id=persistence["chat_id"],
                    user_message_id=persistence["user_message_id"],
                )
            else:
                # Handle unexpected response format
                return QueryDataResponse(
                    status="failure",
                    message="Invalid response type",
                    data={},
                    metadata={},
                )
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error processing data query: {str(e)}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))


    @router.post(
        "/query/eval",
        response_model=QueryEvalResponse,
        dependencies=[Depends(combined_auth)],
    )
    async def query_eval(
        request: QueryRequest,
        request_obj: Request,
        rag: LightRAG = Depends(rag_dependency),
    ):
        """
        Evaluation endpoint that returns everything needed in one non-streaming call:
        - final answer
        - references
        - chunks, entities, relationships
        - retrieval metadata

        This is intended for benchmarking and RAGAS.
        """
        try:
            param = request.to_query_params(False)
            param.stream = False

            # Check if this is a context-only retrieval
            is_context_only = _is_context_only(request)

            if is_context_only:
                logger.info("Context-only retrieval requested for eval endpoint. Calling rag.aquery_data...")
                result = await rag.aquery_data(request.query, param=param)
                
                # For context-only, formatted context is the response
                response_content = getattr(result, "content", "No relevant context found.")
                data = getattr(result, "raw_data", {})
                metadata = {}
                references = data.get("references", []) or []
            else:
                # Force evaluation-friendly behavior for normal LLM queries.
                request.include_references = True
                request.include_chunk_content = True
                request.include_trace = True

                logger.debug("Calling rag.aquery_llm (eval)...")
                result = await rag.aquery_llm(request.query, param=param)
                logger.debug("Result received from rag.aquery_llm")

                llm_response = result.get("llm_response", {})
                data = result.get("data", {}) or {}
                metadata = result.get("metadata", {}) or {}
                references = data.get("references", []) or []
                
                response_content = llm_response.get("content", "")
                if not response_content:
                    response_content = "No relevant context found for the query."

            chunks = data.get("chunks", []) or []

            # Attach chunk content to each reference_id.
            ref_id_to_content = {}
            for chunk in chunks:
                ref_id = chunk.get("reference_id", "")
                content = chunk.get("content", "")
                if ref_id and content:
                    ref_id_to_content.setdefault(ref_id, []).append(content)

            enriched_references = []
            for ref in references:
                ref_copy = ref.copy()
                ref_id = ref.get("reference_id", "")
                ref_copy["content"] = ref_id_to_content.get(ref_id, [])
                enriched_references.append(ref_copy)

            storage_id = _extract_storage_id(request_obj)
            trace = {"data": data, "metadata": metadata}
            persistence = _persist_query_turn(
                storage_id=storage_id,
                request=request,
                data=data,
                metadata=metadata,
                references=enriched_references,
                trace=trace,
                assistant_content=response_content,
                save_assistant_message=True,
            )

            return QueryEvalResponse(
                response=response_content,
                references=enriched_references,
                data=data,
                metadata=metadata,
                chat_id=persistence["chat_id"],
                user_message_id=persistence["user_message_id"],
                assistant_message_id=persistence["assistant_message_id"],
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error processing eval query: {str(e)}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))

    return router
