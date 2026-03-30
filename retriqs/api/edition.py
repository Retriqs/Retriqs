import os
from typing import Any, Mapping

UPGRADE_URL = "https://retriqs.com/"
FREE_EDITION_MAX_STORAGES = 1

RESTRICTED_STORAGE_PROVIDERS = frozenset(
    {
        "Neo4JStorage",
        "MilvusVectorDBStorage",
        "RedisKVStorage",
        "RedisDocStatusStorage",
    }
)

DEV_MODE_VALUES = {"dev", "development", "local", "test"}


def is_development_mode() -> bool:
    """Detect development mode. Defaults to production behavior when unset."""
    if os.getenv("UVICORN_RELOAD", "").strip().lower() == "true":
        return True

    mode = (
        os.getenv("LIGHTRAG_EDITION_MODE")
        or os.getenv("LIGHTRAG_ENV")
        or os.getenv("ENVIRONMENT")
        or os.getenv("APP_ENV")
        or os.getenv("PYTHON_ENV")
        or ""
    ).strip().lower()
    return mode in DEV_MODE_VALUES


def is_free_edition_restricted() -> bool:
    """Hardcoded free-edition gates (future: replace with license/provider check)."""
    return not is_development_mode()


def can_create_storage(existing_storage_count: int) -> bool:
    if not is_free_edition_restricted():
        return True
    return existing_storage_count < FREE_EDITION_MAX_STORAGES


def get_restricted_provider_fields(
    storage_settings: Mapping[str, Any],
) -> list[str]:
    if not is_free_edition_restricted():
        return []

    restricted_fields: list[str] = []
    for field, value in storage_settings.items():
        if isinstance(value, str) and value in RESTRICTED_STORAGE_PROVIDERS:
            restricted_fields.append(field)
    return restricted_fields
