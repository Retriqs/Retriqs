from sqlalchemy import (
    Boolean,
    JSON,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    func,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Mapped, mapped_column, relationship
from typing import Any, List
import os
import threading
from pathlib import Path
from retriqs.api.storage_paths import resolve_storage_paths

Base = declarative_base()

class AppSetting(Base):
    __tablename__ = "app_settings"
    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(50))
    value: Mapped[str] = mapped_column(String(1024), nullable=True)
    storage_id: Mapped[int] = mapped_column(ForeignKey("graph_storages.id"))
    storage: Mapped["GraphStorage"] = relationship(back_populates="storage_settings")


class GraphStorage(Base):
    __tablename__ = "graph_storages"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50))
    work_dir: Mapped[str] = mapped_column(String(1024))
    storage_settings: Mapped[List["AppSetting"]] = relationship(
        back_populates="storage", cascade="all, delete-orphan"
    )
    retrieval_chats: Mapped[List["RetrievalChat"]] = relationship(
        back_populates="storage", cascade="all, delete-orphan"
    )


class RetrievalChat(Base):
    __tablename__ = "retrieval_chats"

    id: Mapped[int] = mapped_column(primary_key=True)
    storage_id: Mapped[int] = mapped_column(
        ForeignKey("graph_storages.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_pinned: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    created_at: Mapped[Any] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[Any] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    storage: Mapped["GraphStorage"] = relationship(back_populates="retrieval_chats")
    messages: Mapped[List["RetrievalChatMessage"]] = relationship(
        back_populates="chat", cascade="all, delete-orphan"
    )


class RetrievalChatMessage(Base):
    __tablename__ = "retrieval_chat_messages"
    __table_args__ = (UniqueConstraint("chat_id", "sequence_no"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    chat_id: Mapped[int] = mapped_column(
        ForeignKey("retrieval_chats.id", ondelete="CASCADE"), index=True
    )
    sequence_no: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[Any] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    chat: Mapped["RetrievalChat"] = relationship(back_populates="messages")
    retrieval_snapshot: Mapped["RetrievalSnapshot"] = relationship(
        back_populates="message",
        cascade="all, delete-orphan",
        uselist=False,
    )


class RetrievalSnapshot(Base):
    __tablename__ = "retrieval_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    message_id: Mapped[int] = mapped_column(
        ForeignKey("retrieval_chat_messages.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )
    mode: Mapped[str | None] = mapped_column(String(20), nullable=True)
    data: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(
        "metadata", JSON, nullable=True
    )
    references: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    trace: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[Any] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    message: Mapped["RetrievalChatMessage"] = relationship(
        back_populates="retrieval_snapshot"
    )


# Save the settings DB inside the resolved rag storage root.
RESOLVED_PATHS = resolve_storage_paths()
RAG_ROOT = RESOLVED_PATHS.rag_root
DB_PATH = RESOLVED_PATHS.settings_db_path
os.makedirs(RAG_ROOT, exist_ok=True)

engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
_db_init_lock = threading.Lock()
_db_initialized = False


def _sqlite_url_from_path(db_path: str) -> str:
    return f"sqlite:///{Path(db_path).resolve().as_posix()}"


def _ensure_sqlite_chat_schema_compatibility() -> None:
    """Patch missing chat-history schema pieces for legacy SQLite databases.

    Alembic may be unavailable in some packaged runtimes. In that case
    `create_all()` creates missing tables but does not alter existing ones.
    This helper keeps existing settings/storage data and incrementally adds
    chat-specific schema pieces when absent.
    """
    with engine.begin() as conn:
        def table_exists(table_name: str) -> bool:
            row = conn.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=:name",
                {"name": table_name},
            ).fetchone()
            return row is not None

        # Ensure retrieval_chats exists with current columns.
        if not table_exists("retrieval_chats"):
            conn.exec_driver_sql(
                """
                CREATE TABLE retrieval_chats (
                    id INTEGER NOT NULL PRIMARY KEY,
                    storage_id INTEGER NOT NULL,
                    title VARCHAR(255),
                    is_pinned BOOLEAN NOT NULL DEFAULT 0,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(storage_id) REFERENCES graph_storages (id) ON DELETE CASCADE
                )
                """
            )
            conn.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS ix_retrieval_chats_storage_id ON retrieval_chats (storage_id)"
            )
        else:
            chat_columns = {
                row[1]
                for row in conn.exec_driver_sql(
                    "PRAGMA table_info('retrieval_chats')"
                ).fetchall()
            }
            if "is_pinned" not in chat_columns:
                conn.exec_driver_sql(
                    "ALTER TABLE retrieval_chats ADD COLUMN is_pinned BOOLEAN NOT NULL DEFAULT 0"
                )

        # Ensure retrieval_chat_messages exists.
        if not table_exists("retrieval_chat_messages"):
            conn.exec_driver_sql(
                """
                CREATE TABLE retrieval_chat_messages (
                    id INTEGER NOT NULL PRIMARY KEY,
                    chat_id INTEGER NOT NULL,
                    sequence_no INTEGER NOT NULL,
                    role VARCHAR(20) NOT NULL,
                    content TEXT NOT NULL,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    CHECK (role IN ('user', 'assistant', 'system')),
                    FOREIGN KEY(chat_id) REFERENCES retrieval_chats (id) ON DELETE CASCADE,
                    UNIQUE (chat_id, sequence_no)
                )
                """
            )
            conn.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS ix_retrieval_chat_messages_chat_id ON retrieval_chat_messages (chat_id)"
            )

        # Ensure retrieval_snapshots exists.
        if not table_exists("retrieval_snapshots"):
            conn.exec_driver_sql(
                """
                CREATE TABLE retrieval_snapshots (
                    id INTEGER NOT NULL PRIMARY KEY,
                    message_id INTEGER NOT NULL UNIQUE,
                    mode VARCHAR(20),
                    data JSON,
                    metadata JSON,
                    references JSON,
                    trace JSON,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(message_id) REFERENCES retrieval_chat_messages (id) ON DELETE CASCADE
                )
                """
            )
            conn.exec_driver_sql(
                "CREATE INDEX IF NOT EXISTS ix_retrieval_snapshots_message_id ON retrieval_snapshots (message_id)"
            )


def init_db():
    """Initialize database using Alembic migrations.
    
    This function:
    1. Ensures the database directory exists
    2. Runs Alembic migrations to create/update the database schema
    3. Handles both first-time initialization and upgrades
    """
    global _db_initialized

    if _db_initialized:
        return

    import logging
    from alembic.config import Config
    from alembic import command
    from pathlib import Path
    
    logger = logging.getLogger("lightrag")
    
    with _db_init_lock:
        if _db_initialized:
            return

        # Ensure the resolved rag storage directory exists
        os.makedirs(RAG_ROOT, exist_ok=True)

        try:
            # Get the project root directory (where alembic.ini is located)
            project_root = Path(__file__).parent.parent.parent.parent
            alembic_ini_path = project_root / "alembic.ini"

            if not alembic_ini_path.exists():
                logger.error(f"Alembic configuration not found at {alembic_ini_path}")
                raise FileNotFoundError(f"alembic.ini not found at {alembic_ini_path}")

            # Create Alembic config
            alembic_cfg = Config(str(alembic_ini_path))
            alembic_cfg.set_main_option("sqlalchemy.url", _sqlite_url_from_path(DB_PATH))

            # Run migrations to head (latest version)
            logger.info("Running database migrations...")
            command.upgrade(alembic_cfg, "head")
            logger.info("Database migrations completed successfully")

        except Exception as e:
            logger.error(f"Failed to run database migrations: {e}")
            # Fall back to direct table creation if migrations fail
            logger.warning("Falling back to direct table creation...")
            Base.metadata.create_all(bind=engine)
        try:
            _ensure_sqlite_chat_schema_compatibility()
        except Exception as compat_exc:
            logger.error(
                f"Failed to apply SQLite chat schema compatibility patch: {compat_exc}"
            )
        finally:
            _db_initialized = True
