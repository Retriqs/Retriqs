from __future__ import annotations

import json
import logging
from typing import Any

from fastmcp import FastMCP

from retriqs.api.mcp_support import (
    build_mcp_query_param,
    normalize_retrieval_result,
    persist_mcp_retrieval_turn,
)

logger = logging.getLogger("lightrag")


def create_mcp_server(rag_manager):
    """
    Explicit MCP server for retrieval-only tools.

    Design intent:
    - MCP returns retrieved context only
    - the external model answers the user
    - a chat is still persisted in the app to show what was retrieved and sent out
    """
    mcp = FastMCP("Retriqs")

    async def _run_retrieve_context(
    *,
    storage_id: int,
    query: str,
    mode: str = "mix",
    top_k: int = 10,
    chunk_top_k: int | None = None,
    max_entity_tokens: int | None = None,
    max_relation_tokens: int | None = None,
    max_total_tokens: int | None = None,
    hl_keywords: list[str] | None = None,
    ll_keywords: list[str] | None = None,
    enable_rerank: bool | None = None,
    provider: str = "external_mcp_client",
    create_chat: bool = True,
    chat_id: int | None = None,
    tool_name: str = "retrieve_context",
    ) -> dict[str, Any]:
        instance = rag_manager.get_instance(storage_id)
        if not instance:
            return {"error": f"Storage with ID {storage_id} not found."}

        try:
            param = build_mcp_query_param(
                            mode=mode,
                            top_k=top_k,
                            chunk_top_k=chunk_top_k,
                            max_entity_tokens=max_entity_tokens,
                            max_relation_tokens=max_relation_tokens,
                            max_total_tokens=max_total_tokens,
                            hl_keywords=hl_keywords,
                            ll_keywords=ll_keywords,
                            enable_rerank=enable_rerank,
                        )
            raw_result = await instance.aquery_data(query, param=param)
            payload = normalize_retrieval_result(raw_result)

            persisted = None
            if create_chat:
                persisted = persist_mcp_retrieval_turn(
                    storage_id=storage_id,
                    query=query,
                    provider=provider,
                    tool_name=tool_name,
                    mode=mode,
                    context_text=payload["context_text"],
                    data=payload["data"],
                    metadata=payload["metadata"],
                    references=payload["references"],
                    chat_id=chat_id,
                )

            payload["origin"] = {
                "type": "mcp",
                "provider": provider,
                "tool_name": tool_name,
                "answer_generated_locally": False,
                "answered_by": "external_model",
            }
            payload["chat"] = persisted

            return payload

        except Exception as e:
            logger.exception(
                "MCP %s error for storage %s", tool_name, storage_id
            )
            return {"error": str(e)}

    @mcp.tool()
    def list_storages() -> list[dict]:
        """
        List all available Retriqs storages that can be queried.

        Use this tool before retrieval when you do not yet know which storage_id to use.

        Returns:
        - A list of storage records, each containing:
        - id: numeric storage identifier
        - name: storage or workspace name
        """
        storages = []
        for storage_id, instance in rag_manager.all_instances():
            name = getattr(instance, "workspace", f"Storage {storage_id}")
            storages.append(
                {
                    "id": storage_id,
                    "name": name,
                }
            )
        return storages

    @mcp.tool()
    async def retrieve_context(
        storage_id: int,
        query: str,
        mode: str = "mix",
        top_k: int = 10,
        chunk_top_k: int | None = None,
        max_entity_tokens: int | None = None,
        max_relation_tokens: int | None = None,
        max_total_tokens: int | None = None,
        hl_keywords: list[str] | None = None,
        ll_keywords: list[str] | None = None,
        enable_rerank: bool | None = None,
        provider: str = "External MCP Client",
        create_chat: bool = True,
        chat_id: int | None = None,
    ) -> dict[str, Any]:
        """
        Retrieve structured context from a Retriqs storage without generating a final answer.

        Purpose:
        - Use this tool when you want retrieval results from Retriqs that your own model
        can use to answer the user.
        - This tool does not produce the final answer text for the user.
        - It returns retrieval output such as entities, relationships, chunks, references,
        metadata, and formatted context text.

        Returns:
        - A structured dictionary containing:
        - status: retrieval status
        - message: retrieval status message
        - context_text: formatted retrieval context
        - data: structured retrieval payload
        - references: reference list
        - metadata: retrieval metadata
        - origin: MCP origin metadata
        - chat: persisted chat/message ids when create_chat=True

        Parameters:
        - storage_id:
        Numeric ID of the Retriqs storage to query.
        Use list_storages first if you do not know which storage to use.

        - query:
        The natural-language question or retrieval request.
        Example: "What is Retriqs and how does the MCP integration work?"

        - mode:
        Retrieval mode to use.
        Supported values:
        - "local": focuses more on entity-local context
        - "global": focuses more on broader relationship-level context
        - "hybrid": combines local and global retrieval styles
        - "naive": simpler chunk/vector-oriented retrieval
        - "mix": balanced default retrieval mode for most use cases
        - "bypass": bypass-style mode if supported by backend behavior
        Default: "mix"

        - top_k:
        Number of top graph-oriented retrieval items to keep.
        In practice this typically affects how many high-ranking entities or
        relationships are included depending on retrieval mode.
        Default: 10

        - chunk_top_k:
        Number of text chunks to keep from chunk retrieval.
        Increase this if you want more document evidence returned.
        Leave as None to use backend defaults.

        - max_entity_tokens:
        Maximum token budget allocated to entity context in retrieval.
        Useful when you want to limit how much entity information is returned.

        - max_relation_tokens:
        Maximum token budget allocated to relationship context in retrieval.
        Useful when you want to limit how much graph-relationship information is returned.

        - max_total_tokens:
        Maximum total token budget for the full retrieved context payload.
        Useful when you want the tool output to stay smaller for downstream model use.

        - hl_keywords:
        Optional high-level keywords to guide retrieval toward broader concepts.
        Example: ["RAG", "retrieval", "multi-tenancy"]
        If omitted, backend retrieval logic uses the query directly.

        - ll_keywords:
        Optional low-level keywords to guide retrieval toward more specific terms.
        Example: ["LightRAG", "FastMCP", "storage_id"]

        - enable_rerank:
        If True, enables reranking when supported by the backend configuration.
        If False, disables reranking.
        If None, backend defaults are used.

        - provider:
        Human-readable name of the external MCP client or agent making the call.
        This is stored in chat history when create_chat=True.
        Example: "Claude Desktop", "Open WebUI Agent", "Retriqs MCP Client"

        - create_chat:
        If True, persist this retrieval call into Retriqs chat history.
        This is useful when you want the retrieval event to be visible in the app UI.
        Default: True

        - chat_id:
        Optional existing chat ID to append this MCP retrieval call to.
        If omitted and create_chat=True, a new chat is created.

        Guidance:
        - Use this tool when your model wants structured retrieval results.
        - Prefer this tool over retrieve_context_json unless you explicitly need a JSON string.
        """
        return await _run_retrieve_context(
            storage_id=storage_id,
            query=query,
            mode=mode,
            top_k=top_k,
            chunk_top_k=chunk_top_k,
            max_entity_tokens=max_entity_tokens,
            max_relation_tokens=max_relation_tokens,
            max_total_tokens=max_total_tokens,
            hl_keywords=hl_keywords,
            ll_keywords=ll_keywords,
            enable_rerank=enable_rerank,
            provider=provider,
            create_chat=create_chat,
            chat_id=chat_id,
            tool_name="retrieve_context",
        )


    @mcp.tool()
    async def retrieve_context_json(
        storage_id: int,
        query: str,
        mode: str = "mix",
        top_k: int = 10,
        chunk_top_k: int | None = None,
        max_entity_tokens: int | None = None,
        max_relation_tokens: int | None = None,
        max_total_tokens: int | None = None,
        hl_keywords: list[str] | None = None,
        ll_keywords: list[str] | None = None,
        enable_rerank: bool | None = None,
        provider: str = "External MCP Client",
        create_chat: bool = True,
        chat_id: int | None = None,
    ) -> str:
        """
        Retrieve structured context from a Retriqs storage and return it as a JSON string.

        Purpose:
        - Use this tool when the calling agent specifically needs the output as a JSON string
        instead of a structured object.
        - This is useful for clients or toolchains that expect raw JSON text.
        - This tool does not generate the final answer for the user.

        Returns:
        - A JSON string containing:
        - status
        - message
        - context_text
        - data
        - references
        - metadata
        - origin
        - chat

        Parameters:
        - storage_id:
        Numeric ID of the Retriqs storage to query.

        - query:
        The natural-language question or retrieval request.

        - mode:
        Retrieval mode to use.
        Supported values:
        - "local"
        - "global"
        - "hybrid"
        - "naive"
        - "mix"
        - "bypass"
        Default: "mix"

        - top_k:
        Number of top graph-oriented retrieval items to keep.
        Default: 10

        - chunk_top_k:
        Number of text chunks to keep from chunk retrieval.

        - max_entity_tokens:
        Maximum token budget allocated to entity context.

        - max_relation_tokens:
        Maximum token budget allocated to relationship context.

        - max_total_tokens:
        Maximum total token budget for the full retrieved context payload.

        - hl_keywords:
        Optional high-level retrieval keywords.

        - ll_keywords:
        Optional low-level retrieval keywords.

        - enable_rerank:
        Whether reranking should be enabled when supported.

        - provider:
        Human-readable name of the external MCP client or agent making the call.
        Stored in chat history when create_chat=True.

        - create_chat:
        If True, persist this retrieval call into Retriqs chat history.
        Default: True

        - chat_id:
        Optional existing chat ID to append this retrieval call to.

        Guidance:
        - Prefer retrieve_context for most model-to-tool interactions.
        - Use retrieve_context_json only when a plain JSON string is explicitly needed.
        """
        payload = await _run_retrieve_context(
            storage_id=storage_id,
            query=query,
            mode=mode,
            top_k=top_k,
            chunk_top_k=chunk_top_k,
            max_entity_tokens=max_entity_tokens,
            max_relation_tokens=max_relation_tokens,
            max_total_tokens=max_total_tokens,
            hl_keywords=hl_keywords,
            ll_keywords=ll_keywords,
            enable_rerank=enable_rerank,
            provider=provider,
            create_chat=create_chat,
            chat_id=chat_id,
            tool_name="retrieve_context_json",
        )
        return json.dumps(payload, ensure_ascii=False, indent=2)

    return mcp.http_app(path="/")