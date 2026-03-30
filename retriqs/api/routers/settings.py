from fastapi import (
    APIRouter,
    HTTPException,
    Body,
    File,
    Form,
    Header,
    Request,
    UploadFile,
)
from fastapi.responses import FileResponse
from pydantic import BaseModel
from retriqs.api.database.settings_manager import (
    DEFAULT_CONFIG,
    get_db_settings,
    update_db_setting,
    get_graph_storages,
    add_and_create_storage,
    delete_storage_by_id,
    update_db_setting_for_storage_id,
)
from retriqs.api.database.models import (
    AppSetting as DBAppSettings,
    GraphStorage as DBGraphStorage,
    SessionLocal,
)
from retriqs.api.edition import (
    UPGRADE_URL,
    can_create_storage,
    get_restricted_provider_fields,
)
from retriqs.api.storage_archive import (
    StorageArchiveError,
    analyze_storage_merge,
    apply_storage_merge,
    build_archive_manifest,
    cleanup_merge_analysis,
    create_storage_archive,
    enforce_archive_upload_size,
    extract_storage_archive,
    get_merge_analysis_record,
    normalize_storage_settings,
    storage_archive_http_exception,
    validate_archive_structure,
)
from retriqs.api.auth import auth_handler

# Import the reload function from your server file
# Adjust the import path based on your folder structure
import logging
import tempfile
import zipfile
from typing import Any, Optional, List, Literal, cast
from urllib.parse import urlparse
from sqlalchemy.orm import joinedload
import os
from starlette.background import BackgroundTask
import httpx
import json
from datetime import datetime, timezone
from retriqs.utils import compute_mdhash_id

logger = logging.getLogger("lightrag")
router = APIRouter(prefix="/api/settings", tags=["Settings"])

# ... (Previous model definitions remain unchanged)


class SettingsUpdate(BaseModel):
    llm_binding: str
    llm_model: str
    llm_binding_host: str
    llm_binding_api_key: str
    ollama_num_ctx: int = 32768
    ollama_llm_num_ctx: int = 32768
    ollama_embedding_num_ctx: int = 32768
    embedding_binding: str
    embedding_model: str
    embedding_binding_host: str
    embedding_binding_api_key: Optional[str] = ""
    embedding_dim: int = 1024
    embedding_token_limit: int = 8192
    max_async: int = 1
    rerank_binding: Optional[str] = "null"

    # Storage Configuration
    lightrag_graph_storage: Optional[str] = "NetworkXStorage"
    lightrag_kv_storage: Optional[str] = "JsonKVStorage"
    lightrag_doc_status_storage: Optional[str] = "JsonDocStatusStorage"
    lightrag_vector_storage: Optional[str] = "NanoVectorDBStorage"
    neo4j_uri: Optional[str] = None
    neo4j_username: Optional[str] = None
    neo4j_password: Optional[str] = None

    milvus_uri: Optional[str] = None
    milvus_db_name: Optional[str] = "lightrag"
    milvus_user: Optional[str] = None
    milvus_password: Optional[str] = None

    redis_uri: Optional[str] = None


class GraphStorageSettingsUpdate(SettingsUpdate):
    id: int


class DTOGraphStorage(BaseModel):
    name: str
    storage_settings: SettingsUpdate


class AppSetting(BaseModel):
    key: str
    value: str


class GraphStorage(BaseModel):
    name: str
    storage_settings: List[AppSetting]


class StorageMergeApplyRequest(BaseModel):
    analysis_id: str
    conflict_mode: str


MARKETPLACE_ARCHIVE_ALLOWED_HOST = "d2nx8b3pezm5w7.cloudfront.net"
MARKETPLACE_ARCHIVE_ALLOWED_PATH_PREFIXES = ("/public/graphs/",)
VECTOR_ARCHIVE_FILES = {
    "vdb_chunks.json",
    "vdb_entities.json",
    "vdb_relationships.json",
}
VECTOR_INDEX_CACHE_FILES = {
    "bm25_chunks.pkl",
    "bm25_entities.pkl",
    "bm25_relationships.pkl",
}
NEEDS_REEMBEDDING_KEY = "NEEDS_REEMBEDDING"
EMBEDDING_SETTING_KEYS = {
    "EMBEDDING_BINDING",
    "EMBEDDING_MODEL",
    "EMBEDDING_BINDING_HOST",
    "EMBEDDING_BINDING_API_KEY",
    "EMBEDDING_DIM",
    "EMBEDDING_TOKEN_LIMIT",
    "EMBEDDING_SEND_DIM",
}
EmbeddingImportMode = Literal["preindexed", "local_reembed"]
EMBEDDING_IMPORT_MODES = {"preindexed", "local_reembed"}


