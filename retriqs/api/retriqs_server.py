"""
LightRAG FastAPI Server
"""

from fastapi import FastAPI, Depends, HTTPException, Request, APIRouter, Depends
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.openapi.docs import (
    get_swagger_ui_html,
    get_swagger_ui_oauth2_redirect_html,
)
import os
import logging
import logging.config
import sys
import uvicorn
import pipmaster as pm
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse, FileResponse
from pathlib import Path
import configparser
from ascii_colors import ASCIIColors
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager, AsyncExitStack
from dotenv import load_dotenv
from retriqs.api.mcp_api import create_mcp_server
from retriqs.api.utils_api import (
    get_combined_auth_dependency,
    display_splash_screen,
)
from .config import (
    global_args,
    update_uvicorn_mode_config,
    get_default_host,
)
from retriqs.utils import get_env_value
from retriqs import LightRAG, __version__ as core_version
from retriqs.api import __api_version__
from retriqs.types import GPTKeywordExtractionFormat
from retriqs.utils import EmbeddingFunc
from retriqs.constants import (
    DEFAULT_LOG_MAX_BYTES,
    DEFAULT_LOG_BACKUP_COUNT,
    DEFAULT_LOG_FILENAME,
    DEFAULT_LLM_TIMEOUT,
    DEFAULT_EMBEDDING_TIMEOUT,
)
from retriqs.api.routers.document_routes import (
    DocumentManager,
    create_document_routes,
)
from retriqs.api.routers.query_routes import create_query_routes
from retriqs.api.routers.graph_routes import create_graph_routes

# Import the new manager
from retriqs.api.database.settings_manager import (
    initialize_db_settings,
    get_graph_storages,
)
from retriqs.api.routers.ollama_api import OllamaAPI
from retriqs.utils import logger, set_verbose_debug
from retriqs.kg.shared_storage import (
    get_namespace_data,
    get_default_workspace,
    # set_default_workspace,
    cleanup_keyed_lock,
    finalize_share_data,
)
from fastapi.security import OAuth2PasswordRequestForm
from retriqs.api.auth import auth_handler
from retriqs.api.dependencies import get_rag_by_id
from retriqs.api.storage_paths import (
    warn_if_legacy_rag_storage_present,
    resolve_log_file_path,
)
import copy


# use the .env that is inside the current folder
# allows to use different .env file for each lightrag instance


webui_title = "d3vsRAG Home"
webui_description = "Application by d3vsRAG"

# Initialize config parser
config = configparser.ConfigParser()
config.read("config.ini")

# Global authentication configuration
auth_configured = bool(auth_handler.accounts)


def safe_console_message(message: str) -> None:
    """Write startup output without failing on unsupported console encodings."""
    try:
        ASCIIColors.green(message)
    except UnicodeEncodeError:
        print(message.encode("ascii", errors="ignore").decode("ascii"))


_original_ascii_green = ASCIIColors.green


def _safe_ascii_green(*args, **kwargs):
    try:
        return _original_ascii_green(*args, **kwargs)
    except UnicodeEncodeError:
        if args:
            message = str(args[0]).encode("ascii", errors="ignore").decode("ascii")
            print(message, **kwargs)
        return None


ASCIIColors.green = _safe_ascii_green


def _raise_missing_gemini_support(error: ImportError) -> None:
    raise RuntimeError(
        "Gemini support is not available in this packaged desktop build. "
        "Rebuild the backend with scripts/build_nuitka_sidecar.ps1 -EnableGemini "
        "if you need Gemini bindings."
    ) from error


class LLMConfigCache:
    """Smart LLM and Embedding configuration cache class"""

    def __init__(self, args):
        self.args = args

        # Initialize configurations based on binding conditions
        self.openai_llm_options = None
        self.gemini_llm_options = None
        self.gemini_embedding_options = None
        self.ollama_llm_options = None
        self.ollama_embedding_options = None

        # Only initialize and log OpenAI options when using OpenAI-related bindings
        if args.llm_binding in ["openai", "openai_codex", "azure_openai"]:
            from retriqs.llm.binding_options import OpenAILLMOptions

            self.openai_llm_options = OpenAILLMOptions.options_dict(args)
            logger.info(f"OpenAI LLM Options: {self.openai_llm_options}")

        if args.llm_binding == "gemini":
            from retriqs.llm.binding_options import GeminiLLMOptions

            self.gemini_llm_options = GeminiLLMOptions.options_dict(args)
            logger.info(f"Gemini LLM Options: {self.gemini_llm_options}")

        # Only initialize and log Ollama LLM options when using Ollama LLM binding
        if args.llm_binding == "ollama":
            try:
                from retriqs.llm.binding_options import OllamaLLMOptions

                self.ollama_llm_options = OllamaLLMOptions.options_dict(args)
                logger.info(f"Ollama LLM Options: {self.ollama_llm_options}")
            except ImportError:
                logger.warning(
                    "OllamaLLMOptions not available, using default configuration"
                )
                self.ollama_llm_options = {}

        # Only initialize and log Ollama Embedding options when using Ollama Embedding binding
        if args.embedding_binding == "ollama":
            try:
                from retriqs.llm.binding_options import OllamaEmbeddingOptions

                self.ollama_embedding_options = OllamaEmbeddingOptions.options_dict(
                    args
                )
                logger.info(
                    f"Ollama Embedding Options: {self.ollama_embedding_options}"
                )
            except ImportError:
                logger.warning(
                    "OllamaEmbeddingOptions not available, using default configuration"
                )
                self.ollama_embedding_options = {}

        # Only initialize and log Gemini Embedding options when using Gemini Embedding binding
        if args.embedding_binding == "gemini":
            try:
                from retriqs.llm.binding_options import GeminiEmbeddingOptions

                self.gemini_embedding_options = GeminiEmbeddingOptions.options_dict(
                    args
                )
                logger.info(
                    f"Gemini Embedding Options: {self.gemini_embedding_options}"
                )
            except ImportError:
                logger.warning(
                    "GeminiEmbeddingOptions not available, using default configuration"
                )
                self.gemini_embedding_options = {}


class RAGProxy:
    """A proxy that forwards all calls to the actual LightRAG instance.
    This allows us to swap the underlying RAG instance at runtime without
    breaking the FastAPI routers that hold a reference to it.
    """

    def __init__(self, instance: LightRAG | None):
        self._instance = instance

    def set_instance(self, new_instance: LightRAG):
        self._instance = new_instance

    def __getattr__(self, name):
        # Forward any attribute/method access to the real instance
        if self._instance is None:
            raise HTTPException(
                status_code=503,
                detail="No RAG instance initialized. Please create a storage/tenant first.",
            )
        return getattr(self._instance, name)


class RAGManager:
    def __init__(self):
        self._instances: dict[int, LightRAG] = {}

    def get_instance(self, storage_id: int) -> LightRAG | None:
        return self._instances.get(storage_id)

    def set_instance(self, storage_id: int, instance: LightRAG):
        self._instances[storage_id] = instance

    def remove_instance(self, storage_id: int):
        if storage_id in self._instances:
            del self._instances[storage_id]

    def all_instances(self):
        return self._instances.items()


