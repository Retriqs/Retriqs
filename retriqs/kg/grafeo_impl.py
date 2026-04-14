from __future__ import annotations

import asyncio
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Iterable, final
import math

from ..base import BaseGraphStorage, BaseVectorStorage
from ..constants import GRAPH_FIELD_SEP
from .shared_storage import get_data_init_lock
from ..types import KnowledgeGraph, KnowledgeGraphEdge, KnowledgeGraphNode
from ..utils import compute_mdhash_id, logger

try:
    import grafeo  # type: ignore
except Exception:  # pragma: no cover - runtime dependency resolution
    try:
        import pipmaster as pm  # type: ignore

        if not pm.is_installed("grafeo"):
            pm.install("grafeo")
        import grafeo  # type: ignore
    except Exception as e:  # pragma: no cover
        raise ImportError(
            "Grafeo support requires the 'grafeo' package. Install it with `pip install grafeo`."
        ) from e


# -----------------------------
# Helpers
# -----------------------------

def _to_1d_float_list(vector: Any) -> list[float]:
    """Accept numpy array / list / tuple and return a flat list[float]."""
    if vector is None:
        return []

    # numpy ndarray or similar
    if hasattr(vector, "tolist"):
        vector = vector.tolist()

    # flatten one extra level if needed, e.g. [[...]]
    if isinstance(vector, list) and len(vector) == 1 and isinstance(vector[0], (list, tuple)):
        vector = vector[0]

    return [float(x) for x in vector]


def _normalize_vector(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in vector))
    if norm == 0.0:
        return []
    return [v / norm for v in vector]

def _get_env_bool(key: str, default: bool) -> bool:
    value = os.getenv(key)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _get_env_int(key: str, default: int) -> int:
    value = os.getenv(key)
    if value is None:
        return default
    return int(value)


def _sanitize_name(name: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9_\-]", "_", name or "")
    return value.strip("_") or "default"


_JSON_PREFIX = "__json__:"


def _encode_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, list):
        if all(isinstance(v, (str, int, float, bool)) or v is None for v in value):
            return value
        return _JSON_PREFIX + json.dumps(value, ensure_ascii=False)
    if isinstance(value, tuple):
        return _JSON_PREFIX + json.dumps(list(value), ensure_ascii=False)
    if isinstance(value, set):
        return _JSON_PREFIX + json.dumps(sorted(value), ensure_ascii=False)
    if isinstance(value, dict):
        return _JSON_PREFIX + json.dumps(value, ensure_ascii=False)
    return _JSON_PREFIX + json.dumps(value, default=str, ensure_ascii=False)


def _decode_value(value: Any) -> Any:
    if isinstance(value, str) and value.startswith(_JSON_PREFIX):
        try:
            return json.loads(value[len(_JSON_PREFIX) :])
        except Exception:
            return value
    return value


def _coerce_mapping(obj: Any) -> dict[str, Any]:
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return dict(obj)
    if hasattr(obj, "items"):
        try:
            return {k: v for k, v in obj.items()}
        except Exception:
            pass
    try:
        return dict(obj)
    except Exception:
        return {}


def _encode_payload(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, default=str)


def _decode_payload(payload: str | None) -> dict[str, Any]:
    if not payload:
        return {}
    try:
        return json.loads(payload)
    except Exception:
        return {}


def _row_to_dict(row: Any) -> dict[str, Any]:
    if row is None:
        return {}
    if isinstance(row, dict):
        return dict(row)
    if hasattr(row, "items"):
        return {k: v for k, v in row.items()}
    try:
        return dict(row)
    except Exception:
        return {"value": row}


def _pick_storable_fields(data: dict[str, Any], fields: Iterable[str]) -> dict[str, Any]:
    return {k: _encode_value(data.get(k)) for k in fields if k in data}


def _merge_payload_with_props(
    payload: dict[str, Any],
    props: dict[str, Any] | None,
    allowed_fields: Iterable[str] | None = None,
) -> dict[str, Any]:
    result = dict(payload or {})
    props = props or {}

    if allowed_fields is None:
        for key, value in props.items():
            if key in {"payload_json", "embedding", "labels", "id", "node_id", "edge_id"}:
                continue
            if key not in result and value is not None:
                result[key] = _decode_value(value)
        return result

    for key in allowed_fields:
        if key not in result and key in props and props[key] is not None:
            result[key] = _decode_value(props[key])

    return result


def _default_stub_node_payload(node_id: str) -> dict[str, Any]:
    return {
        "entity_id": node_id,
        "entity_type": "UNKNOWN",
        "description": "UNKNOWN",
        "source_id": "",
        "file_path": "unknown_source",
    }


def _canonical_edge(src: str, tgt: str) -> tuple[str, str, str]:
    a, b = sorted([str(src), str(tgt)])
    edge_key = compute_mdhash_id(f"{a}|{b}", prefix="edge-")
    return a, b, edge_key


def _batched(items: list[Any], batch_size: int) -> Iterable[list[Any]]:
    if batch_size <= 0:
        batch_size = 1
    for i in range(0, len(items), batch_size):
        yield items[i : i + batch_size]


def _merge_update(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base or {})
    for key, value in (patch or {}).items():
        if value is None:
            continue
        if key in {"entity_type", "description"}:
            old = merged.get(key)
            if old not in (None, "", "UNKNOWN") and value == "UNKNOWN":
                continue
        merged[key] = value
    return merged


# -----------------------------
# Shared Grafeo storage mixin
# -----------------------------