def _validate_archive_source_url(source_url: str) -> str:
    parsed = urlparse(source_url)

    if parsed.scheme not in {"http", "https"}:
        raise HTTPException(
            status_code=400, detail="source_url must use http or https scheme"
        )

    if parsed.username or parsed.password:
        raise HTTPException(
            status_code=400, detail="source_url must not contain credentials"
        )

    hostname = (parsed.hostname or "").lower()
    if hostname != MARKETPLACE_ARCHIVE_ALLOWED_HOST:
        raise HTTPException(
            status_code=400,
            detail=(
                f"source_url host is not allowed. Expected {MARKETPLACE_ARCHIVE_ALLOWED_HOST}"
            ),
        )

    if parsed.port not in (None, 80, 443):
        raise HTTPException(
            status_code=400,
            detail="source_url port is not allowed. Only default HTTP/HTTPS ports are supported",
        )

    path = parsed.path or "/"
    if not any(path.startswith(prefix) for prefix in MARKETPLACE_ARCHIVE_ALLOWED_PATH_PREFIXES):
        raise HTTPException(
            status_code=400,
            detail=(
                "source_url path is not allowed. Expected one of: "
                f"{', '.join(MARKETPLACE_ARCHIVE_ALLOWED_PATH_PREFIXES)}"
            ),
        )

    return source_url


def _select_archive_source(
    file: UploadFile | None, source_url: str | None
) -> tuple[str, str | None]:
    normalized_source_url = source_url.strip() if source_url else None
    has_file = file is not None and bool(file.filename)
    has_source_url = bool(normalized_source_url)

    if has_file and has_source_url:
        raise HTTPException(
            status_code=400, detail="Provide either file or source_url, not both"
        )

    if not has_file and not has_source_url:
        raise HTTPException(
            status_code=400, detail="Either file or source_url is required"
        )

    if has_source_url:
        assert normalized_source_url is not None
        return "source_url", _validate_archive_source_url(normalized_source_url)

    return "file", None


async def _write_uploaded_archive_to_path(file: UploadFile, temp_archive_path: str) -> None:
    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="Storage import only accepts .zip archives")

    bytes_written = 0
    with open(temp_archive_path, "wb") as uploaded_archive:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            bytes_written += len(chunk)
            enforce_archive_upload_size(bytes_written)
            uploaded_archive.write(chunk)


async def _download_archive_to_path_from_source_url(
    source_url: str, temp_archive_path: str
) -> None:
    validated_source_url = _validate_archive_source_url(source_url)
    timeout = httpx.Timeout(30.0, connect=10.0, read=30.0)
    bytes_written = 0

    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=timeout) as client:
            async with client.stream("GET", validated_source_url) as response:
                response.raise_for_status()
                _validate_archive_source_url(str(response.url))

                with open(temp_archive_path, "wb") as downloaded_archive:
                    async for chunk in response.aiter_bytes(1024 * 1024):
                        if not chunk:
                            continue
                        bytes_written += len(chunk)
                        enforce_archive_upload_size(bytes_written)
                        downloaded_archive.write(chunk)
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=400,
            detail=(
                "Failed to download archive from source_url: "
                f"received status {exc.response.status_code}"
            ),
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Failed to download archive from source_url: {exc}",
        ) from exc

    if bytes_written <= 0:
        raise HTTPException(
            status_code=400, detail="Downloaded archive from source_url is empty"
        )


async def _materialize_archive_source_to_temp_file(
    file: UploadFile | None, source_url: str | None, temp_archive_path: str
) -> None:
    source_kind, validated_source_url = _select_archive_source(file, source_url)
    if source_kind == "file":
        assert file is not None
        await _write_uploaded_archive_to_path(file, temp_archive_path)
        return

    assert validated_source_url is not None
    await _download_archive_to_path_from_source_url(
        validated_source_url, temp_archive_path
    )


def _is_embedding_setting_key(key: str) -> bool:
    normalized = str(key).upper()
    return "EMBEDDING" in normalized


def _storage_settings_map(storage: DBGraphStorage) -> dict[str, str]:
    settings_map: dict[str, str] = {}
    for setting in storage.storage_settings:
        settings_map[str(setting.key).upper()] = str(setting.value or "")
    return settings_map


def _set_storage_needs_reembedding(storage_id: int, needed: bool) -> None:
    update_db_setting_for_storage_id(
        storage_id, NEEDS_REEMBEDDING_KEY, "true" if needed else "false"
    )


async def _set_reembedding_pipeline_status(
    rag_instance: Any,
    *,
    busy: bool,
    latest_message: str,
    cur_batch: int = 0,
    batchs: int = 3,
    failed: bool = False,
) -> None:
    from retriqs.kg.shared_storage import get_namespace_data, get_namespace_lock

    pipeline_status = await get_namespace_data(
        "pipeline_status", workspace=rag_instance.workspace
    )
    pipeline_status_lock = get_namespace_lock(
        "pipeline_status", workspace=rag_instance.workspace
    )
    async with pipeline_status_lock:
        if "history_messages" not in pipeline_status:
            pipeline_status["history_messages"] = []

        if busy:
            pipeline_status.update(
                {
                    "busy": True,
                    "job_name": "reembedding",
                    "job_start": datetime.now(timezone.utc),
                    "docs": 3,
                    "batchs": batchs,
                    "cur_batch": cur_batch,
                    "request_pending": False,
                    "cancellation_requested": False,
                    "current_job": "reembedding",
                    "reembedding_busy": True,
                    "reembedding_failed": False,
                }
            )
            try:
                pipeline_status["history_messages"][:] = []
            except Exception:
                pipeline_status["history_messages"].clear()
        else:
            pipeline_status.update(
                {
                    "busy": False,
                    "request_pending": False,
                    "cancellation_requested": False,
                    "current_job": None,
                    "reembedding_busy": False,
                    "reembedding_failed": failed,
                    "cur_batch": cur_batch,
                    "batchs": batchs,
                }
            )

        pipeline_status["latest_message"] = latest_message
        pipeline_status["history_messages"].append(latest_message)