class MCPMountPathMiddleware:
    """
    Normalize mounted MCP path so both /mcp and /mcp/ reach FastMCP.

    Some MCP clients POST to /mcp without trailing slash and do not follow
    redirects consistently. FastMCP mounted under /mcp expects the effective
    inner path /, which is reached reliably through /mcp/.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") == "http" and scope.get("path") == "/mcp":
            scope = dict(scope)
            scope["path"] = "/mcp/"
            raw_path = scope.get("raw_path")
            if raw_path == b"/mcp":
                scope["raw_path"] = b"/mcp/"
        await self.app(scope, receive, send)


def check_frontend_build():
    """Check if frontend is built and optionally check if source is up-to-date

    Returns:
        tuple: (assets_exist: bool, is_outdated: bool)
            - assets_exist: True if WebUI build files exist
            - is_outdated: True if source is newer than build (only in dev environment)
    """
    webui_dir = Path(__file__).parent / "webui"
    index_html = webui_dir / "index.html"

    # 1. Check if build files exist
    if not index_html.exists():
        ASCIIColors.yellow("\n" + "=" * 80)
        ASCIIColors.yellow("WARNING: Frontend Not Built")
        ASCIIColors.yellow("=" * 80)
        ASCIIColors.yellow("The WebUI frontend has not been built yet.")
        ASCIIColors.yellow("The API server will start without the WebUI interface.")
        ASCIIColors.yellow(
            "\nTo enable WebUI, build the frontend using these commands:\n"
        )
        ASCIIColors.cyan("    cd retriqs_webui")
        ASCIIColors.cyan("    bun install --frozen-lockfile")
        ASCIIColors.cyan("    bun run build")
        ASCIIColors.cyan("    cd ..")
        ASCIIColors.yellow("\nThen restart the service.\n")
        ASCIIColors.cyan(
            "Note: Make sure you have Bun installed. Visit https://bun.sh for installation."
        )
        ASCIIColors.yellow("=" * 80 + "\n")
        return (False, False)  # Assets don't exist, not outdated

    # 2. Check if this is a development environment (source directory exists)
    try:
        source_dir = Path(__file__).parent.parent.parent / "retriqs_webui"
        src_dir = source_dir / "src"

        # Determine if this is a development environment: source directory exists and contains src directory
        if not source_dir.exists() or not src_dir.exists():
            # Production environment, skip source code check
            logger.debug(
                "Production environment detected, skipping source freshness check"
            )
            return (True, False)  # Assets exist, not outdated (prod environment)

        # Development environment, perform source code timestamp check
        logger.debug("Development environment detected, checking source freshness")

        # Source code file extensions (files to check)
        source_extensions = {
            ".ts",
            ".tsx",
            ".js",
            ".jsx",
            ".mjs",
            ".cjs",  # TypeScript/JavaScript
            ".css",
            ".scss",
            ".sass",
            ".less",  # Style files
            ".json",
            ".jsonc",  # Configuration/data files
            ".html",
            ".htm",  # Template files
            ".md",
            ".mdx",  # Markdown
        }

        # Key configuration files (in retriqs_webui root directory)
        key_files = [
            source_dir / "package.json",
            source_dir / "bun.lock",
            source_dir / "vite.config.ts",
            source_dir / "tsconfig.json",
            source_dir / "tailraid.config.js",
            source_dir / "index.html",
        ]

        # Get the latest modification time of source code
        latest_source_time = 0

        # Check source code files in src directory
        for file_path in src_dir.rglob("*"):
            if file_path.is_file():
                # Only check source code files, ignore temporary files and logs
                if file_path.suffix.lower() in source_extensions:
                    mtime = file_path.stat().st_mtime
                    latest_source_time = max(latest_source_time, mtime)

        # Check key configuration files
        for key_file in key_files:
            if key_file.exists():
                mtime = key_file.stat().st_mtime
                latest_source_time = max(latest_source_time, mtime)

        # Get build time
        build_time = index_html.stat().st_mtime

        # Compare timestamps (5 second tolerance to avoid file system time precision issues)
        if latest_source_time > build_time + 5:
            ASCIIColors.yellow("\n" + "=" * 80)
            ASCIIColors.yellow("WARNING: Frontend Source Code Has Been Updated")
            ASCIIColors.yellow("=" * 80)
            ASCIIColors.yellow(
                "The frontend source code is newer than the current build."
            )
            ASCIIColors.yellow(
                "This might happen after 'git pull' or manual code changes.\n"
            )
            ASCIIColors.cyan(
                "Recommended: Rebuild the frontend to use the latest changes:"
            )
            ASCIIColors.cyan("    cd retriqs_webui")
            ASCIIColors.cyan("    bun install --frozen-lockfile")
            ASCIIColors.cyan("    bun run build")
            ASCIIColors.cyan("    cd ..")
            ASCIIColors.yellow("\nThe server will continue with the current build.")
            ASCIIColors.yellow("=" * 80 + "\n")
            return (True, True)  # Assets exist, outdated
        else:
            logger.info("Frontend build is up-to-date")
            return (True, False)  # Assets exist, up-to-date

    except Exception as e:
        # If check fails, log warning but don't affect startup
        logger.warning(f"Failed to check frontend source freshness: {e}")
        return (True, False)  # Assume assets exist and up-to-date on error


def build_rag_instance(args) -> LightRAG:

    def create_optimized_azure_openai_llm_func(
        config_cache: LLMConfigCache, args, llm_timeout: int
    ):
        """Create optimized Azure OpenAI LLM function with pre-processed configuration"""

        async def optimized_azure_openai_model_complete(
            prompt,
            system_prompt=None,
            history_messages=None,
            keyword_extraction=False,
            **kwargs,
        ) -> str:
            from retriqs.llm.azure_openai import azure_openai_complete_if_cache

            keyword_extraction = kwargs.pop("keyword_extraction", None)
            if keyword_extraction:
                kwargs["response_format"] = GPTKeywordExtractionFormat
            if history_messages is None:
                history_messages = []

            # Use pre-processed configuration to avoid repeated parsing
            kwargs["timeout"] = llm_timeout
            if config_cache.openai_llm_options:
                kwargs.update(config_cache.openai_llm_options)

            return await azure_openai_complete_if_cache(
                args.llm_model,
                prompt,
                system_prompt=system_prompt,
                history_messages=history_messages,
                base_url=args.llm_binding_host,
                api_key=os.getenv("AZURE_OPENAI_API_KEY", args.llm_binding_api_key),
                api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-08-01-preview"),
                **kwargs,
            )

        return optimized_azure_openai_model_complete

    def create_optimized_gemini_llm_func(
        config_cache: LLMConfigCache, args, llm_timeout: int
    ):
        """Create optimized Gemini LLM function with cached configuration"""

        async def optimized_gemini_model_complete(
            prompt,
            system_prompt=None,
            history_messages=None,
            keyword_extraction=False,
            **kwargs,
        ) -> str:
            try:
                from retriqs.llm.gemini import gemini_complete_if_cache
            except ImportError as error:
                _raise_missing_gemini_support(error)

            if history_messages is None:
                history_messages = []

            # Use pre-processed configuration to avoid repeated parsing
            kwargs["timeout"] = llm_timeout
            if (
                config_cache.gemini_llm_options is not None
                and "generation_config" not in kwargs
            ):
                kwargs["generation_config"] = dict(config_cache.gemini_llm_options)

            return await gemini_complete_if_cache(
                args.llm_model,
                prompt,
                system_prompt=system_prompt,
                history_messages=history_messages,
                api_key=args.llm_binding_api_key,
                base_url=args.llm_binding_host,
                keyword_extraction=keyword_extraction,
                **kwargs,
            )

        return optimized_gemini_model_complete

    def create_optimized_openai_llm_func(
        config_cache: LLMConfigCache, args, llm_timeout: int
    ):
        """Create optimized OpenAI LLM function with pre-processed configuration"""

        async def optimized_openai_alike_model_complete(
            prompt,
            system_prompt=None,
            history_messages=None,
            keyword_extraction=False,
            **kwargs,
        ) -> str:
            from retriqs.llm.openai import openai_complete_if_cache

            keyword_extraction = kwargs.pop("keyword_extraction", None)
            if keyword_extraction:
                kwargs["response_format"] = GPTKeywordExtractionFormat
            if history_messages is None:
                history_messages = []

            # Use pre-processed configuration to avoid repeated parsing
            kwargs["timeout"] = llm_timeout
            if config_cache.openai_llm_options:
                kwargs.update(config_cache.openai_llm_options)

            return await openai_complete_if_cache(
                args.llm_model,
                prompt,
                system_prompt=system_prompt,
                history_messages=history_messages,
                base_url=args.llm_binding_host,
                api_key=args.llm_binding_api_key,
                **kwargs,
            )

        return optimized_openai_alike_model_complete

    def create_optimized_openai_codex_llm_func(
        config_cache: LLMConfigCache, args, llm_timeout: int
    ):
        """Create OpenAI Codex OAuth backed LLM function."""

        async def optimized_openai_codex_model_complete(
            prompt,
            system_prompt=None,
            history_messages=None,
            keyword_extraction=False,
            **kwargs,
        ) -> str:
            from retriqs.llm.openai_codex import openai_codex_complete_if_cache

            keyword_extraction = kwargs.pop(
                "keyword_extraction", keyword_extraction
            )
            if keyword_extraction:
                kwargs["response_format"] = GPTKeywordExtractionFormat
            if history_messages is None:
                history_messages = []

            kwargs["timeout"] = llm_timeout
            if config_cache.openai_llm_options:
                kwargs.update(config_cache.openai_llm_options)

            return await openai_codex_complete_if_cache(
                args.llm_model,
                prompt,
                system_prompt=system_prompt,
                history_messages=history_messages,
                base_url=args.llm_binding_host,
                api_key=args.llm_binding_api_key,
                **kwargs,
            )

        return optimized_openai_codex_model_complete

    def create_optimized_codex_cli_llm_func(args, llm_timeout: int):
        """Create Codex CLI backed LLM function using local authenticated Codex app/CLI."""

        async def optimized_codex_cli_model_complete(
            prompt,
            system_prompt=None,
            history_messages=None,
            keyword_extraction=False,
            **kwargs,
        ) -> str:
            from retriqs.llm.codex_cli import codex_cli_complete_if_cache

            keyword_extraction = kwargs.pop(
                "keyword_extraction", keyword_extraction
            )
            if keyword_extraction:
                kwargs["response_format"] = GPTKeywordExtractionFormat
            if history_messages is None:
                history_messages = []

            kwargs["timeout"] = llm_timeout
            kwargs["working_dir"] = args.working_dir

            return await codex_cli_complete_if_cache(
                args.llm_model,
                prompt,
                system_prompt=system_prompt,
                history_messages=history_messages,
                base_url=args.llm_binding_host,
                api_key=args.llm_binding_api_key,
                **kwargs,
            )

        return optimized_codex_cli_model_complete

    def create_llm_model_func(binding: str):
        """
        Create LLM model function based on binding type.
        Uses optimized functions for OpenAI bindings and lazy import for others.
        """
        try:
            if binding == "lollms":
                from retriqs.llm.lollms import lollms_model_complete

                return lollms_model_complete
            elif binding == "ollama":
                from retriqs.llm.ollama import ollama_model_complete

                return ollama_model_complete
            elif binding == "aws_bedrock":
                return bedrock_model_complete  # Already defined locally
            elif binding == "azure_openai":
                # Use optimized function with pre-processed configuration
                return create_optimized_azure_openai_llm_func(
                    config_cache, args, llm_timeout
                )
            elif binding == "openai_codex":
                return create_optimized_openai_codex_llm_func(
                    config_cache, args, llm_timeout
                )
            elif binding == "gemini":
                return create_optimized_gemini_llm_func(config_cache, args, llm_timeout)
            elif binding == "codex_cli":
                return create_optimized_codex_cli_llm_func(args, llm_timeout)
            else:  # openai and compatible
                # Use optimized function with pre-processed configuration
                return create_optimized_openai_llm_func(config_cache, args, llm_timeout)
        except ImportError as e:
            raise Exception(f"Failed to import {binding} LLM binding: {e}")

    def create_llm_model_kwargs(binding: str, args, llm_timeout: int) -> dict:
        """
        Create LLM model kwargs based on binding type.
        Uses lazy import for binding-specific options.
        """
        if binding in ["lollms", "ollama"]:
            try:
                # from retriqs.llm.binding_options import OllamaLLMOptions
                # TODO:
                options = {}
                options["num_ctx"] = args.ollama_num_ctx
                return {
                    "host": args.llm_binding_host,
                    "timeout": llm_timeout,
                    "options": options,
                    "api_key": args.llm_binding_api_key,
                }
            except ImportError as e:
                raise Exception(f"Failed to import {binding} options: {e}")
        return {}

    llm_timeout = get_env_value("LLM_TIMEOUT", DEFAULT_LLM_TIMEOUT, int)
    embedding_timeout = get_env_value(
        "EMBEDDING_TIMEOUT", DEFAULT_EMBEDDING_TIMEOUT, int
    )

    # 2. Re-create the Config Cache (important for binding options)
    config_cache = LLMConfigCache(args)

    async def bedrock_model_complete(
        prompt,
        system_prompt=None,
        history_messages=None,
        keyword_extraction=False,
        **kwargs,
    ) -> str:
        # Lazy import
        from retriqs.llm.bedrock import bedrock_complete_if_cache

        keyword_extraction = kwargs.pop("keyword_extraction", None)
        if keyword_extraction:
            kwargs["response_format"] = GPTKeywordExtractionFormat
        if history_messages is None:
            history_messages = []

        # Use global temperature for Bedrock
        kwargs["temperature"] = get_env_value("BEDROCK_LLM_TEMPERATURE", 1.0, float)

        return await bedrock_complete_if_cache(
            args.llm_model,
            prompt,
            system_prompt=system_prompt,
            history_messages=history_messages,
            **kwargs,
        )

    def create_optimized_embedding_function(
        config_cache: LLMConfigCache, binding, model, host, api_key, args
    ) -> EmbeddingFunc:
        """
        Create optimized embedding function and return an EmbeddingFunc instance
        with proper max_token_size inheritance from provider defaults.

        This function:
        1. Imports the provider embedding function
        2. Extracts max_token_size and embedding_dim from provider if it's an EmbeddingFunc
        3. Creates an optimized wrapper that calls the underlying function directly (avoiding double-wrapping)
        4. Returns a properly configured EmbeddingFunc instance

        Configuration Rules:
        - When EMBEDDING_MODEL is not set: Uses provider's default model and dimension
          (e.g., jina-embeddings-v4 with 2048 dims, text-embedding-3-small with 1536 dims)
        - When EMBEDDING_MODEL is set to a custom model: User MUST also set EMBEDDING_DIM
          to match the custom model's dimension (e.g., for jina-embeddings-v3, set EMBEDDING_DIM=1024)

        Note: The embedding_dim parameter is automatically injected by EmbeddingFunc wrapper
        when send_dimensions=True (enabled for Jina and Gemini bindings). This wrapper calls
        the underlying provider function directly (.func) to avoid double-wrapping, so we must
        explicitly pass embedding_dim to the provider's underlying function.
        """

        # Step 1: Import provider function and extract default attributes
        provider_func = None
        provider_max_token_size = None
        provider_embedding_dim = None

        try:
            if binding == "openai":
                from retriqs.llm.openai import openai_embed

                provider_func = openai_embed
            elif binding == "ollama":
                from retriqs.llm.ollama import ollama_embed

                provider_func = ollama_embed
            elif binding == "gemini":
                try:
                    from retriqs.llm.gemini import gemini_embed
                except ImportError as error:
                    _raise_missing_gemini_support(error)

                provider_func = gemini_embed
            elif binding == "jina":
                from retriqs.llm.jina import jina_embed

                provider_func = jina_embed
            elif binding == "azure_openai":
                from retriqs.llm.azure_openai import azure_openai_embed

                provider_func = azure_openai_embed
            elif binding == "aws_bedrock":
                from retriqs.llm.bedrock import bedrock_embed

                provider_func = bedrock_embed
            elif binding == "lollms":
                from retriqs.llm.lollms import lollms_embed

                provider_func = lollms_embed

            # Extract attributes if provider is an EmbeddingFunc
            if provider_func and isinstance(provider_func, EmbeddingFunc):
                provider_max_token_size = 8192  # TODO: provider_func.max_token_size
                provider_embedding_dim = provider_func.embedding_dim
                logger.debug(
                    f"Extracted from {binding} provider: "
                    f"max_token_size={provider_max_token_size}, "
                    f"embedding_dim={provider_embedding_dim}"
                )
        except ImportError as e:
            logger.warning(f"Could not import provider function for {binding}: {e}")

        # Step 2: Apply priority (user config > provider default)
        # For max_token_size: explicit env var > provider default > None
        final_max_token_size = args.embedding_token_limit or provider_max_token_size
        # For embedding_dim: user config (always has value) takes priority
        # Only use provider default if user config is explicitly None (which shouldn't happen)
        final_embedding_dim = (
            args.embedding_dim if args.embedding_dim else provider_embedding_dim
        )

        # Step 3: Create optimized embedding function (calls underlying function directly)
        # Note: When model is None, each binding will use its own default model
        async def optimized_embedding_function(texts, embedding_dim=None):
            try:
                if binding == "lollms":
                    from retriqs.llm.lollms import lollms_embed

                    # Get real function, skip EmbeddingFunc wrapper if present
                    actual_func = (
                        lollms_embed.func
                        if isinstance(lollms_embed, EmbeddingFunc)
                        else lollms_embed
                    )
                    # lollms embed_model is not used (server uses configured vectorizer)
                    # Only pass base_url and api_key
                    return await actual_func(texts, base_url=host, api_key=api_key)
                elif binding == "ollama":
                    from retriqs.llm.ollama import ollama_embed

                    # Get real function, skip EmbeddingFunc wrapper if present
                    actual_func = (
                        ollama_embed.func
                        if isinstance(ollama_embed, EmbeddingFunc)
                        else ollama_embed
                    )

                    # # Use pre-processed configuration if available
                    # if config_cache.ollama_embedding_options is not None:
                    #     ollama_options = config_cache.ollama_embedding_options
                    # else:
                    #     from retriqs.llm.binding_options import OllamaEmbeddingOptions

                    #     ollama_options = OllamaEmbeddingOptions.options_dict(args)
                    # from retriqs.llm.binding_options import OllamaLLMOptions
                    # TODO:
                    ollama_options = {}
                    ollama_options["num_ctx"] = 8192
                    # Pass embed_model only if provided, let function use its default (bge-m3:latest)
                    kwargs = {
                        "texts": texts,
                        "host": host,
                        "api_key": api_key,
                        "options": ollama_options,
                    }
                    if model:
                        kwargs["embed_model"] = model
                    return await actual_func(**kwargs)
                elif binding == "azure_openai":
                    from retriqs.llm.azure_openai import azure_openai_embed

                    actual_func = (
                        azure_openai_embed.func
                        if isinstance(azure_openai_embed, EmbeddingFunc)
                        else azure_openai_embed
                    )
                    # Pass model only if provided, let function use its default otherwise
                    kwargs = {"texts": texts, "api_key": api_key}
                    if model:
                        kwargs["model"] = model
                    return await actual_func(**kwargs)
                elif binding == "aws_bedrock":
                    from retriqs.llm.bedrock import bedrock_embed

                    actual_func = (
                        bedrock_embed.func
                        if isinstance(bedrock_embed, EmbeddingFunc)
                        else bedrock_embed
                    )
                    # Pass model only if provided, let function use its default otherwise
                    kwargs = {"texts": texts}
                    if model:
                        kwargs["model"] = model
                    return await actual_func(**kwargs)
                elif binding == "jina":
                    from retriqs.llm.jina import jina_embed

                    actual_func = (
                        jina_embed.func
                        if isinstance(jina_embed, EmbeddingFunc)
                        else jina_embed
                    )
                    # Pass model only if provided, let function use its default (jina-embeddings-v4)
                    kwargs = {
                        "texts": texts,
                        "embedding_dim": embedding_dim,
                        "base_url": host,
                        "api_key": api_key,
                    }
                    if model:
                        kwargs["model"] = model
                    return await actual_func(**kwargs)
                elif binding == "gemini":
                    try:
                        from retriqs.llm.gemini import gemini_embed
                    except ImportError as error:
                        _raise_missing_gemini_support(error)

                    actual_func = (
                        gemini_embed.func
                        if isinstance(gemini_embed, EmbeddingFunc)
                        else gemini_embed
                    )

                    # Use pre-processed configuration if available
                    if config_cache.gemini_embedding_options is not None:
                        gemini_options = config_cache.gemini_embedding_options
                    else:
                        from retriqs.llm.binding_options import GeminiEmbeddingOptions

                        gemini_options = GeminiEmbeddingOptions.options_dict(args)

                    # Pass model only if provided, let function use its default (gemini-embedding-001)
                    kwargs = {
                        "texts": texts,
                        "base_url": host,
                        "api_key": api_key,
                        "embedding_dim": embedding_dim,
                        "task_type": gemini_options.get(
                            "task_type", "RETRIEVAL_DOCUMENT"
                        ),
                    }
                    if model:
                        kwargs["model"] = model
                    return await actual_func(**kwargs)
                else:  # openai and compatible
                    from retriqs.llm.openai import openai_embed

                    actual_func = (
                        openai_embed.func
                        if isinstance(openai_embed, EmbeddingFunc)
                        else openai_embed
                    )
                    # Pass model only if provided, let function use its default (text-embedding-3-small)
                    kwargs = {
                        "texts": texts,
                        "base_url": host,
                        "api_key": api_key,
                        "embedding_dim": embedding_dim,
                    }
                    if model:
                        kwargs["model"] = model
                    return await actual_func(**kwargs)
            except ImportError as e:
                raise Exception(f"Failed to import {binding} embedding: {e}")

        # Step 4: Wrap in EmbeddingFunc and return
        embedding_func_instance = EmbeddingFunc(
            embedding_dim=final_embedding_dim,
            func=optimized_embedding_function,
            max_token_size=final_max_token_size,
            send_dimensions=False,  # Will be set later based on binding requirements
            model_name=model,
        )

        # Log final embedding configuration
        logger.info(
            f"Embedding config: binding={binding} model={model} "
            f"embedding_dim={final_embedding_dim} max_token_size={final_max_token_size}"
        )

        return embedding_func_instance

    # Create embedding function with optimized configuration and max_token_size inheritance
    import inspect

    # Create the EmbeddingFunc instance (now returns complete EmbeddingFunc with max_token_size)
    embedding_func = create_optimized_embedding_function(
        config_cache=config_cache,
        binding=args.embedding_binding,
        model=args.embedding_model,
        host=args.embedding_binding_host,
        api_key=args.embedding_binding_api_key,
        args=args,
    )

    # Get embedding_send_dim from centralized configuration
    embedding_send_dim = args.embedding_send_dim

    # Check if the underlying function signature has embedding_dim parameter
    sig = inspect.signature(embedding_func.func)
    has_embedding_dim_param = "embedding_dim" in sig.parameters

    # Determine send_dimensions value based on binding type
    # Jina and Gemini REQUIRE dimension parameter (forced to True)
    # OpenAI and others: controlled by EMBEDDING_SEND_DIM environment variable
    if args.embedding_binding in ["jina", "gemini"]:
        # Jina and Gemini APIs require dimension parameter - always send it
        send_dimensions = has_embedding_dim_param
        dimension_control = f"forced by {args.embedding_binding.title()} API"
    else:
        # For OpenAI and other bindings, respect EMBEDDING_SEND_DIM setting
        send_dimensions = embedding_send_dim and has_embedding_dim_param
        if send_dimensions or not embedding_send_dim:
            dimension_control = "by env var"
        else:
            dimension_control = "by not hasparam"

    # Set send_dimensions on the EmbeddingFunc instance
    embedding_func.send_dimensions = send_dimensions

    logger.info(
        f"Send embedding dimension: {send_dimensions} {dimension_control} "
        f"(dimensions={embedding_func.embedding_dim}, has_param={has_embedding_dim_param}, "
        f"binding={args.embedding_binding})"
    )

    # Log max_token_size source
    if embedding_func.max_token_size:
        source = (
            "env variable"
            if args.embedding_token_limit
            else f"{args.embedding_binding} provider default"
        )
        logger.info(
            f"Embedding max_token_size: {embedding_func.max_token_size} (from {source})"
        )
    else:
        logger.info(
            "Embedding max_token_size: None (Embedding token limit is disabled)."
        )

    # Configure rerank function based on args.rerank_bindingparameter
    rerank_model_func = None
    if args.rerank_binding != "null":
        from retriqs.rerank import cohere_rerank, jina_rerank, ali_rerank

        # Map rerank binding to corresponding function
        rerank_functions = {
            "cohere": cohere_rerank,
            "jina": jina_rerank,
            "aliyun": ali_rerank,
        }

        # Select the appropriate rerank function based on binding
        selected_rerank_func = rerank_functions.get(args.rerank_binding)
        if not selected_rerank_func:
            logger.error(f"Unsupported rerank binding: {args.rerank_binding}")
            raise ValueError(f"Unsupported rerank binding: {args.rerank_binding}")

        # Get default values from selected_rerank_func if args values are None
        if args.rerank_model is None or args.rerank_binding_host is None:
            sig = inspect.signature(selected_rerank_func)

            # Set default model if args.rerank_model is None
            if args.rerank_model is None and "model" in sig.parameters:
                default_model = sig.parameters["model"].default
                if default_model != inspect.Parameter.empty:
                    args.rerank_model = default_model

            # Set default base_url if args.rerank_binding_host is None
            if args.rerank_binding_host is None and "base_url" in sig.parameters:
                default_base_url = sig.parameters["base_url"].default
                if default_base_url != inspect.Parameter.empty:
                    args.rerank_binding_host = default_base_url

        async def server_rerank_func(
            query: str, documents: list, top_n: int = None, extra_body: dict = None
        ):
            """Server rerank function with configuration from environment variables"""
            # Prepare kwargs for rerank function
            kwargs = {
                "query": query,
                "documents": documents,
                "top_n": top_n,
                "api_key": args.rerank_binding_api_key,
                "model": args.rerank_model,
                "base_url": args.rerank_binding_host,
            }

            # Add Cohere-specific parameters if using cohere binding
            if args.rerank_binding == "cohere":
                # Enable chunking if configured (useful for models with token limits like ColBERT)
                kwargs["enable_chunking"] = (
                    os.getenv("RERANK_ENABLE_CHUNKING", "false").lower() == "true"
                )
                kwargs["max_tokens_per_doc"] = int(
                    os.getenv("RERANK_MAX_TOKENS_PER_DOC", "4096")
                )

            return await selected_rerank_func(**kwargs, extra_body=extra_body)

        rerank_model_func = server_rerank_func
        logger.info(
            f"Reranking is enabled: {args.rerank_model or 'default model'} using {args.rerank_binding} provider"
        )
    else:
        logger.info("Reranking is disabled")

    # Create ollama_server_infos from command line arguments
    from retriqs.api.config import OllamaServerInfos

    ollama_server_infos = OllamaServerInfos(
        name=args.simulated_model_name, tag=args.simulated_model_tag
    )

    logger.info(f"Graph storage: {args.graph_storage}")

    try:
        return LightRAG(
            working_dir=args.working_dir,
            workspace=args.workspace,
            llm_model_func=create_llm_model_func(args.llm_binding),
            llm_model_name=args.llm_model,
            llm_model_max_async=args.max_async,
            summary_max_tokens=args.summary_max_tokens,
            summary_context_size=args.summary_context_size,
            chunk_token_size=int(args.chunk_size),
            chunk_overlap_token_size=int(args.chunk_overlap_size),
            llm_model_kwargs=create_llm_model_kwargs(
                args.llm_binding, args, llm_timeout
            ),
            embedding_func=embedding_func,
            default_llm_timeout=llm_timeout,
            default_embedding_timeout=embedding_timeout,
            kv_storage=args.kv_storage,
            graph_storage=args.graph_storage,
            vector_storage=args.vector_storage,
            doc_status_storage=args.doc_status_storage,
            vector_db_storage_cls_kwargs={
                "cosine_better_than_threshold": args.cosine_threshold
            },
            enable_llm_cache_for_entity_extract=args.enable_llm_cache_for_extract,
            enable_llm_cache=args.enable_llm_cache,
            rerank_model_func=rerank_model_func,
            max_parallel_insert=args.max_parallel_insert,
            max_graph_nodes=args.max_graph_nodes,
            addon_params={
                "language": args.summary_language,
                "entity_types": args.entity_types,
            },
            ollama_server_infos=ollama_server_infos,
        )
    except Exception as e:
        logger.error(f"Failed to initialize LightRAG: {e}")
        raise

def combine_lifespans(*lifespan_funcs):
    """
    Combine multiple FastAPI/Starlette lifespan callables into one.
    Each item must be a callable like: lifespan(app) -> async context manager
    """

    @asynccontextmanager
    async def combined(app: FastAPI):
        async with AsyncExitStack() as stack:
            for lifespan_func in lifespan_funcs:
                if lifespan_func is None:
                    continue
                await stack.enter_async_context(lifespan_func(app))
            yield

    return combined


def create_app(args):
    # 1. Sync DB to args BEFORE building anything
    initialize_db_settings()
    warn_if_legacy_rag_storage_present(logger, args.working_dir)

    rag_manager = RAGManager()

    storages = get_graph_storages()
    failed_storage_ids: list[int] = []

    for storage in storages:
        # Use centralized helper to build storage-specific args
        from retriqs.api.config import build_storage_args

        try:
            instance_args = build_storage_args(storage, args)
            new_instance = build_rag_instance(instance_args)
            rag_manager.set_instance(storage.id, new_instance)
        except Exception as e:
            failed_storage_ids.append(storage.id)
            logger.error(
                f"Skipping storage {storage.id} ({storage.name}) due to initialization failure: {e}"
            )

    if failed_storage_ids:
        logger.warning(
            f"Server startup continued with {len(failed_storage_ids)} skipped storage(s): {failed_storage_ids}"
        )
    # Check frontend build first and get status
    webui_assets_exist, is_frontend_outdated = check_frontend_build()

    # Create unified API version display with warning symbol if frontend is outdated
    api_version_display = (
        f"{__api_version__}⚠️" if is_frontend_outdated else __api_version__
    )

    # Setup logging
    logger.setLevel(args.log_level)
    set_verbose_debug(args.verbose)

    # initial_rag = build_rag_instance(args)
    rag = RAGProxy(None)
    startup_state = {
        "status": "starting",
        "message": "Backend startup has begun.",
        "ready": False,
    }

    # Create ollama_server_infos from command line arguments
    from retriqs.api.config import OllamaServerInfos

    ollama_server_infos = OllamaServerInfos(
        name=args.simulated_model_name, tag=args.simulated_model_tag
    )

    # Verify that bindings are correctly setup
    if args.llm_binding not in [
        "lollms",
        "ollama",
        "openai_codex",
        "codex_cli",
        "openai",
        "azure_openai",
        "aws_bedrock",
        "gemini",
    ]:
        raise Exception("llm binding not supported")

    if args.embedding_binding not in [
        "lollms",
        "ollama",
        "openai",
        "azure_openai",
        "aws_bedrock",
        "jina",
        "gemini",
    ]:
        raise Exception("embedding binding not supported")

    # Set default hosts if not provided
    if args.llm_binding_host is None:
        args.llm_binding_host = get_default_host(args.llm_binding)

    #if args.embedding_binding_host is None:
    args.embedding_binding_host = get_default_host(args.embedding_binding)

    # Add SSL validation
    if args.ssl:
        if not args.ssl_certfile or not args.ssl_keyfile:
            raise Exception(
                "SSL certificate and key files must be provided when SSL is enabled"
            )
        if not os.path.exists(args.ssl_certfile):
            raise Exception(f"SSL certificate file not found: {args.ssl_certfile}")
        if not os.path.exists(args.ssl_keyfile):
            raise Exception(f"SSL key file not found: {args.ssl_keyfile}")

    # Check if API key is provided either through env var or args
    api_key = os.getenv("LIGHTRAG_API_KEY") or args.key

    # Initialize document manager (workspace-specific directories computed dynamically per tenant)
    doc_manager = DocumentManager(args.input_dir)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """Lifespan context manager for startup and shutdown events"""
        # Store background tasks
        app.state.background_tasks = set()
        app.state.startup_state.update(
            {
                "status": "starting",
                "message": "Initializing backend services...",
                "ready": False,
            }
        )

        try:
            # Initialize database connections
            # Note: initialize_storages() now auto-initializes pipeline_status for rag.workspace
            if rag._instance:
                app.state.startup_state["message"] = (
                    "Initializing default backend storage..."
                )
                await rag.initialize_storages()

                # Data migration regardless of storage implementation
                app.state.startup_state["message"] = (
                    "Checking backend data migrations..."
                )
                await rag.check_and_migrate_data()

            # Initialize all tenant RAG instances
            logger.info("Initializing tenant RAG instances...")
            for storage_id, tenant_rag in rag_manager.all_instances():
                try:
                    app.state.startup_state["message"] = (
                        f"Initializing storage instance {storage_id}..."
                    )
                    await tenant_rag.initialize_storages()
                    logger.info(f"Initialized tenant RAG instance: {storage_id}")
                except Exception as e:
                    logger.error(
                        f"Failed to initialize tenant RAG instance {storage_id}: {e}"
                    )

            app.state.startup_state.update(
                {
                    "status": "healthy",
                    "message": "Backend startup completed.",
                    "ready": True,
                }
            )
            ASCIIColors.green("\nServer is ready to accept connections! 🚀\n")
            ASCIIColors.green("\nGo to http://localhost:9621 \n")
            yield

        except Exception as e:
            app.state.startup_state.update(
                {
                    "status": "error",
                    "message": f"Backend startup failed: {e}",
                    "ready": False,
                }
            )
            raise
        finally:
            app.state.startup_state.update(
                {
                    "status": "stopping",
                    "message": "Backend is shutting down...",
                    "ready": False,
                }
            )
            # Finalize all tenant RAG instances
            logger.info("Finalizing tenant RAG instances...")
            for storage_id, tenant_rag in rag_manager.all_instances():
                try:
                    await tenant_rag.finalize_storages()
                    logger.info(f"Finalized tenant RAG instance: {storage_id}")
                except Exception as e:
                    logger.error(
                        f"Failed to finalize tenant RAG instance {storage_id}: {e}"
                    )

            # Clean up database connections
            if rag._instance:
                await rag.finalize_storages()

            if "LIGHTRAG_GUNICORN_MODE" not in os.environ:
                # Only perform cleanup in Uvicorn single-process mode
                logger.debug("Unvicorn Mode: finalizing shared storage...")
                finalize_share_data()
            else:
                # In Gunicorn mode with preload_app=True, cleanup is handled by on_exit hooks
                logger.debug(
                    "Gunicorn Mode: postpone shared storage finalization to master process"
                )

    # Initialize FastAPI
    base_description = (
        "Providing API for LightRAG core, Web UI and Ollama Model Emulation"
    )
    swagger_description = (
        base_description
        + (" (API-Key Enabled)" if api_key else "")
        + "\n\n[View ReDoc documentation](/redoc)"
    )


    # Create explicit MCP app before creating the FastAPI parent app,
    # so we can combine its lifespan with the main backend lifespan.
    mcp_http_app = None
    combined_app_lifespan = lifespan

    try:
        mcp_http_app = create_mcp_server(rag_manager)
        combined_app_lifespan = combine_lifespans(lifespan, mcp_http_app.lifespan)
        logger.info("Created MCP server and combined its lifespan with the backend lifespan")
    except Exception as e:
        logger.error(f"Failed to create MCP server: {e}")
        mcp_http_app = None
        combined_app_lifespan = lifespan


    app_kwargs = {
        "title": "LightRAG Server API",
        "description": swagger_description,
        "version": __api_version__,
        "openapi_url": "/openapi.json",  # Explicitly set OpenAPI schema URL
        "docs_url": None,  # Disable default docs, we'll create custom endpoint
        "redoc_url": "/redoc",  # Explicitly set redoc URL
        "lifespan": combined_app_lifespan,
    }

    # Configure Swagger UI parameters
    # Enable persistAuthorization and tryItOutEnabled for better user experience
    app_kwargs["swagger_ui_parameters"] = {
        "persistAuthorization": True,
        "tryItOutEnabled": True,
    }

    # Create MCP server BEFORE FastAPI to get its lifespan
    # mcp_http_app = create_mcp_server(rag_manager)

    # Combine the existing lifespan with MCP's lifespan
    # combined_lifespan = combine_lifespans(lifespan, mcp_http_app.lifespan)

    # app_kwargs["lifespan"] = combined_lifespan
    # mcp = FastMCP("My Server")

    # @mcp.tool
    # def process_data(input: str) -> str:
    #     """Process data on the server"""
    #     return f"Processed: {input}"

    # mcp_asgi_app = mcp.sse_app()

    app = FastAPI(**app_kwargs)
    app.add_middleware(MCPMountPathMiddleware)

    if mcp_http_app is not None:
        app.mount("/mcp", mcp_http_app)
        logger.info("Mounted MCP server at /mcp")
    # Mount the MCP server (lifespan already combined above)
    # try:
    #     app.mount("/mcp-api", mcp_http_app)
    #     logger.info("Mounted MCP server at /mcp-api/")
    # except Exception as e:
    #     logger.error(f"Failed to mount MCP server: {e}")
    # app.mount("/mcp", mcp.http_app())

    tenant_router = APIRouter(
        prefix="/storage/{storage_id}", dependencies=[Depends(get_rag_by_id)]
    )

    app.state.args = args
    app.state.rag_proxy = rag
    app.state.rag_manager = rag_manager
    app.state.startup_state = startup_state

    # Add custom validation error handler for /query/data endpoint
    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ):
        # Check if this is a request to /query/data endpoint
        if request.url.path.endswith("/query/data"):
            # Extract error details
            error_details = []
            for error in exc.errors():
                field_path = " -> ".join(str(loc) for loc in error["loc"])
                error_details.append(f"{field_path}: {error['msg']}")

            error_message = "; ".join(error_details)

            # Return in the expected format for /query/data
            return JSONResponse(
                status_code=400,
                content={
                    "status": "failure",
                    "message": f"Validation error: {error_message}",
                    "data": {},
                    "metadata": {},
                },
            )
        else:
            # For other endpoints, return the default FastAPI validation error
            return JSONResponse(status_code=422, content={"detail": exc.errors()})

    def get_cors_origins():
        """Get allowed origins from global_args
        Returns a list of allowed origins, defaults to ["*"] if not set
        """
        origins_str = global_args.cors_origins
        if origins_str == "*":
            return ["*"]
        return [origin.strip() for origin in origins_str.split(",")]

    # Add CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=get_cors_origins(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


    # Create combined auth dependency for all endpoints
    combined_auth = get_combined_auth_dependency(api_key)

    def get_workspace_from_request(request: Request) -> str | None:
        """
        Extract workspace from HTTP request header or use default.

        This enables multi-workspace API support by checking the custom
        'LIGHTRAG-WORKSPACE' header. If not present, falls back to the
        server's default workspace configuration.

        Args:
            request: FastAPI Request object

        Returns:
            Workspace identifier (may be empty string for global namespace)
        """
        # Check custom header first
        workspace = request.headers.get("LIGHTRAG-WORKSPACE", "").strip()

        if not workspace:
            workspace = None

        return workspace

    # Create working directory if it doesn't exist
    Path(args.working_dir).mkdir(parents=True, exist_ok=True)

    # Add default routes (without storage_id) FIRST - these must be registered before tenant routes
    # This provides backward compatibility for existing frontend code
    # def get_default_rag():
    #     """Get the first available RAG instance as default"""
    #     # Try to get the first storage from the manager
    #     instances = list(rag_manager.all_instances())
    #     if instances:
    #         storage_id, instance = instances[0]
    #         logger.debug(f"Using default storage_id={storage_id} for non-tenant route")
    #         return instance
    #     # Fallback to the original rag proxy if no instances in manager
    #     logger.warning("No instances in RAGManager, falling back to rag proxy")
    #     return rag

    # # Add default document routes
    # app.include_router(
    #     create_document_routes(
    #         rag_dependency=get_default_rag,
    #         doc_manager=doc_manager,
    #         api_key=api_key,
    #     )
    # )
    # Add default query routes
    # app.include_router(create_query_routes(rag_dependency=get_default_rag, api_key=api_key))
    # Add default graph routes
    # app.include_router(create_graph_routes(rag_dependency=get_default_rag, api_key=api_key))

    # Now add tenant-scoped routes (with storage_id in path)
    tenant_router.include_router(
        create_document_routes(
            rag_dependency=get_rag_by_id, doc_manager=doc_manager, api_key=api_key
        )
    )
    tenant_router.include_router(
        create_query_routes(rag_dependency=get_rag_by_id, api_key=api_key)
    )
    tenant_router.include_router(
        create_graph_routes(rag_dependency=get_rag_by_id, api_key=api_key)
    )
    app.include_router(tenant_router)

    from retriqs.api.routers import settings_router

    app.include_router(settings_router)
    # Add Ollama API routes
    ollama_api = OllamaAPI(
        rag, ollama_server_infos=ollama_server_infos, top_k=args.top_k, api_key=api_key
    )
    app.include_router(ollama_api.router, prefix="/api")

    # Custom Swagger UI endpoint for offline support
    @app.get("/docs", include_in_schema=False)
    async def custom_swagger_ui_html():
        """Custom Swagger UI HTML with local static files"""
        return get_swagger_ui_html(
            openapi_url=app.openapi_url,
            title=app.title + " - Swagger UI",
            oauth2_redirect_url="/docs/oauth2-redirect",
            swagger_js_url="/static/swagger-ui/swagger-ui-bundle.js",
            swagger_css_url="/static/swagger-ui/swagger-ui.css",
            swagger_favicon_url="/static/swagger-ui/favicon-32x32.png",
            swagger_ui_parameters=app.swagger_ui_parameters,
        )

    @app.get("/docs/oauth2-redirect", include_in_schema=False)
    async def swagger_ui_redirect():
        """OAuth2 redirect for Swagger UI"""
        return get_swagger_ui_oauth2_redirect_html()

    @app.get("/")
    async def redirect_to_webui():
        """Redirect root path based on WebUI availability"""
        if webui_assets_exist:
            return RedirectResponse(url="/documents")
        else:
            return RedirectResponse(url="/docs")

    @app.get("/auth-status")
    async def get_auth_status():
        """Get authentication status and guest token if auth is not configured"""

        if not auth_handler.accounts:
            # Authentication not configured, return guest token
            guest_token = auth_handler.create_token(
                username="guest", role="guest", metadata={"auth_mode": "disabled"}
            )
            return {
                "auth_configured": False,
                "access_token": guest_token,
                "token_type": "bearer",
                "auth_mode": "disabled",
                "message": "Authentication is disabled. Using guest access.",
                "core_version": core_version,
                "api_version": api_version_display,
                "webui_title": webui_title,
                "webui_description": webui_description,
            }

        return {
            "auth_configured": True,
            "auth_mode": "enabled",
            "core_version": core_version,
            "api_version": api_version_display,
            "webui_title": webui_title,
            "webui_description": webui_description,
        }

    @app.post("/login")
    async def login(form_data: OAuth2PasswordRequestForm = Depends()):
        if not auth_handler.accounts:
            # Authentication not configured, return guest token
            guest_token = auth_handler.create_token(
                username="guest", role="guest", metadata={"auth_mode": "disabled"}
            )
            return {
                "access_token": guest_token,
                "token_type": "bearer",
                "auth_mode": "disabled",
                "message": "Authentication is disabled. Using guest access.",
                "core_version": core_version,
                "api_version": api_version_display,
                "webui_title": webui_title,
                "webui_description": webui_description,
            }
        username = form_data.username
        if auth_handler.accounts.get(username) != form_data.password:
            raise HTTPException(status_code=401, detail="Incorrect credentials")

        # Regular user login
        user_token = auth_handler.create_token(
            username=username, role="user", metadata={"auth_mode": "enabled"}
        )
        return {
            "access_token": user_token,
            "token_type": "bearer",
            "auth_mode": "enabled",
            "core_version": core_version,
            "api_version": api_version_display,
            "webui_title": webui_title,
            "webui_description": webui_description,
        }

    @app.get(
        "/health",
        dependencies=[Depends(combined_auth)],
        summary="Get system health and configuration status",
        description="Returns comprehensive system status including WebUI availability, configuration, and operational metrics",
        response_description="System health status with configuration details",
        responses={
            200: {
                "description": "Successful response with system status",
                "content": {
                    "application/json": {
                        "example": {
                            "status": "healthy",
                            "webui_available": True,
                            "working_directory": "/path/to/working/dir",
                            "input_directory": "/path/to/input/dir",
                            "configuration": {
                                "llm_binding": "openai",
                                "llm_model": "gpt-4",
                                "embedding_binding": "openai",
                                "embedding_model": "text-embedding-ada-002",
                                "workspace": "default",
                            },
                            "auth_mode": "enabled",
                            "pipeline_busy": False,
                            "core_version": "0.0.1",
                            "api_version": "0.0.1",
                        }
                    }
                },
            }
        },
    )
    async def get_status(request: Request):
        """Get current system status including WebUI availability"""
        try:
            startup = getattr(
                app.state,
                "startup_state",
                {"status": "starting", "message": "Backend is starting.", "ready": False},
            )
            workspace = get_workspace_from_request(request)
            default_workspace = get_default_workspace()
            if workspace is None:
                workspace = default_workspace
            pipeline_busy = False
            current_job = None
            reembedding_busy = False
            pipeline_latest_message = None
            pipeline_status_error = None

            if startup.get("ready"):
                try:
                    pipeline_status = await get_namespace_data(
                        "pipeline_status", workspace=workspace
                    )
                    pipeline_busy = pipeline_status.get("busy", False)
                    current_job = pipeline_status.get("current_job")
                    reembedding_busy = pipeline_status.get("reembedding_busy", False)
                    pipeline_latest_message = pipeline_status.get("latest_message")
                except Exception as pipeline_error:
                    pipeline_status_error = str(pipeline_error)
                    logger.warning(
                        "Health endpoint could not read pipeline status for workspace %s: %s",
                        workspace,
                        pipeline_error,
                    )

            if not auth_configured:
                auth_mode = "disabled"
            else:
                auth_mode = "enabled"

            # Cleanup expired keyed locks and get status
            keyed_lock_info = cleanup_keyed_lock()

            response_payload = {
                "status": startup.get("status", "starting"),
                "ready": bool(startup.get("ready")),
                "message": startup.get("message"),
                "webui_available": webui_assets_exist,
                "working_directory": str(args.working_dir),
                "input_directory": str(args.input_dir),
                "configuration": {
                    # LLM configuration binding/host address (if applicable)/model (if applicable)
                    "llm_binding": args.llm_binding,
                    "llm_binding_host": args.llm_binding_host,
                    "llm_model": args.llm_model,
                    # embedding model configuration binding/host address (if applicable)/model (if applicable)
                    "embedding_binding": args.embedding_binding,
                    "embedding_binding_host": args.embedding_binding_host,
                    "embedding_model": args.embedding_model,
                    "summary_max_tokens": args.summary_max_tokens,
                    "summary_context_size": args.summary_context_size,
                    "kv_storage": args.kv_storage,
                    "doc_status_storage": args.doc_status_storage,
                    "graph_storage": args.graph_storage,
                    "vector_storage": args.vector_storage,
                    "enable_llm_cache_for_extract": args.enable_llm_cache_for_extract,
                    "enable_llm_cache": args.enable_llm_cache,
                    "workspace": default_workspace,
                    "max_graph_nodes": args.max_graph_nodes,
                    # Rerank configuration
                    "enable_rerank": "logging_removed",
                    "rerank_binding": args.rerank_binding,
                    "rerank_model": "logging_removed",
                    "rerank_binding_host": args.rerank_binding_host,
                },
                "auth_mode": auth_mode,
                "pipeline_busy": pipeline_busy,
                "current_job": current_job,
                "reembedding_busy": reembedding_busy,
                "pipeline_latest_message": pipeline_latest_message,
                "keyed_locks": keyed_lock_info,
                "storage_count": len(list(rag_manager.all_instances())),
                "failed_storage_ids": failed_storage_ids,
                "core_version": core_version,
                "api_version": api_version_display,
                "webui_title": webui_title,
                "webui_description": webui_description,
            }

            if pipeline_status_error:
                response_payload["pipeline_status_error"] = pipeline_status_error

            return response_payload
        except Exception as e:
            logger.error(f"Error getting health status: {str(e)}")
            return {
                "status": "error",
                "ready": False,
                "message": str(e),
                "webui_available": webui_assets_exist,
                "working_directory": str(args.working_dir),
                "input_directory": str(args.input_dir),
                "configuration": {
                    "llm_binding": args.llm_binding,
                    "llm_binding_host": args.llm_binding_host,
                    "llm_model": args.llm_model,
                    "embedding_binding": args.embedding_binding,
                    "embedding_binding_host": args.embedding_binding_host,
                    "embedding_model": args.embedding_model,
                    "summary_max_tokens": args.summary_max_tokens,
                    "summary_context_size": args.summary_context_size,
                    "kv_storage": args.kv_storage,
                    "doc_status_storage": args.doc_status_storage,
                    "graph_storage": args.graph_storage,
                    "vector_storage": args.vector_storage,
                    "enable_llm_cache_for_extract": args.enable_llm_cache_for_extract,
                    "enable_llm_cache": args.enable_llm_cache,
                    "workspace": get_default_workspace(),
                    "max_graph_nodes": args.max_graph_nodes,
                    "enable_rerank": "logging_removed",
                    "rerank_binding": args.rerank_binding,
                    "rerank_model": "logging_removed",
                    "rerank_binding_host": args.rerank_binding_host,
                },
                "auth_mode": "enabled" if auth_configured else "disabled",
                "pipeline_busy": False,
                "current_job": None,
                "reembedding_busy": False,
                "pipeline_latest_message": None,
                "keyed_locks": cleanup_keyed_lock(),
                "storage_count": len(list(rag_manager.all_instances())),
                "failed_storage_ids": failed_storage_ids,
                "core_version": core_version,
                "api_version": api_version_display,
                "webui_title": webui_title,
                "webui_description": webui_description,
            }

    # Custom StaticFiles class for smart caching
    class SmartStaticFiles(StaticFiles):  # Renamed from NoCacheStaticFiles
        async def get_response(self, path: str, scope):
            response = await super().get_response(path, scope)

            is_html = path.endswith(".html") or response.media_type == "text/html"

            if is_html:
                response.headers["Cache-Control"] = (
                    "no-cache, no-store, must-revalidate"
                )
                response.headers["Pragma"] = "no-cache"
                response.headers["Expires"] = "0"
            elif (
                "/assets/" in path
            ):  # Assets (JS, CSS, images, fonts) generated by Vite with hash in filename
                response.headers["Cache-Control"] = (
                    "public, max-age=31536000, immutable"
                )
            # Add other rules here if needed for non-HTML, non-asset files

            # Ensure correct Content-Type
            if path.endswith(".js"):
                response.headers["Content-Type"] = "application/javascript"
            elif path.endswith(".css"):
                response.headers["Content-Type"] = "text/css"

            return response

    # Mount Swagger UI static files for offline support
    swagger_static_dir = Path(__file__).parent / "static" / "swagger-ui"
    if swagger_static_dir.exists():
        app.mount(
            "/static/swagger-ui",
            StaticFiles(directory=swagger_static_dir),
            name="swagger-ui-static",
        )

    # Conditionally mount WebUI only if assets exist
    if webui_assets_exist:
        static_dir = Path(__file__).parent / "webui"
        static_dir.mkdir(exist_ok=True)

        # Mount the WebUI assets at the root (will only serve existing files)
        app.mount(
            "/",
            SmartStaticFiles(directory=static_dir, html=True, check_dir=True),
            name="webui",
        )
        logger.info("WebUI assets mounted at /")

        # Redirect /webui for backward compatibility
        @app.get("/webui/{path:path}")
        @app.get("/webui")
        async def webui_redirect_to_root(path: str = ""):
            return RedirectResponse(url=f"/{path}")

        # Fallback for SPA routing: serve index.html for unknown frontend paths
        @app.exception_handler(404)
        async def spa_fallback(request: Request, exc: HTTPException):
            api_prefixes = (
                "/api",
                "/storage",
                "/documents/",
                "/query",
                "/graph",
                "/health",
                "/auth-status",
                "/login",
                "/openapi.json",
                "/docs",
                "/redoc",
                "/mcp",
            )
            if request.url.path.startswith(api_prefixes):
                return JSONResponse(status_code=404, content={"detail": "Not Found0"})

            accept_header = (request.headers.get("accept") or "").lower()
            if "text/html" not in accept_header:
                return JSONResponse(status_code=404, content={"detail": "Not Found1"})

            index_path = static_dir / "index.html"
            if index_path.exists():
                return FileResponse(index_path)
            return JSONResponse(status_code=404, content={"detail": "Not Found2"})
    else:
        logger.info("WebUI assets not available, WebUI not mounted")

        @app.get("/")
        async def root_redirect_to_docs():
            return RedirectResponse(url="/docs")

    return app


def get_application(args=None):
    """Factory function for creating the FastAPI application"""
    if args is None:
        args = global_args
    return create_app(args)


def configure_logging():
    """Configure logging for uvicorn startup"""

    # Reset any existing handlers to ensure clean configuration
    for logger_name in ["uvicorn", "uvicorn.access", "uvicorn.error", "lightrag"]:
        logger = logging.getLogger(logger_name)
        logger.handlers = []
        logger.filters = []

    log_file_path = resolve_log_file_path(DEFAULT_LOG_FILENAME)

    print(f"Retris log file: {log_file_path}\n")
    os.makedirs(os.path.dirname(log_file_path), exist_ok=True)

    # Get log file max size and backup count from environment variables
    log_max_bytes = get_env_value("LOG_MAX_BYTES", DEFAULT_LOG_MAX_BYTES, int)
    log_backup_count = get_env_value("LOG_BACKUP_COUNT", DEFAULT_LOG_BACKUP_COUNT, int)

    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "default": {
                    "format": "%(levelname)s: %(message)s",
                },
                "detailed": {
                    "format": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
                },
            },
            "handlers": {
                "console": {
                    "formatter": "default",
                    "class": "logging.StreamHandler",
                    "stream": "ext://sys.stderr",
                },
                "file": {
                    "formatter": "detailed",
                    "class": "logging.handlers.RotatingFileHandler",
                    "filename": log_file_path,
                    "maxBytes": log_max_bytes,
                    "backupCount": log_backup_count,
                    "encoding": "utf-8",
                },
            },
            "loggers": {
                # Configure all uvicorn related loggers
                "uvicorn": {
                    "handlers": ["console", "file"],
                    "level": "INFO",
                    "propagate": False,
                },
                "uvicorn.access": {
                    "handlers": ["console", "file"],
                    "level": "INFO",
                    "propagate": False,
                    "filters": ["path_filter"],
                },
                "uvicorn.error": {
                    "handlers": ["console", "file"],
                    "level": "INFO",
                    "propagate": False,
                },
                "lightrag": {
                    "handlers": ["console", "file"],
                    "level": "INFO",
                    "propagate": False,
                    "filters": ["path_filter"],
                },
            },
            "filters": {
                "path_filter": {
                    "()": "retriqs.utils.LightragPathFilter",
                },
            },
        }
    )


def check_and_install_dependencies():
    """Check and install required dependencies"""
    required_packages = [
        "uvicorn",
        "tiktoken",
        "fastapi",
        # Add other required packages here
    ]

    for package in required_packages:
        if not pm.is_installed(package):
            print(f"Installing {package}...")
            pm.install(package)
            print(f"{package} installed successfully")


def main():
    # Explicitly initialize configuration for clarity
    # (The proxy will auto-initialize anyway, but this makes intent clear)
    from .config import initialize_config

    initialize_config()

    from retriqs.api.database.settings_manager import initialize_db_settings
    from retriqs.utils_ollama_fix import ensure_ollama_flash_attention_fix

    initialize_db_settings()
    try:
        ensure_ollama_flash_attention_fix(global_args)
    except Exception as e:
        logger.warning(
            f"Ollama startup check failed, continuing without local Ollama auto-fix: {e}"
        )

    # Check if running under Gunicorn
    if "GUNICORN_CMD_ARGS" in os.environ:
        # If started with Gunicorn, return directly as Gunicorn will call get_application
        print("Running under Gunicorn - worker management handled by Gunicorn")
        return

    # Check and install dependencies
    check_and_install_dependencies()

    from multiprocessing import freeze_support

    freeze_support()

    # Configure logging before parsing args
    configure_logging()
    update_uvicorn_mode_config()
    # display_splash_screen(global_args)

    # Note: Signal handlers are NOT registered here because:
    # - Uvicorn has built-in signal handling that properly calls lifespan shutdown
    # - Custom signal handlers can interfere with uvicorn's graceful shutdown
    # - Cleanup is handled by the lifespan context manager's finally block

    # Create application instance directly instead of using factory function
    app = create_app(global_args)


    # Start Uvicorn in single process mode
    uvicorn_config = {
        "app": app,  # Pass application instance directly instead of string path
        "host": global_args.host,
        "port": global_args.port,
        "log_config": None,  # Disable default config
    }

    if global_args.ssl:
        uvicorn_config.update(
            {
                "ssl_certfile": global_args.ssl_certfile,
                "ssl_keyfile": global_args.ssl_keyfile,
            }
        )

    print(
        f"Starting Uvicorn server in single-process mode on {global_args.host}:{global_args.port}"
    )
    uvicorn.run(**uvicorn_config)


if __name__ == "__main__":
    main()
