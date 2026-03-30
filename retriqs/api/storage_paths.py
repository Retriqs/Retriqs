"""Centralized path resolution for API persistent storage."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path


APP_DIR_NAME = "Retriqs"
RAG_DIR_NAME = "rag_storage"
SETTINGS_DB_NAME = "settings.db"


@dataclass(frozen=True)
class StoragePaths:
    data_root: str
    rag_root: str
    settings_db_path: str


def is_frozen_runtime() -> bool:
    # PyInstaller compatibility
    if bool(getattr(sys, "frozen", False)) or hasattr(sys, "_MEIPASS"):
        return True

    # Nuitka compatibility (compiled module marker / onefile env marker)
    if "__compiled__" in globals():
        return True
    if os.getenv("NUITKA_ONEFILE_PARENT") is not None:
        return True

    return False


def is_windows() -> bool:
    return os.name == "nt"


def is_macos() -> bool:
    return sys.platform == "darwin"


def _default_localappdata_root() -> str:
    base = os.getenv("LOCALAPPDATA")
    if not base:
        base = str(Path.home() / "AppData" / "Local")
    return os.path.join(base, APP_DIR_NAME)


def _default_macos_appdata_root() -> str:
    return str(Path.home() / "Library" / "Application Support" / APP_DIR_NAME)


def _default_frozen_data_root() -> str | None:
    if is_windows():
        return _default_localappdata_root()
    if is_macos():
        return _default_macos_appdata_root()
    return None


def resolve_log_file_path(log_filename: str) -> str:
    """
    Resolve the runtime log file path.

    Priority:
    1) LOG_DIR environment variable when set
    2) %LOCALAPPDATA%\\Retriqs for frozen Windows runtime
    3) ~/Library/Application Support/Retriqs for frozen macOS runtime
    4) Current working directory
    """
    log_dir = os.getenv("LOG_DIR", "").strip()
    if log_dir:
        return os.path.abspath(os.path.join(log_dir, log_filename))

    if is_frozen_runtime():
        frozen_root = _default_frozen_data_root()
        if frozen_root:
            return os.path.abspath(os.path.join(frozen_root, log_filename))

    return os.path.abspath(os.path.join(os.getcwd(), log_filename))


def default_rag_root() -> str:
    if is_frozen_runtime():
        frozen_root = _default_frozen_data_root()
        if frozen_root:
            return os.path.abspath(os.path.join(frozen_root, RAG_DIR_NAME))
    return os.path.abspath(f".{os.sep}{RAG_DIR_NAME}")


def resolve_rag_root(working_dir_override: str | None = None) -> str:
    if working_dir_override and str(working_dir_override).strip():
        return os.path.abspath(working_dir_override)

    env_working_dir = os.getenv("WORKING_DIR", "").strip()
    if env_working_dir:
        return os.path.abspath(env_working_dir)

    return default_rag_root()


def resolve_storage_paths(working_dir_override: str | None = None) -> StoragePaths:
    rag_root = resolve_rag_root(working_dir_override)
    data_root = os.path.dirname(rag_root)
    return StoragePaths(
        data_root=data_root,
        rag_root=rag_root,
        settings_db_path=os.path.join(rag_root, SETTINGS_DB_NAME),
    )


def legacy_rag_root_from_cwd() -> str:
    return os.path.abspath(f".{os.sep}{RAG_DIR_NAME}")


def warn_if_legacy_rag_storage_present(logger, active_rag_root: str) -> None:
    legacy_root = legacy_rag_root_from_cwd()
    active_abs = os.path.abspath(active_rag_root)
    if legacy_root == active_abs:
        return
    if not os.path.isdir(legacy_root):
        return

    logger.warning(
        "Detected legacy rag_storage at '%s', but active storage root is '%s'. "
        "Automatic migration is disabled. To migrate manually, stop the app, copy files "
        "from legacy rag_storage into the active storage root, then restart.",
        legacy_root,
        active_abs,
    )