async def _reset_storage_vector_indexes_for_embedding_change(
    app: Any, storage: DBGraphStorage
) -> None:
    """
    Clear vector-only artifacts so a storage can reload under a new embedding dimension.
    Keeps extracted chunks/graph/docs intact and marks re-embed as required.
    """
    rag_manager = app.state.rag_manager
    rag_instance = rag_manager.get_instance(storage.id)

    if rag_instance:
        vector_stores = [
            ("chunks_vdb", getattr(rag_instance, "chunks_vdb", None)),
            ("entities_vdb", getattr(rag_instance, "entities_vdb", None)),
            ("relationships_vdb", getattr(rag_instance, "relationships_vdb", None)),
        ]

        for store_name, store in vector_stores:
            if store and hasattr(store, "drop"):
                try:
                    logger.info(
                        "Resetting vector store %s for storage %s due to embedding setting change",
                        store_name,
                        storage.id,
                    )
                    await store.drop()
                except Exception as exc:
                    logger.warning(
                        "Failed to drop vector store %s for storage %s: %s",
                        store_name,
                        storage.id,
                        exc,
                    )

    candidate_files = set(VECTOR_ARCHIVE_FILES) | set(VECTOR_INDEX_CACHE_FILES)
    for filename in candidate_files:
        file_path = os.path.join(storage.work_dir, filename)
        if os.path.isfile(file_path):
            try:
                os.unlink(file_path)
            except Exception as exc:
                logger.warning(
                    "Failed to remove vector artifact %s for storage %s: %s",
                    file_path,
                    storage.id,
                    exc,
                )


def _resolve_import_storage_settings(
    archive_settings: dict[str, str],
    embedding_import_mode: EmbeddingImportMode,
) -> dict[str, str]:
    merged_settings = dict(normalize_storage_settings(archive_settings))
    if embedding_import_mode == "preindexed":
        return merged_settings

    local_settings = normalize_storage_settings(get_db_settings())
    default_settings = normalize_storage_settings(DEFAULT_CONFIG)
    resolved_embedding_settings = {
        key: value
        for key, value in default_settings.items()
        if _is_embedding_setting_key(key)
    }
    resolved_embedding_settings.update(
        {
            key: value
            for key, value in local_settings.items()
            if _is_embedding_setting_key(key)
        }
    )

    for key, value in resolved_embedding_settings.items():
        if _is_embedding_setting_key(key):
            merged_settings[key] = value

    return merged_settings


async def _rebuild_embeddings_from_existing_storage_data(
    rag_instance: Any, storage_dir: str
) -> dict[str, int]:
    text_chunks_path = os.path.join(storage_dir, "kv_store_text_chunks.json")
    if not os.path.isfile(text_chunks_path):
        raise StorageArchiveError(
            "kv_store_text_chunks.json not found. This operation requires a file-based storage archive."
        )

    with open(text_chunks_path, "r", encoding="utf-8") as handle:
        text_chunks_payload = json.load(handle) or {}
    if not isinstance(text_chunks_payload, dict):
        raise StorageArchiveError(
            "kv_store_text_chunks.json has invalid format. Expected a JSON object."
        )

    await rag_instance.chunks_vdb.drop()
    await rag_instance.entities_vdb.drop()
    await rag_instance.relationships_vdb.drop()

    if text_chunks_payload:
        await rag_instance.chunks_vdb.upsert(text_chunks_payload)

    graph_nodes = await rag_instance.chunk_entity_relation_graph.get_all_nodes()
    graph_edges = await rag_instance.chunk_entity_relation_graph.get_all_edges()

    entities_payload: dict[str, dict[str, Any]] = {}
    for node in graph_nodes:
        entity_name = node.get("entity_name") or node.get("entity_id") or node.get("id")
        if not entity_name:
            continue

        entity_name = str(entity_name)
        if entity_name.startswith("chunk-"):
            continue

        source_id = str(node.get("source_id") or "")
        description = str(node.get("description") or "")
        entity_type = str(node.get("entity_type") or "UNKNOWN")
        entity_id = compute_mdhash_id(entity_name, prefix="ent-")

        entities_payload[entity_id] = {
            "content": f"{entity_name}\n{description}",
            "entity_name": entity_name,
            "source_id": source_id,
            "description": description,
            "entity_type": entity_type,
            "file_path": str(node.get("file_path") or "reembed"),
        }

    if entities_payload:
        await rag_instance.entities_vdb.upsert(entities_payload)

    relationships_payload: dict[str, dict[str, Any]] = {}
    for edge in graph_edges:
        src = edge.get("source") or edge.get("src_id") or edge.get("src")
        tgt = edge.get("target") or edge.get("tgt_id") or edge.get("tgt")
        if not src or not tgt:
            continue

        src = str(src)
        tgt = str(tgt)
        if src.startswith("chunk-") or tgt.startswith("chunk-"):
            continue

        description = str(edge.get("description") or "")
        keywords = str(edge.get("keywords") or "")
        if not description and not keywords:
            continue

        rel_id = compute_mdhash_id(src + tgt, prefix="rel-")
        relationships_payload[rel_id] = {
            "src_id": src,
            "tgt_id": tgt,
            "source_id": str(edge.get("source_id") or ""),
            "content": f"{keywords}\t{src}\n{tgt}\n{description}",
            "keywords": keywords,
            "description": description,
            "weight": edge.get("weight", 1.0),
            "file_path": str(edge.get("file_path") or "reembed"),
        }

    if relationships_payload:
        await rag_instance.relationships_vdb.upsert(relationships_payload)

    await rag_instance.chunks_vdb.index_done_callback()
    await rag_instance.entities_vdb.index_done_callback()
    await rag_instance.relationships_vdb.index_done_callback()

    return {
        "chunks": len(text_chunks_payload),
        "entities": len(entities_payload),
        "relationships": len(relationships_payload),
    }


