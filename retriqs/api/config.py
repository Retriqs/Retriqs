"""
Configs for the LightRAG API.
"""

import os
import argparse
import logging
from typing import Any, Type, Union, Optional
from dotenv import load_dotenv
from retriqs.utils import get_env_value
from retriqs.llm.binding_options import (
    GeminiEmbeddingOptions,
    GeminiLLMOptions,
    OllamaEmbeddingOptions,
    OllamaLLMOptions,
    OpenAILLMOptions,
)
from retriqs.base import OllamaServerInfos
import sys
from retriqs.api.storage_paths import default_rag_root

from retriqs.constants import (
    DEFAULT_WOKERS,
    DEFAULT_TIMEOUT,
    DEFAULT_MAX_GRAPH_NODES,
    DEFAULT_TOP_K,
    DEFAULT_CHUNK_TOP_K,
    DEFAULT_HISTORY_TURNS,
    DEFAULT_MAX_ENTITY_TOKENS,
    DEFAULT_MAX_RELATION_TOKENS,
    DEFAULT_MAX_TOTAL_TOKENS,
    DEFAULT_COSINE_THRESHOLD,
    DEFAULT_RELATED_CHUNK_NUMBER,
    DEFAULT_MIN_RERANK_SCORE,
    DEFAULT_FORCE_LLM_SUMMARY_ON_MERGE,
    DEFAULT_MAX_ASYNC,
    DEFAULT_SUMMARY_MAX_TOKENS,
    DEFAULT_SUMMARY_LENGTH_RECOMMENDED,
    DEFAULT_SUMMARY_CONTEXT_SIZE,
    DEFAULT_SUMMARY_LANGUAGE,
    DEFAULT_EMBEDDING_FUNC_MAX_ASYNC,
    DEFAULT_EMBEDDING_BATCH_NUM,
    DEFAULT_OLLAMA_MODEL_NAME,
    DEFAULT_OLLAMA_MODEL_TAG,
    DEFAULT_RERANK_BINDING,
    DEFAULT_ENTITY_TYPES,
)

ollama_server_infos = OllamaServerInfos()
logger = logging.getLogger("lightrag")


class DefaultRAGStorageConfig:
    KV_STORAGE = "JsonKVStorage"
    VECTOR_STORAGE = "GrafeoVectorStorage"
    GRAPH_STORAGE = "GrafeoGraphStorage"
    DOC_STATUS_STORAGE = "JsonDocStatusStorage"


def get_default_host(binding_type: str) -> str:
    default_hosts = {
        "ollama": os.getenv("LLM_BINDING_HOST", "http://localhost:11434"),
        "lollms": os.getenv("LLM_BINDING_HOST", "http://localhost:9600"),
        "openai_codex": os.getenv(
            "LLM_BINDING_HOST", "https://chatgpt.com/backend-api/codex"
        ),
        "codex_cli": os.getenv("LLM_BINDING_HOST", "codex"),
        "azure_openai": os.getenv("AZURE_OPENAI_ENDPOINT", "https://api.openai.com/v1"),
        "openai": os.getenv("LLM_BINDING_HOST", "https://api.openai.com/v1"),
        "gemini": os.getenv(
            "LLM_BINDING_HOST", "https://generativelanguage.googleapis.com"
        ),
    }
    return default_hosts.get(
        binding_type, os.getenv("LLM_BINDING_HOST", "http://localhost:11434")
    )  # fallback to ollama if unknown


