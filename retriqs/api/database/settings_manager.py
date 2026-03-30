from .models import SessionLocal, AppSetting, GraphStorage, init_db
import os
import logging
import shutil
from sqlalchemy.orm import joinedload
from retriqs.api.storage_paths import resolve_storage_paths

logger = logging.getLogger("lightrag")


DEFAULT_CONFIG = {
    # --- Server & Core ---
    "HOST": "0.0.0.0",
    "PORT": "9621",
    "WORKERS": "1",
    "WORKING_DIR": "./rag_storage",
    "INPUT_DIR": "./inputs",
    "LOG_LEVEL": "INFO",
    "VERBOSE": "False",
    "TIMEOUT": "150",
    # --- LLM Binding (General) ---
    "LLM_BINDING": "ollama",
    "LLM_MODEL": "qwen3:0.6b",
    "LLM_BINDING_HOST": "http://localhost:11434",
    "LLM_BINDING_API_KEY": "",
    "OLLAMA_NUM_CTX": "32768",
    # --- Embedding Binding (General) ---
    "EMBEDDING_BINDING": "ollama",
    "EMBEDDING_MODEL": "bge-m3:latest",
    "EMBEDDING_BINDING_HOST": "http://localhost:11434",
    "EMBEDDING_BINDING_API_KEY": "",
    "EMBEDDING_DIM": "1024",
    "EMBEDDING_TOKEN_LIMIT": "8192",
    # --- RAG Logic Parameters ---
    "CHUNK_SIZE": "1200",
    "CHUNK_OVERLAP_SIZE": "100",
    "TOP_K": "50",
    "MAX_ENTITY_TOKENS": "1000",
    "MAX_RELATION_TOKENS": "1000",
    "COSINE_THRESHOLD": "0.4",
    "HISTORY_TURNS": "3",
    "MAX_ASYNC": "1",
    "SUMMARY_MAX_TOKENS": "500",
    "SUMMARY_LANGUAGE": "English",
    # --- Security & Auth ---
    "LIGHTRAG_API_KEY": "",
    "SSL": "False",
    "SSL_CERTFILE": "None",
    "SSL_KEYFILE": "None",
    "TOKEN_SECRET": "lightrag-jwt-default-secret",
    # --- Storage Configuration ---
    "LIGHTRAG_GRAPH_STORAGE": "NetworkXStorage",
    "LIGHTRAG_KV_STORAGE": "JsonKVStorage",
    "LIGHTRAG_DOC_STATUS_STORAGE": "JsonDocStatusStorage",
    "LIGHTRAG_VECTOR_STORAGE": "NanoVectorDBStorage",
    "NEO4J_URI": "bolt://localhost:7687",
    "NEO4J_USERNAME": "neo4j",
    "NEO4J_PASSWORD": "neo4j",
    "MILVUS_URI": "http://localhost:19530",
    "MILVUS_DB_NAME": "lightrag",
    "MILVUS_USER": "",
    "MILVUS_PASSWORD": "",
    "REDIS_URI": "redis://localhost:6379",
}

DEFAULT_GRAPH_CONFIG: GraphStorage = GraphStorage(
    name="default", work_dir=resolve_storage_paths().rag_root
)

# def initialize_db_settings():
#     """Initializes the DB: adds missing keys AND updates existing ones to match DEFAULT_CONFIG."""
#     init_db()
#     db = SessionLocal()
#     try:
#         for k, v in DEFAULT_CONFIG.items():
#             # 1. Try to find the existing record
#             setting = db.query(AppSetting).filter_by(key=k).first()
#             if setting:
#                 # 2. If it exists, update it to match the current DEFAULT_CONFIG
#                 if setting.value != str(v):
#                     setting.value = str(v)
#             else:
#                 # 3. If it's a brand new key you just added to the dictionary, create it
#                 db.add(AppSetting(key=k, value=str(v)))


#         # graph_setting = db.query(GraphStorage).filter_by(name=DEFAULT_GRAPH_CONFIG.name).first()

#         # if graph_setting:
#         #     # 2. If it exists, update it to match the current DEFAULT_CONFIG
#         #     if graph_setting.name != DEFAULT_GRAPH_CONFIG.name:
#         #         graph_setting.work_dir = DEFAULT_GRAPH_CONFIG.work_dir
#         # else:
#         #     # 3. If it's a brand new key you just added to the dictionary, create it
#         #     db.add(GraphStorage(name=DEFAULT_GRAPH_CONFIG.name, work_dir=DEFAULT_GRAPH_CONFIG.work_dir))

#         db.commit()
#     except Exception as e:
#         db.rollback()
#         print(f"Error syncing settings: {e}")
#     finally:
#         db.close()


def initialize_db_settings():
    init_db()


def get_db_settings():
    """Returns all settings from SQLite as a dictionary."""
    db = SessionLocal()
    settings = db.query(AppSetting).all()
    db.close()
    return {s.key: s.value for s in settings}