def get_storage_or_404(storage_id: int) -> DBGraphStorage:
    db = SessionLocal()
    try:
        storage = (
            db.query(DBGraphStorage)
            .options(joinedload(DBGraphStorage.storage_settings))
            .filter(DBGraphStorage.id == storage_id)
            .first()
        )
        if not storage:
            raise HTTPException(status_code=404, detail="Storage not found")
        db.expunge(storage)
        return storage
    finally:
        db.close()


def build_db_settings_from_dict(settings_payload: dict[str, str]) -> list[DBAppSettings]:
    normalized_settings = normalize_storage_settings(settings_payload)
    return [
        DBAppSettings(key=key.upper(), value=str(value))
        for key, value in normalized_settings.items()
    ]


def normalize_optional_provider_settings(settings_payload: dict[str, Any]) -> dict[str, Any]:
    normalized_payload = dict(settings_payload)

    rerank_binding = normalized_payload.get("rerank_binding")
    if rerank_binding is None or str(rerank_binding).strip() == "":
        normalized_payload["rerank_binding"] = "null"

    return normalized_payload


async def require_archive_access(
    request: Request,
    authorization: Optional[str] = Header(default=None),
    x_api_key: Optional[str] = Header(default=None),
) -> None:
    auth_accounts = getattr(request.app.state.args, "auth_accounts", "")
    configured_api_key = getattr(request.app.state.args, "key", None)
    auth_configured = bool(auth_accounts)
    api_key_configured = bool(configured_api_key)

    if not auth_configured and not api_key_configured:
        return

    if configured_api_key and x_api_key == configured_api_key:
        return

    if authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ", 1)[1].strip()
        token_info = auth_handler.validate_token(token)
        if not auth_configured:
            return
        if token_info.get("role") != "guest":
            return
        raise HTTPException(status_code=403, detail="Guest access cannot export or import storage archives")

    if configured_api_key and not x_api_key:
        raise HTTPException(status_code=403, detail="API Key required")

    raise HTTPException(status_code=401, detail="Authentication required")


async def initialize_storage_instance(request_obj: Request, added_storage: DBGraphStorage):
    from retriqs.api.retriqs_server import build_rag_instance
    from retriqs.api.config import build_storage_args
    from retriqs.kg.shared_storage import (
        clear_workspace_namespaces,
        initialize_share_data,
    )

    # First-storage startup path: shared storage may not be initialized yet.
    # Ensure it exists before attempting workspace namespace cleanup.
    initialize_share_data(1)

    instance_args = build_storage_args(added_storage, request_obj.app.state.args)
    await clear_workspace_namespaces(instance_args.workspace)

    logger.info(f"Building LightRAG instance for storage {added_storage.id}")
    new_instance = build_rag_instance(instance_args)

    logger.info(f"Initializing storages for storage {added_storage.id}")
    await new_instance.initialize_storages()

    rag_manager = request_obj.app.state.rag_manager
    rag_manager.set_instance(added_storage.id, new_instance)


async def ensure_storage_pipeline_idle(request: Request, storage_id: int) -> None:
    rag_manager = request.app.state.rag_manager
    rag_instance = rag_manager.get_instance(storage_id)
    if not rag_instance:
        return

    from retriqs.kg.shared_storage import get_namespace_data
    from retriqs.exceptions import PipelineNotInitializedError

    try:
        pipeline_status = await get_namespace_data(
            "pipeline_status", workspace=rag_instance.workspace
        )
        if pipeline_status.get("busy", False):
            raise HTTPException(
                status_code=409,
                detail="Storage pipeline is busy. Wait for ingestion to finish before importing into existing storage.",
            )
    except PipelineNotInitializedError:
        # If pipeline not initialized, assume it's idle
        return


def validate_storage_creation_allowed(
    existing_storage_count: int, settings_payload: dict[str, str]
) -> None:
    #TODO remove or enforce 
    # if not can_create_storage(existing_storage_count):
    #     raise HTTPException(
    #         status_code=403,
    #         detail=(
    #             f"Free edition allows only one storage in production. "
    #             f"Upgrade at {UPGRADE_URL}"
    #         ),
    #     )

    restricted_fields = get_restricted_provider_fields(settings_payload)
    if restricted_fields:
        raise HTTPException(
            status_code=403,
            detail=(
                f"Selected storage providers are not available in free edition: "
                f"{', '.join(restricted_fields)}. Upgrade at {UPGRADE_URL}"
            ),
        )