def get_db_or_env(
    key: str, default: Any, value_type: Type = str, special_none: bool = False
) -> Any:
    """
    Strict priority: SQLite -> Environment -> Default.
    Only uses default if the key is completely absent from the first two.
    """
    try:
        from retriqs.api.database.settings_manager import get_db_settings

        db_settings = get_db_settings()
    except Exception as e:
        logger.warning(f"Settings DB not available, falling back: {e}")
        db_settings = {}

    # --- PRIORITY 1: DATABASE (Exact Match) ---
    if key in db_settings:
        val = db_settings[key]

        # If DB says "None", handle it based on special_none
        if special_none and (val is None or str(val).lower() == "none"):
            return None

        # If it's a string from DB, we MUST convert it to the requested type
        try:
            if value_type == bool:
                return str(val).lower() in ("true", "1", "yes", "on")
            if value_type == int:
                return int(val)
            if value_type == float:
                return float(val)
            return str(val)
        except (ValueError, TypeError):
            # If the DB has garbage data that can't be converted,
            # we log it but don't crash.
            logger.error(f"DB key {key} had invalid value '{val}'. Falling back.")

    # --- PRIORITY 2: ENVIRONMENT ---
    # We only reach here if 'key' was NOT in db_settings
    env_val = os.getenv(key)
    if env_val is not None:
        # Use your utility or handle type conversion manually
        from retriqs.utils import get_env_value

        return get_env_value(key, default, value_type, special_none)

    # --- PRIORITY 3: DEFAULT ---
    return default


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """
    Parse command line arguments with environment variable fallback

    Args:
        is_uvicorn_mode: Whether running under uvicorn mode

    Returns:
        argparse.Namespace: Parsed arguments
    """

    parser = argparse.ArgumentParser(description="LightRAG API Server")
    default_working_dir = default_rag_root()

    # Server configuration
    parser.add_argument(
        "--host",
        default=get_db_or_env("HOST", "0.0.0.0"),
        help="Server host (default: from env or 0.0.0.0)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=get_db_or_env("PORT", 9621, int),
        help="Server port (default: from env or 9621)",
    )

    # Directory configuration
    parser.add_argument(
        "--working-dir",
        default=get_db_or_env("WORKING_DIR", default_working_dir),
        help="Working directory for RAG storage (default: from env/db or platform-aware default)",
    )
    parser.add_argument(
        "--input-dir",
        default=get_db_or_env("INPUT_DIR", "./inputs"),
        help="Directory containing input documents (default: from env or ./inputs)",
    )

    parser.add_argument(
        "--timeout",
        default=get_db_or_env("TIMEOUT", DEFAULT_TIMEOUT, int, special_none=True),
        type=int,
        help="Timeout in seconds (useful when using slow AI). Use None for infinite timeout",
    )

    # RAG configuration
    parser.add_argument(
        "--max-async",
        type=int,
        default=get_db_or_env("MAX_ASYNC", DEFAULT_MAX_ASYNC, int),
        help=f"Maximum async operations (default: from env or {DEFAULT_MAX_ASYNC})",
    )
    parser.add_argument(
        "--summary-max-tokens",
        type=int,
        default=get_db_or_env("SUMMARY_MAX_TOKENS", DEFAULT_SUMMARY_MAX_TOKENS, int),
        help=f"Maximum token size for entity/relation summary(default: from env or {DEFAULT_SUMMARY_MAX_TOKENS})",
    )
    parser.add_argument(
        "--summary-context-size",
        type=int,
        default=get_db_or_env(
            "SUMMARY_CONTEXT_SIZE", DEFAULT_SUMMARY_CONTEXT_SIZE, int
        ),
        help=f"LLM Summary Context size (default: from env or {DEFAULT_SUMMARY_CONTEXT_SIZE})",
    )
    parser.add_argument(
        "--summary-length-recommended",
        type=int,
        default=get_db_or_env(
            "SUMMARY_LENGTH_RECOMMENDED", DEFAULT_SUMMARY_LENGTH_RECOMMENDED, int
        ),
        help=f"LLM Summary Context size (default: from env or {DEFAULT_SUMMARY_LENGTH_RECOMMENDED})",
    )

    # Logging configuration
    parser.add_argument(
        "--log-level",
        default=get_db_or_env("LOG_LEVEL", "INFO"),
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Logging level (default: from env or INFO)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        default=get_db_or_env("VERBOSE", False, bool),
        help="Enable verbose debug output(only valid for DEBUG log-level)",
    )

    parser.add_argument(
        "--key",
        type=str,
        default=get_db_or_env("LIGHTRAG_API_KEY", None),
        help="API key for authentication. This protects lightrag server against unauthorized access",
    )

    # Optional https parameters
    parser.add_argument(
        "--ssl",
        action="store_true",
        default=get_db_or_env("SSL", False, bool),
        help="Enable HTTPS (default: from env or False)",
    )
    parser.add_argument(
        "--ssl-certfile",
        default=get_db_or_env("SSL_CERTFILE", None),
        help="Path to SSL certificate file (required if --ssl is enabled)",
    )
    parser.add_argument(
        "--ssl-keyfile",
        default=get_db_or_env("SSL_KEYFILE", None),
        help="Path to SSL private key file (required if --ssl is enabled)",
    )

    # Ollama model configuration
    parser.add_argument(
        "--simulated-model-name",
        type=str,
        default=get_db_or_env("OLLAMA_EMULATING_MODEL_NAME", DEFAULT_OLLAMA_MODEL_NAME),
        help="Name for the simulated Ollama model (default: from env or lightrag)",
    )

    parser.add_argument(
        "--simulated-model-tag",
        type=str,
        default=get_db_or_env("OLLAMA_EMULATING_MODEL_TAG", DEFAULT_OLLAMA_MODEL_TAG),
        help="Tag for the simulated Ollama model (default: from env or latest)",
    )

    # Namespace
    parser.add_argument(
        "--workspace",
        type=str,
        default=get_db_or_env("WORKSPACE", ""),
        help="Default workspace for all storage",
    )

    # Server workers configuration
    parser.add_argument(
        "--workers",
        type=int,
        default=get_db_or_env("WORKERS", DEFAULT_WOKERS, int),
        help="Number of worker processes (default: from env or 1)",
    )

    # LLM and embedding bindings
    parser.add_argument(
        "--llm-binding",
        type=str,
        default=get_db_or_env("LLM_BINDING", "ollama"),
        choices=[
            "lollms",
            "ollama",
            "openai_codex",
            "codex_cli",
            "openai",
            "openai-ollama",
            "azure_openai",
            "aws_bedrock",
            "gemini",
        ],
        help="LLM binding type (default: from env or ollama)",
    )
    parser.add_argument(
        "--embedding-binding",
        type=str,
        default=get_db_or_env("EMBEDDING_BINDING", "ollama"),
        choices=[
            "lollms",
            "ollama",
            "openai",
            "azure_openai",
            "aws_bedrock",
            "jina",
            "gemini",
        ],
        help="Embedding binding type (default: from env or ollama)",
    )
    parser.add_argument(
        "--rerank-binding",
        type=str,
        default=get_db_or_env("RERANK_BINDING", DEFAULT_RERANK_BINDING),
        choices=["null", "cohere", "jina", "aliyun"],
        help=f"Rerank binding type (default: from env or {DEFAULT_RERANK_BINDING})",
    )

    # Document loading engine configuration
    parser.add_argument(
        "--docling",
        action="store_true",
        default=False,
        help="Enable DOCLING document loading engine (default: from env or DEFAULT)",
    )

    # Conditionally add binding options defined in binding_options module
    # This will add command line arguments for all binding options (e.g., --ollama-embedding-num_ctx)
    # and corresponding environment variables (e.g., OLLAMA_EMBEDDING_NUM_CTX)
    # if "--llm-binding" in sys.argv:
    # TODO:  refactor to be storage specific
    # logger.info("--llm-binding specified in command line, checking for specific binding options...")
    # try:
    #     idx = sys.argv.index("--llm-binding")
    #     if idx + 1 < len(sys.argv) and sys.argv[idx + 1] == "ollama":
    #         OllamaLLMOptions.add_args(parser)
    # except IndexError:
    #     pass
    # elif os.environ.get("LLM_BINDING") == "ollama":
    # OllamaLLMOptions.add_args(parser)
    # else:
    #     logger.info("LLM_BINDING is not set to ollama, skipping OllamaLLMOptions")

    if "--embedding-binding" in sys.argv:
        try:
            idx = sys.argv.index("--embedding-binding")
            if idx + 1 < len(sys.argv):
                if sys.argv[idx + 1] == "ollama":
                    OllamaEmbeddingOptions.add_args(parser)
                elif sys.argv[idx + 1] == "gemini":
                    GeminiEmbeddingOptions.add_args(parser)
        except IndexError:
            pass
    else:
        env_embedding_binding = os.environ.get("EMBEDDING_BINDING")
        if env_embedding_binding == "ollama":
            OllamaEmbeddingOptions.add_args(parser)
        elif env_embedding_binding == "gemini":
            GeminiEmbeddingOptions.add_args(parser)

    # Add OpenAI LLM options when llm-binding is openai or azure_openai
    if "--llm-binding" in sys.argv:
        try:
            idx = sys.argv.index("--llm-binding")
            if idx + 1 < len(sys.argv) and sys.argv[idx + 1] in [
                "openai",
                "openai_codex",
                "azure_openai",
            ]:
                OpenAILLMOptions.add_args(parser)
        except IndexError:
            pass
    elif os.environ.get("LLM_BINDING") in ["openai", "openai_codex", "azure_openai"]:
        OpenAILLMOptions.add_args(parser)

    if "--llm-binding" in sys.argv:
        try:
            idx = sys.argv.index("--llm-binding")
            if idx + 1 < len(sys.argv) and sys.argv[idx + 1] == "gemini":
                GeminiLLMOptions.add_args(parser)
        except IndexError:
            pass
    elif os.environ.get("LLM_BINDING") == "gemini":
        GeminiLLMOptions.add_args(parser)

    if argv is None and os.getenv("LIGHTRAG_PARSE_ARGS_FROM_ENV_ONLY", "").lower() in (
        "1",
        "true",
        "yes",
        "on",
    ):
        argv = []

    args = parser.parse_args(argv)

    # convert relative path to absolute path
    args.working_dir = os.path.abspath(args.working_dir)
    args.input_dir = os.path.abspath(args.input_dir)

    # Inject storage configuration from environment variables
    args.kv_storage = get_db_or_env(
        "LIGHTRAG_KV_STORAGE", DefaultRAGStorageConfig.KV_STORAGE
    )
    args.doc_status_storage = get_db_or_env(
        "LIGHTRAG_DOC_STATUS_STORAGE", DefaultRAGStorageConfig.DOC_STATUS_STORAGE
    )
    args.graph_storage = get_db_or_env(
        "LIGHTRAG_GRAPH_STORAGE", DefaultRAGStorageConfig.GRAPH_STORAGE
    )
    args.vector_storage = get_db_or_env(
        "LIGHTRAG_VECTOR_STORAGE", DefaultRAGStorageConfig.VECTOR_STORAGE
    )

    # Get MAX_PARALLEL_INSERT from environment
    args.max_parallel_insert = get_db_or_env("MAX_PARALLEL_INSERT", 2, int)

    # Get MAX_GRAPH_NODES from environment
    args.max_graph_nodes = get_db_or_env(
        "MAX_GRAPH_NODES", DEFAULT_MAX_GRAPH_NODES, int
    )

    # Handle openai-ollama special case
    if args.llm_binding == "openai-ollama":
        args.llm_binding = "openai"
        args.embedding_binding = "ollama"

    # Ollama ctx_num
    args.ollama_num_ctx = get_db_or_env("OLLAMA_NUM_CTX", 32768, int)

    args.llm_binding_host = get_db_or_env(
        "LLM_BINDING_HOST", get_default_host(args.llm_binding)
    )
    args.embedding_binding_host = get_db_or_env(
        "EMBEDDING_BINDING_HOST", get_default_host(args.embedding_binding)
    )
    args.llm_binding_api_key = get_db_or_env("LLM_BINDING_API_KEY", None)
    args.embedding_binding_api_key = get_db_or_env("EMBEDDING_BINDING_API_KEY", "")

    # Inject model configuration
    args.llm_model = get_db_or_env("LLM_MODEL", "mistral-nemo:latest")
    # EMBEDDING_MODEL defaults to None - each binding will use its own default model
    # e.g., OpenAI uses "text-embedding-3-small", Jina uses "jina-embeddings-v4"
    args.embedding_model = get_db_or_env("EMBEDDING_MODEL", None, special_none=True)
    # EMBEDDING_DIM defaults to None - each binding will use its own default dimension
    # Value is inherited from provider defaults via wrap_embedding_func_with_attrs decorator
    args.embedding_dim = get_db_or_env("EMBEDDING_DIM", None, int, special_none=True)
    args.embedding_send_dim = get_db_or_env("EMBEDDING_SEND_DIM", False, bool)

    # Inject chunk configuration
    args.chunk_size = get_db_or_env("CHUNK_SIZE", 1200, int)
    args.chunk_overlap_size = get_db_or_env("CHUNK_OVERLAP_SIZE", 100, int)

    # Inject LLM cache configuration
    args.enable_llm_cache_for_extract = get_db_or_env(
        "ENABLE_LLM_CACHE_FOR_EXTRACT", True, bool
    )
    args.enable_llm_cache = get_db_or_env("ENABLE_LLM_CACHE", True, bool)

    # Set document_loading_engine from --docling flag
    if args.docling:
        args.document_loading_engine = "DOCLING"
    else:
        args.document_loading_engine = get_db_or_env(
            "DOCUMENT_LOADING_ENGINE", "DEFAULT"
        )

    # PDF decryption password
    args.pdf_decrypt_password = get_db_or_env("PDF_DECRYPT_PASSWORD", None)

    # Add environment variables that were previously read directly
    args.cors_origins = get_db_or_env("CORS_ORIGINS", "*")
    args.summary_language = get_db_or_env("SUMMARY_LANGUAGE", DEFAULT_SUMMARY_LANGUAGE)
    args.entity_types = get_db_or_env("ENTITY_TYPES", DEFAULT_ENTITY_TYPES, list)
    args.whitelist_paths = get_db_or_env("WHITELIST_PATHS", "/health,/api/*")

    # For JWT Auth
    args.auth_accounts = get_db_or_env("AUTH_ACCOUNTS", "")
    args.token_secret = get_db_or_env("TOKEN_SECRET", "lightrag-jwt-default-secret")
    args.token_expire_hours = get_db_or_env("TOKEN_EXPIRE_HOURS", 48, int)
    args.guest_token_expire_hours = get_db_or_env("GUEST_TOKEN_EXPIRE_HOURS", 24, int)
    args.jwt_algorithm = get_db_or_env("JWT_ALGORITHM", "HS256")

    # Rerank model configuration
    args.rerank_model = get_db_or_env("RERANK_MODEL", None)
    args.rerank_binding_host = get_db_or_env("RERANK_BINDING_HOST", None)
    args.rerank_binding_api_key = get_db_or_env("RERANK_BINDING_API_KEY", None)
    # Note: rerank_binding is already set by argparse, no need to override from env

    # Min rerank score configuration
    args.min_rerank_score = get_db_or_env(
        "MIN_RERANK_SCORE", DEFAULT_MIN_RERANK_SCORE, float
    )

    # Query configuration
    args.history_turns = get_db_or_env("HISTORY_TURNS", DEFAULT_HISTORY_TURNS, int)
    args.top_k = get_db_or_env("TOP_K", DEFAULT_TOP_K, int)
    args.chunk_top_k = get_db_or_env("CHUNK_TOP_K", DEFAULT_CHUNK_TOP_K, int)
    args.max_entity_tokens = get_db_or_env(
        "MAX_ENTITY_TOKENS", DEFAULT_MAX_ENTITY_TOKENS, int
    )
    args.max_relation_tokens = get_db_or_env(
        "MAX_RELATION_TOKENS", DEFAULT_MAX_RELATION_TOKENS, int
    )
    args.max_total_tokens = get_db_or_env(
        "MAX_TOTAL_TOKENS", DEFAULT_MAX_TOTAL_TOKENS, int
    )
    args.cosine_threshold = get_db_or_env(
        "COSINE_THRESHOLD", DEFAULT_COSINE_THRESHOLD, float
    )
    args.related_chunk_number = get_db_or_env(
        "RELATED_CHUNK_NUMBER", DEFAULT_RELATED_CHUNK_NUMBER, int
    )

    # Add missing environment variables for health endpoint
    args.force_llm_summary_on_merge = get_db_or_env(
        "FORCE_LLM_SUMMARY_ON_MERGE", DEFAULT_FORCE_LLM_SUMMARY_ON_MERGE, int
    )
    args.embedding_func_max_async = get_db_or_env(
        "EMBEDDING_FUNC_MAX_ASYNC", DEFAULT_EMBEDDING_FUNC_MAX_ASYNC, int
    )
    args.embedding_batch_num = get_db_or_env(
        "EMBEDDING_BATCH_NUM", DEFAULT_EMBEDDING_BATCH_NUM, int
    )

    # Embedding token limit configuration
    args.embedding_token_limit = get_db_or_env(
        "EMBEDDING_TOKEN_LIMIT", None, int, special_none=True
    )

    ollama_server_infos.LIGHTRAG_NAME = args.simulated_model_name
    ollama_server_infos.LIGHTRAG_TAG = args.simulated_model_tag

    return args