class _GrafeoStorageMixin:
    db: Any = None
    _db_path: str | None = None
    _lock: asyncio.Lock
    _executor: ThreadPoolExecutor

    def _setup_grafeo_storage(self, default_label: str) -> None:
        self._lock = asyncio.Lock()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="grafeo")
        self._default_label = default_label
        self._db_path = self._resolve_db_path()
        self._write_batch_size = _get_env_int("GRAFEO_WRITE_BATCH_SIZE", 500)
        logger.info(
            "[Grafeo:%s] namespace=%s workspace=%s db_path=%s batch_size=%s",
            self.__class__.__name__,
            getattr(self, "namespace", ""),
            getattr(self, "workspace", ""),
            self._db_path or "<memory>",
            self._write_batch_size,
        )

    def _resolve_db_path(self) -> str | None:
        if _get_env_bool("GRAFEO_IN_MEMORY", False):
            return None

        working_dir = self.global_config.get("working_dir", ".")
        workspace = _sanitize_name(getattr(self, "workspace", "") or "")
        namespace = _sanitize_name(getattr(self, "namespace", "") or "default")
        workspace_dir = os.path.join(working_dir, workspace) if workspace else working_dir
        os.makedirs(workspace_dir, exist_ok=True)
        return os.path.join(workspace_dir, f"grafeo_{namespace}.db")

    async def _open_db(self) -> None:
        if self.db is not None:
            return
        async with self._lock:
            if self.db is not None:
                return
            loop = asyncio.get_running_loop()
            if self._db_path:
                self.db = await loop.run_in_executor(self._executor, lambda: grafeo.GrafeoDB(self._db_path))
            else:
                self.db = await loop.run_in_executor(self._executor, lambda: grafeo.GrafeoDB())

    async def _run_sync(self, fn, *args, **kwargs):
        await self._open_db()
        loop = asyncio.get_running_loop()
        async with self._lock:
            return await loop.run_in_executor(self._executor, lambda: fn(*args, **kwargs))

    def _exec_sync(self, query: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        result = self.db.execute(query, params or None)
        return [_row_to_dict(row) for row in result]

    async def _exec(self, query: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        return await self._run_sync(self._exec_sync, query, params)

    async def _save_if_needed(self) -> None:
        if self.db is None or not self._db_path:
            return
        try:
            await self._run_sync(self.db.save, self._db_path)
        except Exception as e:
            logger.info("[Grafeo:%s] explicit save skipped: %s", self.__class__.__name__, e)

    async def finalize(self):
        try:
            await self._save_if_needed()
        finally:
            self.db = None
            try:
                self._executor.shutdown(wait=False, cancel_futures=True)
            except Exception:
                pass

    async def index_done_callback(self) -> None:
        if _get_env_bool("GRAFEO_EXPLICIT_SAVE", True):
            await self._save_if_needed()

    async def drop(self) -> dict[str, str]:
        try:
            await self._exec("MATCH (n) DETACH DELETE n")
            await self._save_if_needed()
            return {"status": "success", "message": "data dropped"}
        except Exception as e:
            return {"status": "error", "message": str(e)}


# -----------------------------
# Graph storage
# -----------------------------

@final
@dataclass
class GrafeoGraphStorage(_GrafeoStorageMixin, BaseGraphStorage):
    db: Any = field(default=None)

    NODE_LABEL: str = field(default="LightragNode", init=False)
    EDGE_TYPE: str = field(default="LIGHTRAG_REL", init=False)

    def __init__(self, namespace, global_config, embedding_func, workspace=None):
        super().__init__(
            namespace=namespace,
            workspace=workspace or "",
            global_config=global_config,
            embedding_func=embedding_func,
        )
        self._setup_grafeo_storage(self.NODE_LABEL)

        # Buffered writes:
        # - upsert_node / upsert_edge only update these dicts
        # - index_done_callback / finalize flush them in bulk
        self._pending_lock = asyncio.Lock()
        self._pending_node_patches: dict[str, dict[str, Any]] = {}
        self._pending_edge_patches: dict[str, dict[str, Any]] = {}

    async def initialize(self):
        """
        Initialize graph storage and create indexes used by the hot read paths.

        We index:
        - entity_id       -> root lookup / node lookup
        - edge_key        -> edge lookup
        - source_node_id  -> edge filtering
        - target_node_id  -> edge filtering
        """
        async with get_data_init_lock():
            await self._open_db()

            for prop in ("entity_id", "edge_key", "source_node_id", "target_node_id"):
                try:
                    await self._run_sync(self.db.create_property_index, prop)
                except Exception:
                    pass

            try:
                await self._run_sync(self.db.create_text_index, self.NODE_LABEL, "entity_id")
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Helpers for buffered graph writes
    # ------------------------------------------------------------------

    async def _has_pending_graph_writes(self) -> bool:
        """Fast check to avoid unnecessary flush work on read-heavy paths."""
        async with self._pending_lock:
            return bool(self._pending_node_patches or self._pending_edge_patches)

    def _node_row(self, node_id: str, node_data: dict[str, Any]) -> dict[str, Any]:
        """
        Convert logical node payload into a row suitable for bulk UNWIND writes.
        """
        row = {
            "entity_id": node_id,
            "payload_json": _encode_payload(node_data),
            "entity_type": _encode_value(node_data.get("entity_type")),
            "description": _encode_value(node_data.get("description")),
            "source_id": _encode_value(node_data.get("source_id")),
            "file_path": _encode_value(node_data.get("file_path")),
            "created_at": _encode_value(node_data.get("created_at")),
        }

        source_id = node_data.get("source_id")
        if isinstance(source_id, str) and source_id:
            row["source_ids_json"] = _JSON_PREFIX + json.dumps(
                source_id.split(GRAPH_FIELD_SEP), ensure_ascii=False
            )
        else:
            row["source_ids_json"] = None

        return row

    def _edge_row(self, src_id: str, tgt_id: str, edge_data: dict[str, Any]) -> dict[str, Any]:
        """
        Convert logical edge payload into a row suitable for bulk UNWIND writes.
        """
        canon_src, canon_tgt, edge_key = _canonical_edge(src_id, tgt_id)

        row = {
            "edge_key": edge_key,
            "source_node_id": canon_src,
            "target_node_id": canon_tgt,
            "payload_json": _encode_payload(edge_data),
            "relationship": _encode_value(edge_data.get("relationship")),
            "description": _encode_value(edge_data.get("description")),
            "weight": _encode_value(edge_data.get("weight")),
            "keywords": _encode_value(edge_data.get("keywords")),
            "source_id": _encode_value(edge_data.get("source_id")),
            "file_path": _encode_value(edge_data.get("file_path")),
            "created_at": _encode_value(edge_data.get("created_at")),
        }

        source_id = edge_data.get("source_id")
        if isinstance(source_id, str) and source_id:
            row["source_ids_json"] = _JSON_PREFIX + json.dumps(
                source_id.split(GRAPH_FIELD_SEP), ensure_ascii=False
            )
        else:
            row["source_ids_json"] = None

        return row

    def _flush_graph_batch_sync(
        self,
        node_patches: dict[str, dict[str, Any]],
        edge_patches: dict[str, dict[str, Any]],
    ) -> None:
        """
        Flush buffered node/edge patches to Grafeo in bulk.

        Important design choice:
        - We do NOT load existing nodes/edges from the DB first.
        - The pending buffers already collapse repeated updates in-memory via _merge_update().
        - This removes an avoidable read-before-write DB round-trip during flush.
        """

        # -------------------------
        # Flush nodes
        # -------------------------
        if node_patches:
            node_rows: list[dict[str, Any]] = []

            for entity_id, patch in node_patches.items():
                merged = dict(patch)
                merged["entity_id"] = entity_id
                node_rows.append(self._node_row(entity_id, merged))

            for batch in _batched(node_rows, self._write_batch_size):
                self.db.execute(
                    f"UNWIND $rows AS row "
                    f"MERGE (n:{self.NODE_LABEL} {{entity_id: row.entity_id}}) "
                    "SET n.payload_json = row.payload_json, "
                    "    n.entity_type = row.entity_type, "
                    "    n.description = row.description, "
                    "    n.source_id = row.source_id, "
                    "    n.file_path = row.file_path, "
                    "    n.created_at = row.created_at, "
                    "    n.source_ids_json = row.source_ids_json",
                    {"rows": batch},
                )

        # -------------------------
        # Flush edges
        # -------------------------
        if edge_patches:
            edge_rows: list[dict[str, Any]] = []

            for edge_key, patch in edge_patches.items():
                merged = dict(patch)
                src = str(merged.get("source_node_id"))
                tgt = str(merged.get("target_node_id"))
                merged["source_node_id"] = src
                merged["target_node_id"] = tgt
                edge_rows.append(self._edge_row(src, tgt, merged))

            for batch in _batched(edge_rows, self._write_batch_size):
                self.db.execute(
                    f"UNWIND $rows AS row "
                    f"MERGE (a:{self.NODE_LABEL} {{entity_id: row.source_node_id}}) "
                    "ON CREATE SET "
                    "    a.payload_json = row.source_stub_payload_json, "
                    "    a.entity_type = 'UNKNOWN', "
                    "    a.description = 'UNKNOWN', "
                    "    a.source_id = '', "
                    "    a.file_path = 'unknown_source' "
                    f"MERGE (b:{self.NODE_LABEL} {{entity_id: row.target_node_id}}) "
                    "ON CREATE SET "
                    "    b.payload_json = row.target_stub_payload_json, "
                    "    b.entity_type = 'UNKNOWN', "
                    "    b.description = 'UNKNOWN', "
                    "    b.source_id = '', "
                    "    b.file_path = 'unknown_source' "
                    f"MERGE (a)-[r:{self.EDGE_TYPE} {{edge_key: row.edge_key}}]->(b) "
                    "SET r.payload_json = row.payload_json, "
                    "    r.relationship = row.relationship, "
                    "    r.description = row.description, "
                    "    r.weight = row.weight, "
                    "    r.keywords = row.keywords, "
                    "    r.source_id = row.source_id, "
                    "    r.file_path = row.file_path, "
                    "    r.created_at = row.created_at, "
                    "    r.source_ids_json = row.source_ids_json, "
                    "    r.source_node_id = row.source_node_id, "
                    "    r.target_node_id = row.target_node_id",
                    {
                        "rows": [
                            {
                                **row,
                                "source_stub_payload_json": _encode_payload(
                                    _default_stub_node_payload(row["source_node_id"])
                                ),
                                "target_stub_payload_json": _encode_payload(
                                    _default_stub_node_payload(row["target_node_id"])
                                ),
                            }
                            for row in batch
                        ]
                    },
                )

    async def _flush_pending_graph_writes(self) -> None:
        """
        Flush buffered graph writes until the buffers are empty.

        The loop handles the case where more writes arrive while a flush is already
        in progress.
        """
        while True:
            async with self._pending_lock:
                if not self._pending_node_patches and not self._pending_edge_patches:
                    return

                node_patches = self._pending_node_patches
                edge_patches = self._pending_edge_patches
                self._pending_node_patches = {}
                self._pending_edge_patches = {}

            logger.info(
                "[GrafeoGraphStorage] flushing nodes=%s edges=%s",
                len(node_patches),
                len(edge_patches),
            )
            await self._run_sync(self._flush_graph_batch_sync, node_patches, edge_patches)

    async def index_done_callback(self) -> None:
        """
        Persist buffered graph writes at the normal index boundary.
        """
        await self._flush_pending_graph_writes()
        await super().index_done_callback()

    async def finalize(self):
        """
        Finalize storage cleanly after flushing any pending graph writes.
        """
        await self._flush_pending_graph_writes()
        await super().finalize()

    async def drop(self) -> dict[str, str]:
        async with self._pending_lock:
            self._pending_node_patches.clear()
            self._pending_edge_patches.clear()
        return await super().drop()

    # ------------------------------------------------------------------
    # Simple existence / degree APIs
    # ------------------------------------------------------------------

    async def has_node(self, node_id: str) -> bool:
        node_id = str(node_id)
        async with self._pending_lock:
            if node_id in self._pending_node_patches:
                return True

        rows = await self._exec(
            f"MATCH (n:{self.NODE_LABEL} {{entity_id: $entity_id}}) "
            "RETURN 1 AS found LIMIT 1",
            {"entity_id": node_id},
        )
        return bool(rows)

    async def has_edge(self, source_node_id: str, target_node_id: str) -> bool:
        _, _, edge_key = _canonical_edge(source_node_id, target_node_id)

        async with self._pending_lock:
            if edge_key in self._pending_edge_patches:
                return True

        rows = await self._exec(
            f"MATCH ()-[r:{self.EDGE_TYPE} {{edge_key: $edge_key}}]->() "
            "RETURN 1 AS found LIMIT 1",
            {"edge_key": edge_key},
        )
        return bool(rows)

    async def node_degree(self, node_id: str) -> int:
        if await self._has_pending_graph_writes():
            await self._flush_pending_graph_writes()

        rows = await self._exec(
            f"MATCH (n:{self.NODE_LABEL} {{entity_id: $entity_id}})-[r:{self.EDGE_TYPE}]-() "
            "RETURN COUNT(r) AS degree",
            {"entity_id": str(node_id)},
        )
        return int(rows[0].get("degree", 0)) if rows else 0

    async def edge_degree(self, src_id: str, tgt_id: str) -> int:
        degree_map = await self.node_degrees_batch([str(src_id), str(tgt_id)])
        return degree_map.get(str(src_id), 0) + degree_map.get(str(tgt_id), 0)

    # ------------------------------------------------------------------
    # Single node / edge fetch APIs
    # ------------------------------------------------------------------

    async def get_node(self, node_id: str) -> dict[str, str] | None:
        """
        Return persisted node merged with any pending patch for correctness.
        """
        node_id = str(node_id)

        async with self._pending_lock:
            pending = self._pending_node_patches.get(node_id)

        rows = await self._exec(
            f"MATCH (n:{self.NODE_LABEL} {{entity_id: $entity_id}}) "
            "RETURN n.entity_id AS entity_id, "
            "       n.entity_type AS entity_type, "
            "       n.description AS description, "
            "       n.source_id AS source_id, "
            "       n.file_path AS file_path, "
            "       n.created_at AS created_at, "
            "       n.payload_json AS payload_json "
            "LIMIT 1",
            {"entity_id": node_id},
        )

        base: dict[str, Any] = {}
        if rows:
            row = rows[0]
            base = _decode_payload(row.get("payload_json"))
            base = _merge_payload_with_props(
                base,
                row,
                allowed_fields=[
                    "entity_id",
                    "entity_type",
                    "description",
                    "source_id",
                    "file_path",
                    "created_at",
                ],
            )

        if pending is not None:
            payload = _merge_update(base, pending)
            payload.setdefault("entity_id", node_id)
            return payload

        if not rows:
            return None

        base.setdefault("entity_id", node_id)
        return base

    async def get_edge(self, source_node_id: str, target_node_id: str) -> dict[str, str] | None:
        """
        Return persisted edge merged with any pending patch for correctness.
        """
        canon_src, canon_tgt, edge_key = _canonical_edge(source_node_id, target_node_id)

        async with self._pending_lock:
            pending = self._pending_edge_patches.get(edge_key)

        rows = await self._exec(
            f"MATCH ()-[r:{self.EDGE_TYPE} {{edge_key: $edge_key}}]->() "
            "RETURN r.payload_json AS payload_json, "
            "       r.source_node_id AS source_node_id, "
            "       r.target_node_id AS target_node_id, "
            "       r.relationship AS relationship, "
            "       r.description AS description, "
            "       r.weight AS weight, "
            "       r.keywords AS keywords, "
            "       r.source_id AS source_id, "
            "       r.file_path AS file_path, "
            "       r.created_at AS created_at "
            "LIMIT 1",
            {"edge_key": edge_key},
        )

        base: dict[str, Any] = {}
        if rows:
            row = rows[0]
            base = _decode_payload(row.get("payload_json"))
            base = _merge_payload_with_props(
                base,
                row,
                allowed_fields=[
                    "relationship",
                    "description",
                    "weight",
                    "keywords",
                    "source_id",
                    "file_path",
                    "created_at",
                ],
            )
            base.setdefault("source_node_id", row.get("source_node_id"))
            base.setdefault("target_node_id", row.get("target_node_id"))

        if pending is not None:
            payload = _merge_update(base, pending)
            payload.setdefault("source_node_id", canon_src)
            payload.setdefault("target_node_id", canon_tgt)
            return payload

        if not rows:
            return None

        return base

    async def get_node_edges(self, source_node_id: str) -> list[tuple[str, str]] | None:
        if await self._has_pending_graph_writes():
            await self._flush_pending_graph_writes()

        rows = await self._exec(
            f"MATCH (n:{self.NODE_LABEL} {{entity_id: $entity_id}})-[r:{self.EDGE_TYPE}]-() "
            "RETURN r.source_node_id AS source_node_id, r.target_node_id AS target_node_id",
            {"entity_id": str(source_node_id)},
        )

        if not rows:
            exists = await self.has_node(source_node_id)
            return [] if exists else None

        return [
            (str(row.get("source_node_id")), str(row.get("target_node_id")))
            for row in rows
            if row.get("source_node_id") is not None and row.get("target_node_id") is not None
        ]

    # ------------------------------------------------------------------
    # Buffered write APIs
    # ------------------------------------------------------------------

    async def upsert_node(self, node_id: str, node_data: dict[str, str]) -> None:
        """
        Buffer node writes in memory. Repeated writes collapse via _merge_update().
        """
        node_id = str(node_id)
        patch = dict(node_data or {})
        patch["entity_id"] = node_id

        async with self._pending_lock:
            base = self._pending_node_patches.get(node_id, {})
            self._pending_node_patches[node_id] = _merge_update(base, patch)

    async def upsert_edge(self, source_node_id: str, target_node_id: str, edge_data: dict[str, str]) -> None:
        """
        Buffer edge writes in memory. Also ensure endpoint stubs exist in the node buffer.
        """
        canon_src, canon_tgt, edge_key = _canonical_edge(source_node_id, target_node_id)

        patch = dict(edge_data or {})
        patch["source_node_id"] = canon_src
        patch["target_node_id"] = canon_tgt

        async with self._pending_lock:
            self._pending_node_patches.setdefault(canon_src, {"entity_id": canon_src})
            self._pending_node_patches.setdefault(canon_tgt, {"entity_id": canon_tgt})

            base = self._pending_edge_patches.get(edge_key, {})
            self._pending_edge_patches[edge_key] = _merge_update(base, patch)

    # ------------------------------------------------------------------
    # Delete APIs
    # ------------------------------------------------------------------

    async def delete_node(self, node_id: str) -> None:
        node_id = str(node_id)

        async with self._pending_lock:
            self._pending_node_patches.pop(node_id, None)

            doomed_edges = [
                edge_key
                for edge_key, patch in self._pending_edge_patches.items()
                if patch.get("source_node_id") == node_id or patch.get("target_node_id") == node_id
            ]
            for edge_key in doomed_edges:
                self._pending_edge_patches.pop(edge_key, None)

        await self._exec(
            f"MATCH (n:{self.NODE_LABEL} {{entity_id: $entity_id}}) DETACH DELETE n",
            {"entity_id": node_id},
        )

    async def remove_nodes(self, nodes: list[str]):
        if not nodes:
            return

        unique_nodes = list(dict.fromkeys(str(node) for node in nodes))

        async with self._pending_lock:
            for node_id in unique_nodes:
                self._pending_node_patches.pop(node_id, None)

            doomed_edges = [
                edge_key
                for edge_key, patch in self._pending_edge_patches.items()
                if patch.get("source_node_id") in unique_nodes or patch.get("target_node_id") in unique_nodes
            ]
            for edge_key in doomed_edges:
                self._pending_edge_patches.pop(edge_key, None)

        await self._exec(
            f"MATCH (n:{self.NODE_LABEL}) WHERE n.entity_id IN $entity_ids DETACH DELETE n",
            {"entity_ids": unique_nodes},
        )

    async def remove_edges(self, edges: list[tuple[str, str]]):
        if not edges:
            return

        edge_keys = []
        async with self._pending_lock:
            for src, tgt in edges:
                _, _, edge_key = _canonical_edge(src, tgt)
                self._pending_edge_patches.pop(edge_key, None)
                edge_keys.append(edge_key)

        await self._exec(
            f"MATCH ()-[r:{self.EDGE_TYPE}]->() WHERE r.edge_key IN $edge_keys DELETE r",
            {"edge_keys": edge_keys},
        )

    # ------------------------------------------------------------------
    # Bulk / batch read APIs
    # ------------------------------------------------------------------

    async def get_all_labels(self) -> list[str]:
        if await self._has_pending_graph_writes():
            await self._flush_pending_graph_writes()

        rows = await self._exec(
            f"MATCH (n:{self.NODE_LABEL}) RETURN n.entity_id AS entity_id ORDER BY n.entity_id ASC"
        )
        return [str(row.get("entity_id")) for row in rows if row.get("entity_id") is not None]

    def _construct_graph_node(self, node_id: str, node_data: dict[str, Any]) -> KnowledgeGraphNode:
        return KnowledgeGraphNode(
            id=node_id,
            labels=[node_id],
            properties={k: v for k, v in node_data.items() if k != "entity_id"},
        )

    def _construct_graph_edge(self, edge_id: str, edge: dict[str, Any]) -> KnowledgeGraphEdge:
        return KnowledgeGraphEdge(
            id=edge_id,
            type=edge.get("relationship", ""),
            source=edge["source_node_id"],
            target=edge["target_node_id"],
            properties={
                k: v
                for k, v in edge.items()
                if k not in {"source_node_id", "target_node_id", "relationship"}
            },
        )

    def _fetch_graph_nodes_by_internal_ids_sync(self, internal_ids: list[Any]) -> list[dict[str, Any]]:
        """
        Bulk hydrate graph nodes using native property-batch access instead of a general query.
        This is usually faster after BFS has already produced internal node ids.
        """
        if not internal_ids:
            return []

        entity_ids = self.db.get_property_batch(internal_ids, "entity_id")
        payload_jsons = self.db.get_property_batch(internal_ids, "payload_json")
        entity_types = self.db.get_property_batch(internal_ids, "entity_type")
        descriptions = self.db.get_property_batch(internal_ids, "description")
        source_ids = self.db.get_property_batch(internal_ids, "source_id")
        file_paths = self.db.get_property_batch(internal_ids, "file_path")
        created_ats = self.db.get_property_batch(internal_ids, "created_at")

        rows: list[dict[str, Any]] = []
        for node_id, entity_id, payload_json, entity_type, description, source_id, file_path, created_at in zip(
            internal_ids,
            entity_ids,
            payload_jsons,
            entity_types,
            descriptions,
            source_ids,
            file_paths,
            created_ats,
        ):
            rows.append(
                {
                    "node_id": node_id,
                    "entity_id": entity_id,
                    "payload_json": payload_json,
                    "entity_type": entity_type,
                    "description": description,
                    "source_id": source_id,
                    "file_path": file_path,
                    "created_at": created_at,
                }
            )
        return rows

    # ------------------------------------------------------------------
    # Knowledge graph fetch
    # ------------------------------------------------------------------

    async def get_knowledge_graph(self, node_label: str, max_depth: int = 3, max_nodes: int = 1000) -> KnowledgeGraph:
        """
        Return either:
        - the whole graph (node_label == "*"), truncated to max_nodes
        - a BFS neighborhood around the requested entity_id
        """
        if await self._has_pending_graph_writes():
            await self._flush_pending_graph_writes()

        result = KnowledgeGraph()

        # --------------------------------------------------------------
        # Whole graph mode
        # --------------------------------------------------------------
        if node_label == "*":
            node_rows = await self._exec(
                f"MATCH (n:{self.NODE_LABEL}) "
                "RETURN n.entity_id AS entity_id, "
                "       n.payload_json AS payload_json, "
                "       n.entity_type AS entity_type, "
                "       n.description AS description, "
                "       n.source_id AS source_id, "
                "       n.file_path AS file_path, "
                "       n.created_at AS created_at "
                "ORDER BY n.entity_id ASC "
                "LIMIT $limit",
                {"limit": int(max_nodes)},
            )

            kept_ids: list[str] = []
            for row in node_rows:
                entity_id = row.get("entity_id")
                if entity_id is None:
                    continue

                payload = _decode_payload(row.get("payload_json"))
                payload = _merge_payload_with_props(
                    payload,
                    row,
                    allowed_fields=[
                        "entity_id",
                        "entity_type",
                        "description",
                        "source_id",
                        "file_path",
                        "created_at",
                    ],
                )
                payload.setdefault("entity_id", str(entity_id))
                kept_ids.append(str(entity_id))
                result.nodes.append(self._construct_graph_node(str(entity_id), payload))

            if not kept_ids:
                return result

            if len(kept_ids) >= max_nodes:
                result.is_truncated = True

            edge_rows = await self._exec(
                f"MATCH ()-[r:{self.EDGE_TYPE}]->() "
                "WHERE r.source_node_id IN $node_ids AND r.target_node_id IN $node_ids "
                "RETURN r.source_node_id AS source_node_id, "
                "       r.target_node_id AS target_node_id, "
                "       r.payload_json AS payload_json, "
                "       r.relationship AS relationship, "
                "       r.description AS description, "
                "       r.weight AS weight, "
                "       r.keywords AS keywords, "
                "       r.source_id AS source_id, "
                "       r.file_path AS file_path, "
                "       r.created_at AS created_at",
                {"node_ids": kept_ids},
            )

            seen_edges: set[str] = set()
            for row in edge_rows:
                src = row.get("source_node_id")
                tgt = row.get("target_node_id")
                if src is None or tgt is None:
                    continue

                _, _, edge_key = _canonical_edge(str(src), str(tgt))
                if edge_key in seen_edges:
                    continue
                seen_edges.add(edge_key)

                payload = _decode_payload(row.get("payload_json"))
                payload = _merge_payload_with_props(
                    payload,
                    row,
                    allowed_fields=[
                        "relationship",
                        "description",
                        "weight",
                        "keywords",
                        "source_id",
                        "file_path",
                        "created_at",
                    ],
                )
                payload.setdefault("source_node_id", str(src))
                payload.setdefault("target_node_id", str(tgt))
                result.edges.append(self._construct_graph_edge(edge_key, payload))

            return result

        # --------------------------------------------------------------
        # Neighborhood mode
        # --------------------------------------------------------------

        # Use native property lookup instead of a query just to get the root id.
        root_ids = await self._run_sync(self.db.find_nodes_by_property, "entity_id", str(node_label))
        if not root_ids:
            return result

        root_internal_id = root_ids[0]

        # Native BFS over the internal graph structure.
        layers = await self._run_sync(self.db.algorithms.bfs_layers, root_internal_id)
        if not layers:
            return result

        kept_internal_ids: list[Any] = []
        seen_internal_ids: set[Any] = set()

        for depth, layer in enumerate(layers):
            if depth > max_depth:
                break

            for internal_id in layer:
                if internal_id in seen_internal_ids:
                    continue
                seen_internal_ids.add(internal_id)
                kept_internal_ids.append(internal_id)

                if len(kept_internal_ids) >= max_nodes:
                    result.is_truncated = True
                    break

            if len(kept_internal_ids) >= max_nodes:
                break

        if not kept_internal_ids:
            return result

        # Hydrate nodes via native property batch fetch.
        node_rows = await self._run_sync(self._fetch_graph_nodes_by_internal_ids_sync, kept_internal_ids)

        kept_entity_ids: list[str] = []
        for row in node_rows:
            entity_id = row.get("entity_id")
            if entity_id is None:
                continue

            payload = _decode_payload(row.get("payload_json"))
            payload = _merge_payload_with_props(
                payload,
                row,
                allowed_fields=[
                    "entity_id",
                    "entity_type",
                    "description",
                    "source_id",
                    "file_path",
                    "created_at",
                ],
            )
            payload.setdefault("entity_id", str(entity_id))
            kept_entity_ids.append(str(entity_id))
            result.nodes.append(self._construct_graph_node(str(entity_id), payload))

        if not kept_entity_ids:
            return result

        # Fetch only edges fully inside the kept node set.
        edge_rows = await self._exec(
            f"MATCH ()-[r:{self.EDGE_TYPE}]->() "
            "WHERE r.source_node_id IN $node_ids AND r.target_node_id IN $node_ids "
            "RETURN r.source_node_id AS source_node_id, "
            "       r.target_node_id AS target_node_id, "
            "       r.payload_json AS payload_json, "
            "       r.relationship AS relationship, "
            "       r.description AS description, "
            "       r.weight AS weight, "
            "       r.keywords AS keywords, "
            "       r.source_id AS source_id, "
            "       r.file_path AS file_path, "
            "       r.created_at AS created_at",
            {"node_ids": kept_entity_ids},
        )

        seen_edges: set[str] = set()
        for row in edge_rows:
            src = row.get("source_node_id")
            tgt = row.get("target_node_id")
            if src is None or tgt is None:
                continue

            _, _, edge_key = _canonical_edge(str(src), str(tgt))
            if edge_key in seen_edges:
                continue
            seen_edges.add(edge_key)

            payload = _decode_payload(row.get("payload_json"))
            payload = _merge_payload_with_props(
                payload,
                row,
                allowed_fields=[
                    "relationship",
                    "description",
                    "weight",
                    "keywords",
                    "source_id",
                    "file_path",
                    "created_at",
                ],
            )
            payload.setdefault("source_node_id", str(src))
            payload.setdefault("target_node_id", str(tgt))
            result.edges.append(self._construct_graph_edge(edge_key, payload))

        return result

    # ------------------------------------------------------------------
    # Batch helper APIs
    # ------------------------------------------------------------------

    async def get_nodes_batch(self, node_ids: list[str]) -> dict[str, dict]:
        if not node_ids:
            return {}

        if await self._has_pending_graph_writes():
            await self._flush_pending_graph_writes()

        unique_node_ids = list(dict.fromkeys(str(node_id) for node_id in node_ids))

        rows = await self._exec(
            f"UNWIND $node_ids AS requested_id "
            f"MATCH (n:{self.NODE_LABEL} {{entity_id: requested_id}}) "
            "RETURN requested_id, "
            "       n.entity_id AS entity_id, "
            "       n.entity_type AS entity_type, "
            "       n.description AS description, "
            "       n.source_id AS source_id, "
            "       n.file_path AS file_path, "
            "       n.created_at AS created_at, "
            "       n.payload_json AS payload_json",
            {"node_ids": unique_node_ids},
        )

        result: dict[str, dict] = {}
        for row in rows:
            requested_id = row.get("requested_id")
            if requested_id is None:
                continue

            payload = _decode_payload(row.get("payload_json"))
            payload = _merge_payload_with_props(
                payload,
                row,
                allowed_fields=[
                    "entity_id",
                    "entity_type",
                    "description",
                    "source_id",
                    "file_path",
                    "created_at",
                ],
            )
            payload.setdefault("entity_id", str(requested_id))
            result[str(requested_id)] = payload

        return result

    async def node_degrees_batch(self, node_ids: list[str]) -> dict[str, int]:
        if not node_ids:
            return {}

        if await self._has_pending_graph_writes():
            await self._flush_pending_graph_writes()

        unique_node_ids = list(dict.fromkeys(str(node_id) for node_id in node_ids))

        rows = await self._exec(
            f"UNWIND $node_ids AS node_id "
            f"MATCH (n:{self.NODE_LABEL} {{entity_id: node_id}}) "
            f"OPTIONAL MATCH (n)-[r:{self.EDGE_TYPE}]-() "
            "RETURN node_id, COUNT(r) AS degree",
            {"node_ids": unique_node_ids},
        )

        result = {node_id: 0 for node_id in unique_node_ids}
        for row in rows:
            result[str(row["node_id"])] = int(row.get("degree", 0) or 0)

        return result

    async def edge_degrees_batch(self, edge_pairs: list[tuple[str, str]]) -> dict[tuple[str, str], int]:
        if not edge_pairs:
            return {}

        canonical_pairs: list[tuple[str, str]] = []
        seen: set[tuple[str, str]] = set()

        for src_id, tgt_id in edge_pairs:
            canon_src, canon_tgt, _ = _canonical_edge(src_id, tgt_id)
            pair = (canon_src, canon_tgt)
            if pair in seen:
                continue
            seen.add(pair)
            canonical_pairs.append(pair)

        unique_node_ids = list(
            dict.fromkeys([src for src, _ in canonical_pairs] + [tgt for _, tgt in canonical_pairs])
        )
        degree_map = await self.node_degrees_batch(unique_node_ids)

        return {
            pair: degree_map.get(pair[0], 0) + degree_map.get(pair[1], 0)
            for pair in canonical_pairs
        }

    async def get_edges_batch(self, pairs: list[dict[str, str]]) -> dict[tuple[str, str], dict]:
        if not pairs:
            return {}

        if await self._has_pending_graph_writes():
            await self._flush_pending_graph_writes()

        canonical_pairs: list[tuple[str, str, str]] = []
        seen: set[tuple[str, str]] = set()

        for pair in pairs:
            src_id = pair["src"]
            tgt_id = pair["tgt"]
            canon_src, canon_tgt, edge_key = _canonical_edge(src_id, tgt_id)
            dedup_key = (canon_src, canon_tgt)
            if dedup_key in seen:
                continue
            seen.add(dedup_key)
            canonical_pairs.append((canon_src, canon_tgt, edge_key))

        edge_keys = [edge_key for _, _, edge_key in canonical_pairs]
        edge_key_to_pair = {edge_key: (src, tgt) for src, tgt, edge_key in canonical_pairs}

        rows = await self._exec(
            f"UNWIND $edge_keys AS edge_key "
            f"MATCH ()-[r:{self.EDGE_TYPE} {{edge_key: edge_key}}]->() "
            "RETURN edge_key, "
            "       r.payload_json AS payload_json, "
            "       r.source_node_id AS source_node_id, "
            "       r.target_node_id AS target_node_id, "
            "       r.relationship AS relationship, "
            "       r.description AS description, "
            "       r.weight AS weight, "
            "       r.keywords AS keywords, "
            "       r.source_id AS source_id, "
            "       r.file_path AS file_path, "
            "       r.created_at AS created_at",
            {"edge_keys": edge_keys},
        )

        result: dict[tuple[str, str], dict] = {}
        for row in rows:
            edge_key = row.get("edge_key")
            if not edge_key:
                continue

            requested_pair = edge_key_to_pair.get(str(edge_key))
            if requested_pair is None:
                continue

            payload = _decode_payload(row.get("payload_json"))
            payload = _merge_payload_with_props(
                payload,
                row,
                allowed_fields=[
                    "relationship",
                    "description",
                    "weight",
                    "keywords",
                    "source_id",
                    "file_path",
                    "created_at",
                ],
            )
            payload.setdefault("source_node_id", row.get("source_node_id"))
            payload.setdefault("target_node_id", row.get("target_node_id"))
            result[requested_pair] = payload

        return result

    async def get_nodes_edges_batch(self, node_ids: list[str]) -> dict[str, list[tuple[str, str]]]:
        if not node_ids:
            return {}

        if await self._has_pending_graph_writes():
            await self._flush_pending_graph_writes()

        unique_node_ids = list(dict.fromkeys(str(node_id) for node_id in node_ids))

        rows = await self._exec(
            f"UNWIND $node_ids AS node_id "
            f"OPTIONAL MATCH (n:{self.NODE_LABEL} {{entity_id: node_id}})-[r:{self.EDGE_TYPE}]-() "
            "RETURN node_id, "
            "       COLLECT(CASE WHEN r IS NULL THEN NULL ELSE [r.source_node_id, r.target_node_id] END) AS raw_edges",
            {"node_ids": unique_node_ids},
        )

        result: dict[str, list[tuple[str, str]]] = {}
        for row in rows:
            raw_edges = row.get("raw_edges") or []
            edges: list[tuple[str, str]] = []

            for item in raw_edges:
                if not item or len(item) != 2:
                    continue
                edges.append((str(item[0]), str(item[1])))

            result[str(row["node_id"])] = edges

        for node_id in unique_node_ids:
            result.setdefault(node_id, [])

        return result

    async def get_all_nodes(self) -> list[dict]:
        if await self._has_pending_graph_writes():
            await self._flush_pending_graph_writes()

        rows = await self._exec(
            f"MATCH (n:{self.NODE_LABEL}) "
            "RETURN n.entity_id AS entity_id, "
            "       n.payload_json AS payload_json, "
            "       n.entity_type AS entity_type, "
            "       n.description AS description, "
            "       n.source_id AS source_id, "
            "       n.file_path AS file_path, "
            "       n.created_at AS created_at"
        )

        result = []
        for row in rows:
            entity_id = row.get("entity_id")
            if entity_id is None:
                continue

            payload = _decode_payload(row.get("payload_json"))
            payload = _merge_payload_with_props(
                payload,
                row,
                allowed_fields=[
                    "entity_id",
                    "entity_type",
                    "description",
                    "source_id",
                    "file_path",
                    "created_at",
                ],
            )
            payload["id"] = str(entity_id)
            result.append(payload)

        return result

    async def get_all_edges(self) -> list[dict]:
        if await self._has_pending_graph_writes():
            await self._flush_pending_graph_writes()

        rows = await self._exec(
            f"MATCH ()-[r:{self.EDGE_TYPE}]->() "
            "RETURN r.source_node_id AS source_node_id, "
            "       r.target_node_id AS target_node_id, "
            "       r.payload_json AS payload_json, "
            "       r.relationship AS relationship, "
            "       r.description AS description, "
            "       r.weight AS weight, "
            "       r.keywords AS keywords, "
            "       r.source_id AS source_id, "
            "       r.file_path AS file_path, "
            "       r.created_at AS created_at"
        )

        result = []
        for row in rows:
            src = row.get("source_node_id")
            tgt = row.get("target_node_id")
            if src is None or tgt is None:
                continue

            payload = _decode_payload(row.get("payload_json"))
            payload = _merge_payload_with_props(
                payload,
                row,
                allowed_fields=[
                    "relationship",
                    "description",
                    "weight",
                    "keywords",
                    "source_id",
                    "file_path",
                    "created_at",
                ],
            )
            payload["source"] = str(src)
            payload["target"] = str(tgt)
            payload.setdefault("source_node_id", str(src))
            payload.setdefault("target_node_id", str(tgt))
            result.append(payload)

        return result

    async def get_popular_labels(self, limit: int = 300) -> list[str]:
        if await self._has_pending_graph_writes():
            await self._flush_pending_graph_writes()

        rows = await self._exec(
            f"MATCH (n:{self.NODE_LABEL})-[r:{self.EDGE_TYPE}]-() "
            "RETURN n.entity_id AS entity_id, COUNT(r) AS degree "
            "ORDER BY degree DESC, entity_id ASC "
            "LIMIT $limit",
            {"limit": max(1, int(limit))},
        )
        return [str(row.get("entity_id")) for row in rows if row.get("entity_id") is not None]

    async def search_labels(self, query: str, limit: int = 50) -> list[str]:
        if await self._has_pending_graph_writes():
            await self._flush_pending_graph_writes()

        q = (query or "").strip()
        if not q:
            return []

        rows = await self._exec(
            f"MATCH (n:{self.NODE_LABEL}) "
            "WHERE toLower(n.entity_id) CONTAINS toLower($query) "
            "RETURN n.entity_id AS entity_id "
            "ORDER BY n.entity_id ASC "
            "LIMIT $limit",
            {"query": q, "limit": max(1, int(limit))},
        )
        return [str(row.get("entity_id")) for row in rows if row.get("entity_id") is not None]

# -----------------------------
# Vector storage
# -----------------------------


@final
@dataclass
class GrafeoVectorStorage(_GrafeoStorageMixin, BaseVectorStorage):
    db: Any = field(default=None)

    VECTOR_LABEL: str = field(default="LightragVector", init=False)
    ID_FIELD: str = field(default="doc_id", init=False)

    

    def __init__(self, namespace, global_config, embedding_func, workspace=None, meta_fields=None):
        super().__init__(
            namespace=namespace,
            workspace=workspace or "",
            global_config=global_config,
            embedding_func=embedding_func,
            meta_fields=meta_fields or set(),
        )
        self._validate_embedding_func()
        kwargs = self.global_config.get("vector_db_storage_cls_kwargs", {})
        threshold = kwargs.get("cosine_better_than_threshold")
        if threshold is not None:
            self.cosine_better_than_threshold = threshold
        self._setup_grafeo_storage(self.VECTOR_LABEL)
        self._max_batch_size = int(self.global_config.get("embedding_batch_num", 32))
        self._vector_index_dirty = True

    async def initialize(self):
        async with get_data_init_lock():
            await self._open_db()
            dim = int(self.embedding_func.embedding_dim)
            try:
                await self._run_sync(self.db.create_vector_index, self.VECTOR_LABEL, "embedding", dim)
            except Exception:
                pass
            try:
                await self._run_sync(self.db.create_text_index, self.VECTOR_LABEL, "content")
            except Exception:
                pass
            try:
                await self._run_sync(self.db.create_property_index, self.ID_FIELD)
            except Exception:
                pass
            for property_name in ("src_id", "tgt_id"):
                try:
                    await self._run_sync(self.db.create_property_index, property_name)
                except Exception:
                    pass

    def _vector_row(self, doc_id: str, data: dict[str, Any], vector: list[float]) -> dict[str, Any]:
        payload = {k: v for k, v in data.items() if k != "vector"}
        row = {
            "doc_id": doc_id,
            "payload_json": _encode_payload(payload),
            "embedding": vector,
        }
        for key, value in payload.items():
            row[key] = _encode_value(value)
        return row

    async def _embed_contents(self, contents: list[str]) -> list[list[float]]:
        batches = [contents[i : i + self._max_batch_size] for i in range(0, len(contents), self._max_batch_size)]
        results = await asyncio.gather(*(self.embedding_func(batch) for batch in batches))
        vectors: list[list[float]] = []
        for batch_result in results:
            for row in batch_result:
                vectors.append(row.tolist() if hasattr(row, "tolist") else list(row))
        return vectors

    def _upsert_vector_rows_sync(self, rows: list[dict[str, Any]]) -> None:
        existing_rows = self._exec_sync(
            f"MATCH (n:{self.VECTOR_LABEL}) "
            f"WHERE n.{self.ID_FIELD} IN $doc_ids "
            f"RETURN n.{self.ID_FIELD} AS doc_id, id(n) AS node_id",
            {"doc_ids": [row["doc_id"] for row in rows]},
        )

        existing = {
            str(row["doc_id"]): row["node_id"]
            for row in existing_rows
            if row.get("doc_id") is not None and row.get("node_id") is not None
        }

        for row in rows:
            doc_id = str(row["doc_id"])
            props = {
                self.ID_FIELD: doc_id,
                "payload_json": row.get("payload_json"),
                "embedding": row.get("embedding"),
                "content": row.get("content"),
                "entity_name": row.get("entity_name"),
                "src_id": row.get("src_id"),
                "tgt_id": row.get("tgt_id"),
                "source_id": row.get("source_id"),
                "description": row.get("description"),
                "entity_type": row.get("entity_type"),
                "keywords": row.get("keywords"),
                "weight": row.get("weight"),
                "file_path": row.get("file_path"),
                "full_doc_id": row.get("full_doc_id"),
                "tokens": row.get("tokens"),
                "chunk_order_index": row.get("chunk_order_index"),
            }

            node_id = existing.get(doc_id)
            if node_id is None:
                self.db.create_node([self.VECTOR_LABEL], props)
            else:
                for key, value in props.items():
                    self.db.set_node_property(node_id, key, value)

    async def upsert(self, data: dict[str, dict[str, Any]]) -> None:
        if not data:
            return
        doc_ids = list(data.keys())
        contents = [str(data[doc_id].get("content", "") or "") for doc_id in doc_ids]
        embeddings = await self._embed_contents(contents)
        rows: list[dict[str, Any]] = []
        for idx, doc_id in enumerate(doc_ids):
            rows.append(self._vector_row(doc_id, data[doc_id], embeddings[idx]))
        await self._run_sync(self._upsert_vector_rows_sync, rows)

    def _hydrate_vector_hits_sync(self, node_ids: list[Any]) -> dict[Any, dict[str, Any]]:
        if not node_ids:
            return {}
        rows = self._exec_sync(
            f"MATCH (n:{self.VECTOR_LABEL}) WHERE id(n) IN $node_ids "
            "RETURN id(n) AS node_id, "
            f"       n.{self.ID_FIELD} AS doc_id, "
            "       n.payload_json AS payload_json",
            {"node_ids": list(node_ids)},
        )
        hydrated: dict[Any, dict[str, Any]] = {}
        for row in rows:
            node_id = row.get("node_id")
            doc_id = row.get("doc_id")
            if node_id is None or doc_id is None:
                continue
            payload = _decode_payload(row.get("payload_json"))
            payload["id"] = doc_id
            hydrated[node_id] = payload
        return hydrated

    async def export_data(self, *args, **kwargs) -> list[dict[str, Any]]:
        rows = await self._exec(
            f"MATCH (n:{self.VECTOR_LABEL}) "
            f"RETURN n.{self.ID_FIELD} AS doc_id, "
            "       n.payload_json AS payload_json, "
            "       n.embedding AS embedding"
        )
        exported: list[dict[str, Any]] = []
        for row in rows:
            doc_id = row.get("doc_id")
            if doc_id is None:
                continue
            payload = _decode_payload(row.get("payload_json"))
            payload["id"] = doc_id
            if row.get("embedding") is not None:
                payload["vector"] = list(row.get("embedding"))
            exported.append(payload)
        return exported

    def _is_entity_namespace(self) -> bool:
        ns = str(getattr(self, "namespace", "") or "").lower()
        return "entity" in ns and "relation" not in ns
    
    async def index_done_callback(self) -> None:
        if self._vector_index_dirty:
            await self._run_sync(
                self.db.rebuild_vector_index,
                self.VECTOR_LABEL,
                "embedding",
            )
            self._vector_index_dirty = False
        await super().index_done_callback()

    async def query(
        self, query: str, top_k: int, query_embedding: list[float] = None
    ) -> list[dict[str, Any]]:
        wanted = max(1, int(top_k))

        if query_embedding is None:
            embedding_batch = await self.embedding_func([query], _priority=5)
            if len(embedding_batch) == 0:
                return []
            raw_query_vector = embedding_batch[0]
        else:
            raw_query_vector = query_embedding

        query_vector = _to_1d_float_list(raw_query_vector)
        if not query_vector:
            return []

        # Keep this only if Grafeo expects normalized cosine vectors.
        # If your stored embeddings are already normalized and query embeddings are too,
        # this is still harmless.
        normalized = _normalize_vector(query_vector)
        if not normalized:
            return []

        try:
            native_hits = await self._run_sync(
                self.db.vector_search,
                self.VECTOR_LABEL,
                "embedding",
                normalized,
                wanted,
            )
            native_hits = list(native_hits or [])
        except Exception:
            return []

        if not native_hits:
            return []

        node_ids: list[Any] = []
        scores_by_node_id: dict[Any, float] = {}

        for node_id, score in native_hits:
            if node_id in scores_by_node_id:
                continue
            node_ids.append(node_id)
            scores_by_node_id[node_id] = float(score)

        hydrated = await self._run_sync(self._hydrate_vector_hits_sync, node_ids)
        if not hydrated:
            return []

        results: list[dict[str, Any]] = []
        for node_id in node_ids:
            payload = hydrated.get(node_id)
            if payload is None:
                payload = hydrated.get(str(node_id))
            if payload is None:
                continue

            row = dict(payload)
            score = scores_by_node_id.get(node_id)

            # Grafeo vector_search often returns a distance-like value.
            # If in your build it already returns cosine similarity, remove the 1.0 - ...
            if score is not None:
                row["distance"] = 1.0 - score

            results.append(row)

        return results[:wanted]

    async def get_by_id(self, id: str) -> dict[str, Any] | None:
        rows = await self._exec(
            f"MATCH (n:{self.VECTOR_LABEL}) "
            f"WHERE n.{self.ID_FIELD} = $doc_id "
            f"RETURN n.{self.ID_FIELD} AS doc_id, n.payload_json AS payload_json "
            "LIMIT 1",
            {"doc_id": str(id)},
        )
        if not rows:
            return None
        row = rows[0]
        payload = _decode_payload(row.get("payload_json"))
        payload["id"] = row.get("doc_id")
        return payload

    async def get_by_ids(self, ids: list[str]) -> list[dict[str, Any]]:
        if not ids:
            return []
        rows = await self._exec(
            f"UNWIND $requested_ids AS requested_id "
            f"MATCH (n:{self.VECTOR_LABEL}) "
            f"WHERE n.{self.ID_FIELD} = requested_id "
            "RETURN requested_id, "
            f"       n.{self.ID_FIELD} AS doc_id, "
            "       n.payload_json AS payload_json",
            {"requested_ids": [str(x) for x in ids]},
        )
        by_requested_id: dict[str, dict[str, Any]] = {}
        for row in rows:
            requested_id = row.get("requested_id")
            if requested_id is None:
                continue
            payload = _decode_payload(row.get("payload_json"))
            payload["id"] = row.get("doc_id")
            by_requested_id[str(requested_id)] = payload
        return [by_requested_id[id] for id in ids if id in by_requested_id]

    async def get_vectors_by_ids(self, ids: list[str]) -> dict[str, list[float]]:
        if not ids:
            return {}
        rows = await self._exec(
            f"UNWIND $requested_ids AS requested_id "
            f"MATCH (n:{self.VECTOR_LABEL}) "
            f"WHERE n.{self.ID_FIELD} = requested_id AND n.embedding IS NOT NULL "
            "RETURN requested_id, n.embedding AS embedding",
            {"requested_ids": list(dict.fromkeys(str(x) for x in ids))},
        )
        result: dict[str, list[float]] = {}
        for row in rows:
            requested_id = row.get("requested_id")
            embedding = row.get("embedding")
            if requested_id is None or embedding is None:
                continue
            result[str(requested_id)] = list(embedding)
        return result

    async def delete(self, ids: list[str]):
        if not ids:
            return
        unique_ids = list(dict.fromkeys(str(x) for x in ids))
        await self._exec(
            f"MATCH (n:{self.VECTOR_LABEL}) "
            f"WHERE n.{self.ID_FIELD} IN $doc_ids "
            "DETACH DELETE n",
            {"doc_ids": unique_ids},
        )
        self._vector_index_dirty = True

    async def delete_entity(self, entity_name: str) -> None:
        entity_id = compute_mdhash_id(entity_name, prefix="ent-")
        await self.delete([entity_id])

    async def delete_entity_relation(self, entity_name: str) -> None:
        await self._exec(
            f"MATCH (n:{self.VECTOR_LABEL}) "
            "WHERE n.src_id = $entity_name OR n.tgt_id = $entity_name "
            "DETACH DELETE n",
            {"entity_name": entity_name},
        )


# -----------------------------
# Backwards-friendly aliases
# -----------------------------

GrafeoGraphDBStorage = GrafeoGraphStorage
GrafeoVectorDBStorage = GrafeoVectorStorage