async def perform_hot_reload(app):
    """Safely hand over storage by stopping the old instance BEFORE starting the new one."""
    try:
        # 1. Force the config to refresh from SQLite first
        from retriqs.api.config import initialize_config

        new_args = initialize_config(force=True)

        # 2. Lazy Import to avoid circular dependency
        from retriqs.api.retriqs_server import build_rag_instance

        # 3. SHUT DOWN THE OLD INSTANCE NOW
        # This releases file locks on .json and .graphml files
        if hasattr(app.state, "rag_proxy"):
            old_rag = app.state.rag_proxy._instance
            logger.info("Closing existing storage handles for hot-swap...")
            try:
                # We use finalize_storages to save any pending data and close files
                await old_rag.finalize_storages()
            except Exception as e:
                logger.warning(f"Non-critical error closing old storage: {e}")

        # 4. BUILD AND INITIALIZE THE NEW INSTANCE
        # Now that the files are free, the new instance can grab them
        logger.info("Building new RAG instance with updated settings...")
        new_rag_instance = build_rag_instance(new_args)

        logger.info("Initializing new storage connections...")
        await new_rag_instance.initialize_storages()

        # 5. SWAP THE PROXY
        app.state.rag_proxy.set_instance(new_rag_instance)
        logger.info("Hot-reload successful. System is now using new configuration.")

    except Exception as e:
        import traceback

        logger.error(f"CRITICAL ERROR DURING RELOAD: {e}")
        traceback.print_exc()  # This will show the exact line of the crash in your terminal
        raise HTTPException(status_code=500, detail=f"Reload failed: {str(e)}")


async def reload_tenant_instance(app, storage_id: int):
    """Reloads a specific tenant instance in the RAGManager."""
    logger.info(f"Reloading tenant instance for storage ID: {storage_id}")

    db = SessionLocal()
    try:
        # Fetch storage with settings eagerly loaded
        storage = (
            db.query(DBGraphStorage)
            .options(joinedload(DBGraphStorage.storage_settings))
            .filter(DBGraphStorage.id == storage_id)
            .first()
        )
        if not storage:
            raise ValueError(f"Storage with ID {storage_id} not found")

        # Use centralized helper to build storage-specific args
        from retriqs.api.config import build_storage_args
        from retriqs.kg.shared_storage import clear_workspace_namespaces

        instance_args = build_storage_args(storage, app.state.args)
        rag_manager = app.state.rag_manager
        old_instance = rag_manager.get_instance(storage.id)

        if old_instance:
            logger.info(f"Finalizing old instance for storage {storage.id}")
            try:
                await old_instance.finalize_storages()
            except Exception as e:
                logger.warning(f"Error finalizing old instance: {e}")

        await clear_workspace_namespaces(instance_args.workspace)

        # Build and initialize new instance
        from retriqs.api.retriqs_server import build_rag_instance

        logger.info(f"Building LightRAG instance for storage {storage.id}")
        new_instance = build_rag_instance(instance_args)

        logger.info(f"Initializing storages for storage {storage.id}")
        await new_instance.initialize_storages()

        rag_manager.set_instance(storage.id, new_instance)
        logger.info(f"Successfully reloaded instance for storage {storage.id}")

    except Exception as e:
        logger.error(f"Failed to reload tenant instance {storage_id}: {e}")
        raise e
    finally:
        db.close()


@router.get("")
async def fetch_settings():
    """Returns the current configuration from SQLite"""
    return get_db_settings()


@router.get("/graph_storages")
async def fetch_graph_storages():
    """Returns all current storages from SQLite"""
    logger.info("Fetching Graph data")
    return get_graph_storages()


@router.post("")
async def update_settings_for_storage(
    request: Request, data: GraphStorageSettingsUpdate
):
    """Updates multiple SQLite database settings and reloads the RAG engine."""

    failed_keys = []

    if not data.id:
        return {"status": "failed", "message": "Message didn't include storage id"}

    storage = get_storage_or_404(data.id)
    previous_settings = _storage_settings_map(storage)
    normalized_payload = normalize_optional_provider_settings(data.model_dump())
    embedding_setting_changed = False

    for k, v in normalized_payload.items():
        if not update_db_setting_for_storage_id(data.id, k.upper(), v):
            failed_keys.append(k)
            continue
        key_upper = k.upper()
        if key_upper in EMBEDDING_SETTING_KEYS:
            old_value = str(previous_settings.get(key_upper, ""))
            new_value = "" if v is None else str(v)
            if old_value != new_value:
                embedding_setting_changed = True

    if embedding_setting_changed:
        _set_storage_needs_reembedding(data.id, True)

    if failed_keys:
        return {
            "status": "partial_success",
            "message": f"Updated some settings, but failed to find: {', '.join(failed_keys)}",
        }

    # --- NEW: TRIGGER THE TENANT RELOAD ---
    try:
        if embedding_setting_changed:
            await _reset_storage_vector_indexes_for_embedding_change(
                request.app, storage
            )

        logger.info(f"Performing reload for storage {data.id}")
        await reload_tenant_instance(request.app, data.id)

        # If this happens to be the 'active' global instance (if using rag_proxy),
        # we might need to update proxy too?
        # Assuming rag_proxy is mostly for single-tenant or default view.
        # But if we want consistent behavior:
        # if request.app.state.current_active_storage_id == data.id: ...
        # For now, updating rag_manager is the critical part for multi-tenancy.

    except Exception as e:
        # We catch this so the user knows settings saved, even if the restart failed
        logger.info("Error hit")
        raise HTTPException(
            status_code=500,
            detail=f"Settings saved to DB, but failed to reload RAG instance: {str(e)}",
        )

    return {
        "status": "success",
        "message": f"All settings saved and RAG instance for storage {data.id} reloaded.",
    }