def update_uvicorn_mode_config():
    # If in uvicorn mode and workers > 1, force it to 1 and log warning
    if global_args.workers > 1:
        original_workers = global_args.workers
        global_args.workers = 1
        # Log warning directly here
        logging.warning(
            f">> Forcing workers=1 in uvicorn mode(Ignoring workers={original_workers})"
        )


# Global configuration with lazy initialization
_global_args = None
_initialized = False


def initialize_config(args=None, force=False):
    """Initialize global configuration

    This function allows explicit initialization of the configuration,
    which is useful for programmatic usage, testing, or embedding LightRAG
    in other applications.

    Args:
        args: Pre-parsed argparse.Namespace or None to parse from sys.argv
        force: Force re-initialization even if already initialized

    Returns:
        argparse.Namespace: The configured arguments

    Example:
        # Use parsed command line arguments (default)
        initialize_config()

        # Use custom configuration programmatically
        custom_args = argparse.Namespace(
            host='localhost',
            port=8080,
            working_dir='./custom_rag',
            # ... other config
        )
        initialize_config(custom_args)
    """
    global _global_args, _initialized
    if _initialized and not force:
        return _global_args

    # Initialize database BEFORE parsing args to ensure migrations run
    # before any config code tries to query the database
    if args is None:  # Only initialize DB when parsing args from scratch
        try:
            from retriqs.api.database.settings_manager import initialize_db_settings

            initialize_db_settings()
        except Exception as e:
            logger.warning(f"Could not initialize database during config: {e}")

    _global_args = args if args is not None else parse_args()
    _initialized = True
    return _global_args