def get_db_setting_by_storage(key: str, storage_id: int):
    """Fetches a specific setting value by its key and storage_id from the database."""
    db = SessionLocal()
    try:
        # Query for the specific key and storage_id
        setting = db.query(AppSetting).filter_by(key=key, storage_id=storage_id).first()
        # Return the value if found, otherwise return None
        return setting.value if setting else None
    except Exception as e:
        logger.error(f"Error fetching setting '{key}' for storage {storage_id}: {e}")
        return None
    finally:
        db.close()


def update_db_setting(key: str, value: any):
    """
    Updates the value if key exists, otherwise creates a new record.
    Returns True regardless of whether it was an update or an insert.
    """
    db = SessionLocal()
    try:
        # 1. Search for the setting by key
        setting = db.query(AppSetting).filter_by(key=key).first()

        val_str = str(value) if value is not None else ""

        if setting:
            # 2. Update existing
            setting.value = val_str
        else:
            # 3. Create new if missing (The "Insert" part)
            new_setting = AppSetting(key=key, value=val_str)
            db.add(new_setting)

        db.commit()
        return True

    except Exception as e:
        db.rollback()
        print(f"Error saving setting '{key}': {e}")
        return False
    finally:
        db.close()


def update_db_setting_for_storage_id(storage_id: int, key: str, value: any):
    """
    Updates the value if key exists for the specific storage_id, otherwise creates a new record.
    Returns True regardless of whether it was an update or an insert.
    """
    db = SessionLocal()
    try:
        # 1. Search for the setting by key AND storage_id
        setting = db.query(AppSetting).filter_by(key=key, storage_id=storage_id).first()

        val_str = str(value) if value is not None else ""

        if setting:
            # 2. Update existing
            setting.value = val_str
        else:
            # 3. Create new if missing (The "Insert" part)
            new_setting = AppSetting(key=key, value=val_str, storage_id=storage_id)
            db.add(new_setting)

        db.commit()
        return True

    except Exception as e:
        db.rollback()
        print(f"Error saving setting '{key}' for storage {storage_id}: {e}")
        return False
    finally:
        db.close()


"""
Graph Storage variables
"""


def get_graph_storages():
    """
    Docstring for get_graph_storages

    gets all graph storages and its AppSettings
    """
    db = SessionLocal()
    try:
        graph_storages = (
            db.query(GraphStorage)
            .options(joinedload(GraphStorage.storage_settings))
            .all()
        )
        return graph_storages
    finally:
        db.close()


def add_and_create_storage(new_storage: GraphStorage):
    """
    Adds a new GraphStorage to the DB and sets a unique work_dir ased on its ID.
    """
    db = SessionLocal()
    logger.info("we are now here")
    try:
        if not new_storage.work_dir:
            new_storage.work_dir = "PENDING_ID"

        db.add(new_storage)
        db.flush()

        base_path = resolve_storage_paths().rag_root
        unique_folder_name = f"storage_{new_storage.id}"
        final_path = os.path.abspath(os.path.join(base_path, unique_folder_name))
        new_storage.work_dir = final_path

        os.makedirs(final_path, exist_ok=True)
        db.commit()
        db.refresh(new_storage)

        # Eagerly load the storage_settings relationship before closing the session
        # This prevents DetachedInstanceError when accessing storage_settings later
        _ = new_storage.storage_settings  # Force load the relationship

        # Make the object safe to use after session close
        db.expunge(new_storage)

        return new_storage
    except Exception as e:
        db.rollback()
        raise e
    finally:
        db.close()


def delete_storage_by_id(storage_id: int, base_rag_dir: str | None = None):
    """
    Docstring for delete_storage_by_id

    :param storage_id: Description
    :type storage_id: int
    :param base_rag_dir: Description
    :type base_rag_dir: str
    """
    db = SessionLocal()
    try:
        storage = db.query(GraphStorage).filter(GraphStorage.id == storage_id).first()

        if not storage:
            print(f"Storage with ID: {storage_id} not found.")
            return False

        folder_to_delete = storage.work_dir

        if not base_rag_dir:
            base_rag_dir = resolve_storage_paths().rag_root

        absolute_base = os.path.abspath(base_rag_dir)
        absolute_target = os.path.abspath(folder_to_delete)

        if absolute_base == absolute_target:
            raise ValueError(
                "Safety Triggered: Attempted to delte the root RAG storage directory!"
            )

        if not absolute_target.startswith(absolute_base):
            raise ValueError(
                "Safety Triggered: Target path is outside of the allowed RAG storage directory"
            )

        if os.path.exists(folder_to_delete) and os.path.isdir(folder_to_delete):
            shutil.rmtree(folder_to_delete)
            print(f"Deleted fodler: {folder_to_delete}")

            db.delete(storage)
            db.commit()

            return True
    except Exception as e:
        db.rollback()
        raise e
    finally:
        db.close()