@router.put("/{key}")
async def update_single_setting(
    request: Request, key: str, value: str = Body(..., embed=True)
):
    """Updates a specific setting key and reloads configuration."""
    key_upper = key.upper()
    success = update_db_setting(key_upper, value)

    if success:
        # Trigger reload even for single setting updates
        await perform_hot_reload(request.app)
        return {
            "status": "success",
            "message": f"Updated {key_upper} and reloaded RAG.",
        }
    else:
        raise HTTPException(status_code=404, detail=f"Setting '{key_upper}' not found.")


"""
example input:
{
  "name": "test",
  "storage_settings": {
    "llm_binding": "ollama",
    "llm_model": "qwen3:0.6b",
    "llm_binding_host": "http://localhost:11434",
    "llm_binding_api_key": "",
    "ollama_num_ctx": 32768,
    "embedding_binding": "ollama",
    "embedding_model": "bge-m3:latest",
    "embedding_binding_host": "http://localhost:11434",
    "embedding_dim": 1024,
    "embedding_token_limit": 8192,
    "rerank_binding": "null"
  
"""


@router.post("/new_storage")
async def create_new_graph_storage(request_obj: Request, data: DTOGraphStorage):
    """Creates a new storage instance with its own LightRAG configuration."""

    settings_payload = normalize_optional_provider_settings(
        data.storage_settings.model_dump()
    )
    existing_storages = get_graph_storages()
    validate_storage_creation_allowed(len(existing_storages), settings_payload)

    db_settings = build_db_settings_from_dict(settings_payload)
    new_db_storage = DBGraphStorage(name=data.name, storage_settings=db_settings)

    try:
        added_storage = add_and_create_storage(new_db_storage)
        logger.info(
            f"Created storage with ID {added_storage.id} at {added_storage.work_dir}"
        )

        _set_storage_needs_reembedding(added_storage.id, False)
        await initialize_storage_instance(request_obj, added_storage)
        logger.info(f"Successfully created and initialized storage {added_storage.id}")

        return {
            "status": "success",
            "message": f"Storage '{data.name}' created and initialized",
            "storage": {
                "id": added_storage.id,
                "name": added_storage.name,
                "work_dir": added_storage.work_dir,
            },
        }
    except Exception as e:
        logger.error(f"Error creating storage: {e}")
        import traceback

        traceback.print_exc()
        raise HTTPException(
            status_code=500, detail=f"Failed to create storage: {str(e)}"
        )


@router.get("/storage/{storage_id}/export")
async def export_storage_archive(
    request: Request,
    storage_id: int,
    authorization: Optional[str] = Header(default=None),
    x_api_key: Optional[str] = Header(default=None),
):
    await require_archive_access(request, authorization, x_api_key)

    storage = get_storage_or_404(storage_id)
    archive_path: str | None = None
    had_live_instance = False
    rag_manager = request.app.state.rag_manager
    old_instance = rag_manager.get_instance(storage_id)

    try:
        if old_instance:
            had_live_instance = True
            logger.info(f"Finalizing storage {storage_id} before export")
            await old_instance.finalize_storages()

        manifest = build_archive_manifest(storage, storage.storage_settings, storage.work_dir)
        archive_path = create_storage_archive(storage.work_dir, manifest)

        filename = f"{storage.name or f'storage_{storage_id}'}-storage-export.zip"
        return FileResponse(
            archive_path,
            media_type="application/zip",
            filename=filename,
            background=BackgroundTask(lambda path: os.path.exists(path) and os.unlink(path), archive_path),
        )
    except Exception as exc:
        if archive_path and os.path.exists(archive_path):
            os.unlink(archive_path)
        raise storage_archive_http_exception(exc)
    finally:
        if had_live_instance:
            await reload_tenant_instance(request.app, storage_id)