def get_config():
    """Get global configuration, auto-initializing if needed

    Returns:
        argparse.Namespace: The configured arguments
    """
    if not _initialized:
        initialize_config()
    return _global_args


class _GlobalArgsProxy:
    """Proxy object that auto-initializes configuration on first access

    This maintains backward compatibility with existing code while
    allowing programmatic control over initialization timing.
    """

    def __getattr__(self, name):
        if not _initialized:
            initialize_config()
        return getattr(_global_args, name)

    def __setattr__(self, name, value):
        if not _initialized:
            initialize_config()
        setattr(_global_args, name, value)

    def __repr__(self):
        if not _initialized:
            return "<GlobalArgsProxy: Not initialized>"
        return repr(_global_args)


def build_storage_args(storage, base_args=None):
    """
    Build storage-specific args from database settings with fallback to defaults.

    This function creates a properly configured argparse.Namespace for a specific storage
    by combining base configuration with storage-specific settings from the database.
    This ensures each storage/tenant has its own isolated configuration rather than
    sharing global args.

    Args:
        storage: GraphStorage database model instance with storage_settings relationship loaded
        base_args: Base argparse.Namespace to copy from (defaults to global_args if None)

    Returns:
        argparse.Namespace: Storage-specific args ready for build_rag_instance
    """
    import copy
    import os

    # Use global_args as base if none provided
    if base_args is None:
        base_args = get_config()

    # Deep copy to avoid mutating base args
    instance_args = copy.deepcopy(base_args)

    # Type conversion mappings
    integer_fields = [
        "embedding_dim",
        "embedding_token_limit",
        "ollama_num_ctx",
        "ollama_llm_num_ctx",
        "ollama_embedding_num_ctx",
        "max_async",
        "max_parallel_insert",
        "embedding_func_max_async",
        "embedding_batch_num",
        "port",
        "workers",
        "timeout",
        "summary_max_tokens",
        "summary_context_size",
        "summary_length_recommended",
        "chunk_size",
        "chunk_overlap_size",
        "max_graph_nodes",
        "top_k",
        "chunk_top_k",
        "max_entity_tokens",
        "max_relation_tokens",
        "max_total_tokens",
        "history_turns",
        "related_chunk_number",
        "force_llm_summary_on_merge",
        "token_expire_hours",
        "guest_token_expire_hours",
    ]

    float_fields = [
        "cosine_threshold",
        "min_rerank_score",
    ]

    bool_fields = [
        "enable_rerank",
        "force_llm_summary_on_merge",
        "enable_llm_cache_for_extract",
        "enable_llm_cache",
        "verbose",
        "ssl",
        "docling",
        "embedding_send_dim",
    ]

    # Apply storage-specific settings from database
    for setting in storage.storage_settings:
        attr_name = setting.key.lower()
        attr_value = setting.value

        logger.debug(
            f"Processing setting for storage {storage.id}: {attr_name} = {attr_value}"
        )

        # Type conversion based on field type
        if attr_name in integer_fields:
            try:
                attr_value = int(attr_value) if attr_value else None
            except (ValueError, TypeError):
                logger.warning(
                    f"Could not convert {attr_name}={attr_value} to int, using as-is"
                )
        elif attr_name in float_fields:
            try:
                attr_value = float(attr_value) if attr_value else None
            except (ValueError, TypeError):
                logger.warning(
                    f"Could not convert {attr_name}={attr_value} to float, using as-is"
                )
        elif attr_name in bool_fields:
            if isinstance(attr_value, str):
                attr_value = attr_value.lower() in ("true", "1", "yes", "on")
        elif hasattr(instance_args, attr_name):
            # Fallback: try to infer type from existing attribute
            current_value = getattr(instance_args, attr_name)
            if isinstance(current_value, int):
                try:
                    attr_value = int(attr_value)
                except (ValueError, TypeError):
                    pass
            elif isinstance(current_value, float):
                try:
                    attr_value = float(attr_value)
                except (ValueError, TypeError):
                    pass
            elif isinstance(current_value, bool):
                if isinstance(attr_value, str):
                    attr_value = attr_value.lower() in ("true", "1", "yes", "on")

        setattr(instance_args, attr_name, attr_value)

    # Apply Neo4j, Milvus, and Redis settings from storage (for per-storage isolation)
    for setting in storage.storage_settings:
        attr_name = setting.key.lower()
        if attr_name == "neo4j_uri":
            instance_args.neo4j_uri = setting.value
        elif attr_name == "neo4j_username":
            instance_args.neo4j_username = setting.value
        elif attr_name == "neo4j_password":
            instance_args.neo4j_password = setting.value
        elif attr_name == "milvus_uri":
            instance_args.milvus_uri = setting.value
        elif attr_name == "milvus_user":
            instance_args.milvus_user = setting.value
        elif attr_name == "milvus_password":
            instance_args.milvus_password = setting.value
        elif attr_name == "milvus_db_name":
            instance_args.milvus_db_name = setting.value
        elif attr_name == "redis_uri":
            instance_args.redis_uri = setting.value
        elif attr_name == "embedding_binding_api_key":
            logger.info(
                "Setting embedding_binding_api_key for storage %s (value hidden)",
                storage.id,
            )
            instance_args.embedding_binding_api_key = setting.value
        elif attr_name == "embedding_binding_host":
            logger.info(f"Setting embedding_binding_host for storage {storage.id} from setting value {setting.value}")
            instance_args.embedding_binding_host = setting.value

    # Set working directory and workspace from storage path
    # Use absolute path to safely split into dir and workspace name
    # This ensures:
    # 1. Correct file path construction: working_dir / workspace
    # 2. Memory isolation: each tenant has a unique workspace name for locks/status
    abs_work_dir = os.path.abspath(storage.work_dir)
    instance_args.working_dir = os.path.dirname(abs_work_dir)
    instance_args.workspace = os.path.basename(abs_work_dir)

    # # ollama_num_ctx = getattr(instance_args, "ollama_num_ctx", None)
    # if getattr(instance_args, "ollama_llm_num_ctx", None) in (None, ""):
    #     instance_args.ollama_llm_num_ctx = ollama_num_ctx
    # if getattr(instance_args, "ollama_embedding_num_ctx", None) in (None, ""):
    #     instance_args.ollama_embedding_num_ctx = ollama_num_ctx

    graph_storage_setting = next(
        (
            s
            for s in storage.storage_settings
            if s.key.lower() == "lightrag_graph_storage"
        ),
        None,
    )
    if graph_storage_setting:
        instance_args.graph_storage = graph_storage_setting.value

    kv_storage_setting = next(
        (s for s in storage.storage_settings if s.key.lower() == "lightrag_kv_storage"),
        None,
    )
    if kv_storage_setting:
        instance_args.kv_storage = kv_storage_setting.value

    doc_status_storage_setting = next(
        (
            s
            for s in storage.storage_settings
            if s.key.lower() == "lightrag_doc_status_storage"
        ),
        None,
    )
    if doc_status_storage_setting:
        instance_args.doc_status_storage = doc_status_storage_setting.value

    vector_storage_setting = next(
        (
            s
            for s in storage.storage_settings
            if s.key.lower() == "lightrag_vector_storage"
        ),
        None,
    )
    if vector_storage_setting:
        instance_args.vector_storage = vector_storage_setting.value

    logger.info(
        f"Built args for storage {storage.id} (graph_storage type: {instance_args.graph_storage})"
    )

    logger.info(
        f"Built args for storage {storage.id} (workspace: {instance_args.workspace})"
    )

    return instance_args


# Create proxy instance for backward compatibility
# Existing code like `from config import global_args` continues to work
# The proxy will auto-initialize on first attribute access
global_args = _GlobalArgsProxy()