@router.post("/storage/import")
async def import_storage_archive(
    request: Request,
    name: str = Form(...),
    file: UploadFile | None = File(default=None),
    source_url: str | None = Form(default=None),
    embedding_import_mode: str = Form(default="preindexed"),
    authorization: Optional[str] = Header(default=None),
    x_api_key: Optional[str] = Header(default=None),
):
    await require_archive_access(request, authorization, x_api_key)

    temp_archive = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
    temp_archive_path = temp_archive.name
    temp_archive.close()
    added_storage_id: int | None = None

    try:
        if embedding_import_mode not in EMBEDDING_IMPORT_MODES:
            raise HTTPException(
                status_code=400,
                detail=(
                    "embedding_import_mode must be one of: "
                    f"{', '.join(sorted(EMBEDDING_IMPORT_MODES))}"
                ),
            )

        await _materialize_archive_source_to_temp_file(file, source_url, temp_archive_path)

        with zipfile.ZipFile(temp_archive_path, "r") as archive:
            manifest = validate_archive_structure(archive)

        selected_embedding_import_mode = cast(
            EmbeddingImportMode, embedding_import_mode
        )
        imported_storage_settings = _resolve_import_storage_settings(
            manifest.storage_settings,
            selected_embedding_import_mode,
        )

        validate_storage_creation_allowed(len(get_graph_storages()), imported_storage_settings)

        new_db_storage = DBGraphStorage(
            name=name,
            storage_settings=build_db_settings_from_dict(imported_storage_settings),
        )
        added_storage = add_and_create_storage(new_db_storage)
        added_storage_id = added_storage.id

        archive_excludes = (
            VECTOR_ARCHIVE_FILES if selected_embedding_import_mode == "local_reembed" else None
        )
        extract_storage_archive(
            temp_archive_path,
            added_storage.work_dir,
            exclude_files=archive_excludes,
        )
        _set_storage_needs_reembedding(
            added_storage.id, selected_embedding_import_mode == "local_reembed"
        )
        await initialize_storage_instance(request, added_storage)

        logger.info(f"Successfully imported storage archive into storage {added_storage.id}")
        return {
            "status": "success",
            "message": f"Storage '{name}' imported and initialized",
            "embedding_import_mode": selected_embedding_import_mode,
            "storage": {
                "id": added_storage.id,
                "name": added_storage.name,
                "work_dir": added_storage.work_dir,
            },
        }
    except Exception as exc:
        if added_storage_id is not None:
            request.app.state.rag_manager.remove_instance(added_storage_id)
            try:
                delete_storage_by_id(added_storage_id)
            except Exception as cleanup_exc:
                logger.warning(f"Failed to clean up imported storage {added_storage_id}: {cleanup_exc}")
        raise storage_archive_http_exception(exc)
    finally:
        if file is not None:
            await file.close()
        if os.path.exists(temp_archive_path):
            os.unlink(temp_archive_path)


@router.post("/storage/{storage_id}/import/analyze")
async def analyze_storage_archive_merge(
    request: Request,
    storage_id: int,
    file: UploadFile | None = File(default=None),
    source_url: str | None = Form(default=None),
    authorization: Optional[str] = Header(default=None),
    x_api_key: Optional[str] = Header(default=None),
):
    await require_archive_access(request, authorization, x_api_key)

    storage = get_storage_or_404(storage_id)
    await ensure_storage_pipeline_idle(request, storage_id)

    temp_archive = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
    temp_archive_path = temp_archive.name
    temp_archive.close()

    try:
        await _materialize_archive_source_to_temp_file(file, source_url, temp_archive_path)

        return analyze_storage_merge(
            storage_id=storage_id,
            storage_dir=storage.work_dir,
            target_settings=storage.storage_settings,
            archive_path=temp_archive_path,
        )
    except Exception as exc:
        raise storage_archive_http_exception(exc)
    finally:
        if file is not None:
            await file.close()
        if os.path.exists(temp_archive_path):
            os.unlink(temp_archive_path)


@router.post("/storage/{storage_id}/import/apply")
async def apply_storage_archive_merge(
    request: Request,
    storage_id: int,
    data: StorageMergeApplyRequest,
    authorization: Optional[str] = Header(default=None),
    x_api_key: Optional[str] = Header(default=None),
):
    await require_archive_access(request, authorization, x_api_key)

    storage = get_storage_or_404(storage_id)
    await ensure_storage_pipeline_idle(request, storage_id)

    analysis_record = get_merge_analysis_record(data.analysis_id)
    if analysis_record.storage_id != storage_id:
        raise HTTPException(status_code=400, detail="Merge analysis does not belong to this storage")

    rag_manager = request.app.state.rag_manager
    old_instance = rag_manager.get_instance(storage_id)

    try:
        if old_instance:
            logger.info(f"Finalizing storage {storage_id} before merge apply")
            await old_instance.finalize_storages()

        result = apply_storage_merge(
            storage_dir=storage.work_dir,
            analysis_id=data.analysis_id,
            conflict_mode=data.conflict_mode,
        )
        await reload_tenant_instance(request.app, storage_id)
        return result
    except Exception as exc:
        cleanup_merge_analysis(data.analysis_id)
        raise storage_archive_http_exception(exc)


@router.post("/storage/{storage_id}/reembed")
async def rebuild_storage_embeddings(
    request: Request,
    storage_id: int,
    authorization: Optional[str] = Header(default=None),
    x_api_key: Optional[str] = Header(default=None),
):
    await require_archive_access(request, authorization, x_api_key)

    storage = get_storage_or_404(storage_id)
    await ensure_storage_pipeline_idle(request, storage_id)

    rag_manager = request.app.state.rag_manager
    rag_instance = rag_manager.get_instance(storage_id)
    if rag_instance is None:
        await reload_tenant_instance(request.app, storage_id)
        rag_instance = rag_manager.get_instance(storage_id)
    if rag_instance is None:
        raise HTTPException(status_code=500, detail="Failed to load storage instance")

    await _set_reembedding_pipeline_status(
        rag_instance,
        busy=True,
        cur_batch=0,
        latest_message="Re-embedding job started",
    )

    try:
        await _set_reembedding_pipeline_status(
            rag_instance,
            busy=True,
            cur_batch=1,
            latest_message="Rebuilding chunk embeddings from existing chunk store",
        )
        counts = await _rebuild_embeddings_from_existing_storage_data(
            rag_instance, storage.work_dir
        )
        await _set_reembedding_pipeline_status(
            rag_instance,
            busy=False,
            cur_batch=3,
            latest_message=(
                "Re-embedding completed. "
                f"Chunks: {counts['chunks']}, Entities: {counts['entities']}, "
                f"Relationships: {counts['relationships']}"
            ),
        )
        _set_storage_needs_reembedding(storage_id, False)
    except Exception as exc:
        await _set_reembedding_pipeline_status(
            rag_instance,
            busy=False,
            failed=True,
            cur_batch=3,
            latest_message=f"Re-embedding failed: {exc}",
        )
        raise

    return {
        "status": "reembedding_completed",
        "message": "Rebuilt embeddings from existing chunk/entity/relation data",
        "storage_id": storage_id,
        "counts": counts,
    }


@router.delete("/storage/{storage_id}")
async def remove_storage(request: Request, storage_id: int):
    """
    Delete a storage instance and clean up all associated resources.

    This endpoint performs a complete cleanup:
    1. Clears ALL data from storage backends (Neo4j, Milvus, Redis, JSON files, etc.)
    2. Finalizes the RAG instance to close storage connections
    3. Removes the instance from the in-memory RAGManager cache
    4. Deletes the physical storage directory
    5. Removes the database record

    CRITICAL: External storage backends (Neo4j, Milvus, Redis) store data with
    workspace-based keys/collections. Simply deleting the local directory does NOT
    remove data from these external systems. We must explicitly drop/clear the data
    before finalizing connections, otherwise the data persists and appears when
    tenant IDs are reused.

    :param request: FastAPI request object to access app state
    :param storage_id: ID of the storage to delete
    :type storage_id: int
    """
    logger.info(f"Starting deletion process for storage {storage_id}")

    # Step 1: Clear data from ALL storage backends and finalize
    # This is CRITICAL to prevent data leakage when IDs are reused
    rag_manager = request.app.state.rag_manager
    old_instance = rag_manager.get_instance(storage_id)

    if old_instance:
        logger.info(f"Clearing all storage backend data for storage {storage_id}")
        try:
            # Check if storage is initialized
            if hasattr(old_instance, "_storages_status"):
                from retriqs.base import StoragesStatus

                if old_instance._storages_status == StoragesStatus.INITIALIZED:
                    logger.info(
                        f"Dropping data from all storage backends for storage {storage_id}"
                    )

                    # Clear data from ALL storage backends
                    # This includes: Neo4j graphs, Milvus collections, Redis keys, JSON files, etc.
                    storages_to_clear = [
                        ("full_docs", old_instance.full_docs),
                        ("text_chunks", old_instance.text_chunks),
                        ("full_entities", old_instance.full_entities),
                        ("full_relations", old_instance.full_relations),
                        ("entity_chunks", old_instance.entity_chunks),
                        ("relation_chunks", old_instance.relation_chunks),
                        ("entities_vdb", old_instance.entities_vdb),
                        ("relationships_vdb", old_instance.relationships_vdb),
                        ("chunks_vdb", old_instance.chunks_vdb),
                        (
                            "chunk_entity_relation_graph",
                            old_instance.chunk_entity_relation_graph,
                        ),
                        ("llm_response_cache", old_instance.llm_response_cache),
                        ("doc_status", old_instance.doc_status),
                    ]

                    # Drop/clear each storage backend
                    for storage_name, storage in storages_to_clear:
                        if storage and hasattr(storage, "drop"):
                            try:
                                logger.info(
                                    f"Dropping {storage_name} for storage {storage_id}"
                                )
                                await storage.drop()
                            except Exception as e:
                                logger.warning(f"Error dropping {storage_name}: {e}")

                    # Now finalize to close connections
                    logger.info(
                        f"Closing storage backend connections for storage {storage_id}"
                    )
                    await old_instance.finalize_storages()
                    logger.info(
                        f"Successfully cleared and finalized storage {storage_id}"
                    )
                else:
                    logger.info(
                        f"Storage {storage_id} not initialized, skipping data clearing"
                    )
            else:
                logger.warning(
                    f"Storage {storage_id} has no status attribute, attempting cleanup anyway"
                )
                # Try to finalize anyway
                await old_instance.finalize_storages()
        except Exception as e:
            # Log but don't fail - we still want to clean up even if finalization has issues
            logger.warning(f"Error during storage cleanup for {storage_id}: {e}")

        # Remove from in-memory cache
        rag_manager.remove_instance(storage_id)
        logger.info(f"Removed storage {storage_id} from RAGManager cache")
        try:
            from retriqs.kg.shared_storage import clear_workspace_namespaces

            await clear_workspace_namespaces(old_instance.workspace)
        except Exception as e:
            logger.warning(
                f"Failed to clear shared namespace state for storage {storage_id}: {e}"
            )
    else:
        logger.info(
            f"No active RAG instance found for storage {storage_id} (already cleaned up or never initialized)"
        )

    # Step 2: Delete the physical directory and database record
    success = delete_storage_by_id(storage_id)

    if not success:
        raise HTTPException(status_code=404, detail="Storage not found")

    logger.info(
        f"Successfully deleted storage {storage_id} and all associated resources"
    )
    return {"message": f"Storage {storage_id} and its files have been removed"}
