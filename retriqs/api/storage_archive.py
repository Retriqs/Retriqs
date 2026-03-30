from __future__ import annotations

import copy
import hashlib
import json
import os
import pickle
import shutil
import tempfile
import uuid
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Literal

import networkx as nx
from fastapi import HTTPException


ARCHIVE_VERSION = 2
ARCHIVE_MANIFEST_NAME = "storage_archive_manifest.json"
ARCHIVE_LEGACY_MANIFEST_NAME = "storage_archive_manifest"
ARCHIVE_MAX_SIZE_BYTES = 512 * 1024 * 1024
ARCHIVE_RESERVED_METADATA_FILES = {
    ARCHIVE_MANIFEST_NAME,
    ARCHIVE_LEGACY_MANIFEST_NAME,
}

FILE_BASED_STORAGE_REQUIREMENTS = {
    "LIGHTRAG_GRAPH_STORAGE": "NetworkXStorage",
    "LIGHTRAG_KV_STORAGE": "JsonKVStorage",
    "LIGHTRAG_DOC_STATUS_STORAGE": "JsonDocStatusStorage",
    "LIGHTRAG_VECTOR_STORAGE": "NanoVectorDBStorage",
}

REQUIRED_ARCHIVE_FILES = [
    "bm25_chunks.pkl",
    "bm25_entities.pkl",
    "bm25_relationships.pkl",
    "graph_chunk_entity_relation.graphml",
    "kv_store_doc_status.json",
    "kv_store_full_docs.json",
    "kv_store_text_chunks.json",
    "kv_store_llm_response_cache.json",
    "vdb_chunks.json",
    "vdb_entities.json",
    "vdb_relationships.json",
]
BM25_ARCHIVE_FILES = [
    "bm25_chunks.pkl",
    "bm25_entities.pkl",
    "bm25_relationships.pkl",
]
BM25_EMPTY_INDEX = {"ids": [], "tokenized_corpus": []}

REQUIRED_SETTING_KEYS = [
    "LLM_BINDING",
    "LLM_MODEL",
    "EMBEDDING_BINDING",
    "EMBEDDING_MODEL",
    "EMBEDDING_DIM",
    "LIGHTRAG_GRAPH_STORAGE",
    "LIGHTRAG_KV_STORAGE",
    "LIGHTRAG_DOC_STATUS_STORAGE",
    "LIGHTRAG_VECTOR_STORAGE",
]

MERGE_ANALYSIS_TTL_SECONDS = 60 * 15
SET_LIKE_LIST_FIELDS = {"chunks_list", "llm_cache_list"}
SENSITIVE_EXPORT_SETTING_MARKERS = ("API_KEY",)
JSON_NAMESPACE_SPECS = {
    "kv_store_full_docs.json": {"type": "dict"},
    "kv_store_doc_status.json": {"type": "dict"},
    "kv_store_text_chunks.json": {"type": "dict"},
    "kv_store_full_entities.json": {"type": "dict"},
    "kv_store_full_relations.json": {"type": "dict"},
    "kv_store_entity_chunks.json": {"type": "dict"},
    "kv_store_relation_chunks.json": {"type": "dict"},
    "kv_store_llm_response_cache.json": {"type": "dict"},
    "vdb_chunks.json": {"type": "vdb"},
    "vdb_entities.json": {"type": "vdb"},
    "vdb_relationships.json": {"type": "vdb"},
}
GRAPH_FILE_NAME = "graph_chunk_entity_relation.graphml"
MERGE_COMPATIBILITY_KEYS = [
    "EMBEDDING_BINDING",
    "EMBEDDING_MODEL",
    "EMBEDDING_DIM",
    "LIGHTRAG_GRAPH_STORAGE",
    "LIGHTRAG_KV_STORAGE",
    "LIGHTRAG_DOC_STATUS_STORAGE",
    "LIGHTRAG_VECTOR_STORAGE",
]

ConflictMode = Literal["archive_wins", "keep_existing"]


class StorageArchiveError(ValueError):
    pass


@dataclass(frozen=True)
class StorageArchiveManifest:
    archive_version: int
    storage_name: str
    exported_at: str
    backend_scope: str
    required_files: list[str]
    storage_settings: dict[str, str]
    source_storage_id: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "archive_version": self.archive_version,
            "storage_name": self.storage_name,
            "source_storage_id": self.source_storage_id,
            "exported_at": self.exported_at,
            "backend_scope": self.backend_scope,
            "required_files": self.required_files,
            "storage_settings": self.storage_settings,
        }


@dataclass
class MergeNamespaceResult:
    additions: int = 0
    no_ops: int = 0
    conflicts: int = 0


@dataclass
class MergeAnalysisRecord:
    analysis_id: str
    storage_id: int
    created_at: float
    extracted_dir: str
    fingerprint: dict[str, Any]
    archive_manifest: StorageArchiveManifest
    summary: dict[str, Any]
    blocking_issues: list[str]
    conflicts: list[dict[str, Any]]


_MERGE_ANALYSIS_REGISTRY: dict[str, MergeAnalysisRecord] = {}


def normalize_storage_settings(storage_settings: list[Any] | dict[str, Any]) -> dict[str, str]:
    if isinstance(storage_settings, dict):
        items = storage_settings.items()
    else:
        items = ((setting.key, setting.value) for setting in storage_settings)
    return {str(key).upper(): "" if value is None else str(value) for key, value in items}


def sanitize_exported_storage_settings(settings: dict[str, str]) -> dict[str, str]:
    return {
        key: value
        for key, value in settings.items()
        if not any(marker in key for marker in SENSITIVE_EXPORT_SETTING_MARKERS)
    }


def validate_file_based_storage_settings(settings: dict[str, str]) -> None:
    for key, expected in FILE_BASED_STORAGE_REQUIREMENTS.items():
        if settings.get(key) != expected:
            raise StorageArchiveError(
                f"Storage archives only support file-based backends. Expected {key}={expected}."
            )


def validate_required_archive_settings(settings: dict[str, str]) -> None:
    missing = [key for key in REQUIRED_SETTING_KEYS if not settings.get(key)]
    if missing:
        raise StorageArchiveError(
            f"Archive is missing required storage settings: {', '.join(sorted(missing))}"
        )

    embedding_dim = settings.get("EMBEDDING_DIM", "").strip()
    try:
        if int(embedding_dim) <= 0:
            raise ValueError
    except ValueError as exc:
        raise StorageArchiveError("Archive EMBEDDING_DIM must be a positive integer") from exc


def _validate_required_storage_files(storage_dir: str) -> None:
    base_dir = Path(storage_dir)
    if not base_dir.is_dir():
        raise StorageArchiveError(f"Storage directory does not exist: {storage_dir}")

    # Older storages may predate relationship indexing and miss one or more BM25 files.
    # Backfill those files with an empty index so export can remain backward compatible.
    for bm25_file in BM25_ARCHIVE_FILES:
        bm25_path = base_dir / PurePosixPath(bm25_file)
        if bm25_path.is_file():
            continue
        bm25_path.parent.mkdir(parents=True, exist_ok=True)
        with open(bm25_path, "wb") as handle:
            pickle.dump(BM25_EMPTY_INDEX, handle, protocol=pickle.HIGHEST_PROTOCOL)

    missing_files = [
        required_file
        for required_file in REQUIRED_ARCHIVE_FILES
        if not (base_dir / PurePosixPath(required_file)).is_file()
    ]
    if missing_files:
        raise StorageArchiveError(
            f"Storage is missing required archive files: {', '.join(sorted(missing_files))}"
        )


def build_archive_manifest(
    storage: Any,
    storage_settings: list[Any] | dict[str, Any],
    storage_dir: str,
) -> StorageArchiveManifest:
    normalized_settings = normalize_storage_settings(storage_settings)
    validate_file_based_storage_settings(normalized_settings)
    validate_required_archive_settings(normalized_settings)
    _validate_required_storage_files(storage_dir)
    export_settings = sanitize_exported_storage_settings(normalized_settings)
    return StorageArchiveManifest(
        archive_version=ARCHIVE_VERSION,
        storage_name=str(storage.name),
        source_storage_id=getattr(storage, "id", None),
        exported_at=datetime.now(timezone.utc).isoformat(),
        backend_scope="file-based",
        required_files=list(REQUIRED_ARCHIVE_FILES),
        storage_settings=export_settings,
    )


def _validate_archive_member_path(name: str) -> str:
    normalized = name.replace("\\", "/")
    path = PurePosixPath(normalized)
    if not normalized or normalized.endswith("/"):
        return normalized
    if path.is_absolute() or ".." in path.parts:
        raise StorageArchiveError(f"Unsafe archive entry detected: {name}")
    return normalized


def create_storage_archive(storage_dir: str, manifest: StorageArchiveManifest) -> str:
    source_dir = Path(storage_dir)
    if not source_dir.is_dir():
        raise StorageArchiveError(f"Storage directory does not exist: {storage_dir}")

    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
    temp_file.close()

    try:
        with zipfile.ZipFile(temp_file.name, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(
                ARCHIVE_MANIFEST_NAME,
                json.dumps(manifest.to_dict(), indent=2, sort_keys=True),
            )
            for path in sorted(source_dir.rglob("*")):
                if path.is_dir():
                    continue
                relative_path = path.relative_to(source_dir).as_posix()
                if relative_path in ARCHIVE_RESERVED_METADATA_FILES:
                    continue
                archive.write(path, relative_path)
        return temp_file.name
    except Exception:
        if os.path.exists(temp_file.name):
            os.unlink(temp_file.name)
        raise


def load_archive_manifest(archive: zipfile.ZipFile) -> StorageArchiveManifest:
    try:
        raw_manifest = archive.read(ARCHIVE_MANIFEST_NAME)
    except KeyError as exc:
        raise StorageArchiveError("Archive manifest is missing") from exc

    try:
        payload = json.loads(raw_manifest)
    except json.JSONDecodeError as exc:
        raise StorageArchiveError("Archive manifest is not valid JSON") from exc

    if payload.get("archive_version") not in (1, ARCHIVE_VERSION):
        raise StorageArchiveError(
            f"Unsupported archive version: {payload.get('archive_version')}"
        )
    if payload.get("backend_scope") != "file-based":
        raise StorageArchiveError("Only file-based storage archives are supported")

    settings = normalize_storage_settings(payload.get("storage_settings", {}))
    validate_file_based_storage_settings(settings)
    validate_required_archive_settings(settings)

    required_files = payload.get("required_files") or []
    if not isinstance(required_files, list) or not all(
        isinstance(entry, str) for entry in required_files
    ):
        raise StorageArchiveError("Archive manifest required_files is invalid")

    return StorageArchiveManifest(
        archive_version=payload["archive_version"],
        storage_name=str(payload.get("storage_name") or ""),
        source_storage_id=payload.get("source_storage_id"),
        exported_at=str(payload.get("exported_at") or ""),
        backend_scope=str(payload.get("backend_scope") or ""),
        required_files=required_files,
        storage_settings=settings,
    )


def validate_archive_structure(archive: zipfile.ZipFile) -> StorageArchiveManifest:
    manifest = load_archive_manifest(archive)
    names = set()
    for info in archive.infolist():
        normalized = _validate_archive_member_path(info.filename)
        if info.file_size < 0:
            raise StorageArchiveError(f"Archive entry has invalid size: {info.filename}")
        names.add(normalized)

    missing_files = sorted(
        required_file for required_file in manifest.required_files if required_file not in names
    )
    if missing_files:
        raise StorageArchiveError(
            f"Archive is missing required storage files: {', '.join(missing_files)}"
        )

    return manifest


def extract_storage_archive(
    archive_path: str,
    target_dir: str,
    exclude_files: set[str] | None = None,
) -> StorageArchiveManifest:
    destination = Path(target_dir)
    destination.mkdir(parents=True, exist_ok=True)
    excluded = set(exclude_files or set())

    with zipfile.ZipFile(archive_path, "r") as archive:
        manifest = validate_archive_structure(archive)
        for info in archive.infolist():
            normalized = _validate_archive_member_path(info.filename)
            if not normalized or normalized.endswith("/"):
                continue
            if normalized in ARCHIVE_RESERVED_METADATA_FILES:
                continue
            if normalized in excluded:
                continue

            target_path = (destination / PurePosixPath(normalized)).resolve()
            if not str(target_path).startswith(str(destination.resolve())):
                raise StorageArchiveError(f"Unsafe archive entry detected: {info.filename}")

            target_path.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info, "r") as source, open(target_path, "wb") as target:
                shutil.copyfileobj(source, target)

    return manifest


def enforce_archive_upload_size(size_bytes: int) -> None:
    if size_bytes <= 0:
        raise StorageArchiveError("Archive upload is empty")
    if size_bytes > ARCHIVE_MAX_SIZE_BYTES:
        raise StorageArchiveError(
            f"Archive exceeds the maximum size of {ARCHIVE_MAX_SIZE_BYTES // (1024 * 1024)} MB"
        )


def _json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return value.as_posix()
    raise TypeError(f"Unsupported value for JSON serialization: {type(value)!r}")


def _normalize_scalar(value: Any) -> Any:
    if isinstance(value, Path):
        return value.as_posix()
    return value


def normalize_payload(value: Any, parent_key: str | None = None) -> Any:
    if isinstance(value, dict):
        return {
            str(key): normalize_payload(item, str(key))
            for key, item in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, list):
        items = [normalize_payload(item, parent_key) for item in value]
        if parent_key in SET_LIKE_LIST_FIELDS:
            return sorted(items, key=lambda item: json.dumps(item, sort_keys=True, default=_json_default))
        return items
    return _normalize_scalar(value)


def merge_payload(target_value: Any, archive_value: Any, parent_key: str | None = None) -> Any:
    if isinstance(target_value, dict) and isinstance(archive_value, dict):
        merged = copy.deepcopy(target_value)
        for key, value in archive_value.items():
            if key not in merged:
                merged[key] = copy.deepcopy(value)
                continue

            if (
                key in SET_LIKE_LIST_FIELDS
                and isinstance(merged[key], list)
                and isinstance(value, list)
            ):
                merged[key] = merge_payload(merged[key], value, key)
                continue

            if isinstance(merged[key], dict) and isinstance(value, dict):
                merged[key] = merge_payload(merged[key], value, key)
        return merged

    if isinstance(target_value, list) and isinstance(archive_value, list):
        archive_normalized = normalize_payload(archive_value)
        target_normalized = normalize_payload(target_value)
        if archive_normalized == target_normalized:
            return copy.deepcopy(target_value)

        if parent_key not in SET_LIKE_LIST_FIELDS:
            return copy.deepcopy(target_value)

        seen: set[str] = set()
        combined: list[Any] = []
        for item in target_value + archive_value:
            marker = json.dumps(normalize_payload(item), sort_keys=True, default=_json_default)
            if marker not in seen:
                seen.add(marker)
                combined.append(copy.deepcopy(item))
        return combined

    return copy.deepcopy(archive_value)


def _compare_keyed_payloads(
    target_records: dict[str, Any],
    archive_records: dict[str, Any],
    namespace: str,
) -> tuple[MergeNamespaceResult, list[dict[str, Any]]]:
    result = MergeNamespaceResult()
    conflicts: list[dict[str, Any]] = []

    for key in sorted(archive_records):
        archive_value = archive_records[key]
        if key not in target_records:
            result.additions += 1
            continue

        target_value = target_records[key]
        target_normalized = normalize_payload(target_value)
        archive_normalized = normalize_payload(archive_value)
        if target_normalized == archive_normalized:
            result.no_ops += 1
            continue

        merged_target = normalize_payload(merge_payload(target_value, archive_value))
        if merged_target == archive_normalized:
            result.no_ops += 1
            continue

        result.conflicts += 1
        conflicts.append(
            {
                "namespace": namespace,
                "key": key,
                "target_preview": target_normalized,
                "archive_preview": archive_normalized,
            }
        )

    return result, conflicts


def _load_json_file(path: Path) -> Any:
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _save_json_file(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)


def _load_namespace_records(storage_dir: Path, filename: str) -> tuple[dict[str, Any], Any]:
    payload = _load_json_file(storage_dir / filename)
    if payload is None:
        if JSON_NAMESPACE_SPECS[filename]["type"] == "vdb":
            return {}, {"embedding_dim": 0, "data": []}
        return {}, {}

    namespace_type = JSON_NAMESPACE_SPECS[filename]["type"]
    if namespace_type == "dict":
        if not isinstance(payload, dict):
            raise StorageArchiveError(f"{filename} must contain a JSON object")
        return payload, payload

    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise StorageArchiveError(f"{filename} must contain an object with a data list")

    records: dict[str, Any] = {}
    for item in payload["data"]:
        if not isinstance(item, dict) or not item.get("__id__"):
            raise StorageArchiveError(f"{filename} contains an invalid vector record")
        records[str(item["__id__"])] = item
    return records, payload


def _apply_json_namespace_merge(
    target_dir: Path,
    archive_dir: Path,
    filename: str,
    conflict_mode: ConflictMode,
) -> MergeNamespaceResult:
    target_records, target_payload = _load_namespace_records(target_dir, filename)
    archive_records, archive_payload = _load_namespace_records(archive_dir, filename)
    result, _ = _compare_keyed_payloads(target_records, archive_records, filename)

    for key, archive_value in archive_records.items():
        if key not in target_records:
            target_records[key] = copy.deepcopy(archive_value)
            continue

        target_value = target_records[key]
        if normalize_payload(target_value) == normalize_payload(archive_value):
            continue

        merged_target = merge_payload(target_value, archive_value)
        if normalize_payload(merged_target) == normalize_payload(archive_value):
            target_records[key] = merged_target
            continue

        if conflict_mode == "archive_wins":
            target_records[key] = copy.deepcopy(archive_value)

    if JSON_NAMESPACE_SPECS[filename]["type"] == "dict":
        _save_json_file(target_dir / filename, target_records)
        return result

    if archive_payload.get("embedding_dim") and (
        not target_payload.get("embedding_dim")
        or int(target_payload.get("embedding_dim", 0)) != int(archive_payload["embedding_dim"])
    ):
        target_payload["embedding_dim"] = archive_payload["embedding_dim"]

    target_payload["data"] = [target_records[key] for key in sorted(target_records)]

    # Handle NanoVectorDB matrix reconstruction for 'vdb' type
    if JSON_NAMESPACE_SPECS[filename]["type"] == "vdb":
        import numpy as np
        import zlib
        import base64

        vectors = []
        dim = int(target_payload.get("embedding_dim", 0))
        for item in target_payload["data"]:
            if "vector" in item:
                try:
                    decoded = base64.b64decode(item["vector"])
                    decompressed = zlib.decompress(decoded)
                    vector = np.frombuffer(decompressed, dtype=np.float16).astype(np.float32)
                    if len(vector) == dim:
                        vectors.append(vector)
                    else:
                        vectors.append(np.zeros(dim, dtype=np.float32))
                except Exception:
                    vectors.append(np.zeros(dim, dtype=np.float32))
            else:
                vectors.append(np.zeros(dim, dtype=np.float32))

        if vectors:
            matrix = np.vstack(vectors)
        else:
            matrix = np.array([], dtype=np.float32).reshape(0, dim)

        target_payload["matrix"] = base64.b64encode(matrix.astype(np.float32).tobytes()).decode()

    _save_json_file(target_dir / filename, target_payload)
    return result



def _graph_node_key(node: tuple[Any, dict[str, Any]]) -> str:
    return str(node[0])


def _graph_edge_key(edge: tuple[Any, Any, dict[str, Any]]) -> str:
    return f"{edge[0]}->{edge[1]}"


def _load_graph(storage_dir: Path) -> nx.Graph:
    path = storage_dir / GRAPH_FILE_NAME
    if not path.exists():
        return nx.Graph()
    return nx.read_graphml(path)


def _compare_graphs(target_dir: Path, archive_dir: Path) -> tuple[MergeNamespaceResult, list[dict[str, Any]]]:
    target_graph = _load_graph(target_dir)
    archive_graph = _load_graph(archive_dir)
    result = MergeNamespaceResult()
    conflicts: list[dict[str, Any]] = []

    target_nodes = {str(node): normalize_payload(dict(attrs)) for node, attrs in target_graph.nodes(data=True)}
    archive_nodes = {str(node): normalize_payload(dict(attrs)) for node, attrs in archive_graph.nodes(data=True)}
    node_result, node_conflicts = _compare_keyed_payloads(target_nodes, archive_nodes, f"{GRAPH_FILE_NAME}:nodes")
    result.additions += node_result.additions
    result.no_ops += node_result.no_ops
    result.conflicts += node_result.conflicts
    conflicts.extend(node_conflicts)

    target_edges = {
        _graph_edge_key((src, dst, attrs)): normalize_payload(dict(attrs))
        for src, dst, attrs in target_graph.edges(data=True)
    }
    archive_edges = {
        _graph_edge_key((src, dst, attrs)): normalize_payload(dict(attrs))
        for src, dst, attrs in archive_graph.edges(data=True)
    }
    edge_result, edge_conflicts = _compare_keyed_payloads(target_edges, archive_edges, f"{GRAPH_FILE_NAME}:edges")
    result.additions += edge_result.additions
    result.no_ops += edge_result.no_ops
    result.conflicts += edge_result.conflicts
    conflicts.extend(edge_conflicts)
    return result, conflicts


def _apply_graph_merge(target_dir: Path, archive_dir: Path, conflict_mode: ConflictMode) -> MergeNamespaceResult:
    target_graph = _load_graph(target_dir)
    archive_graph = _load_graph(archive_dir)
    result, _ = _compare_graphs(target_dir, archive_dir)

    for node_id, attrs in archive_graph.nodes(data=True):
        node_id_str = str(node_id)
        archive_attrs = dict(attrs)
        if not target_graph.has_node(node_id_str):
            target_graph.add_node(node_id_str, **archive_attrs)
            continue

        target_attrs = dict(target_graph.nodes[node_id_str])
        merged_target = merge_payload(target_attrs, archive_attrs)
        if normalize_payload(merged_target) == normalize_payload(archive_attrs):
            target_graph.nodes[node_id_str].update(merged_target)
            continue

        if conflict_mode == "archive_wins":
            target_graph.nodes[node_id_str].clear()
            target_graph.nodes[node_id_str].update(copy.deepcopy(archive_attrs))

    for src, dst, attrs in archive_graph.edges(data=True):
        src_str = str(src)
        dst_str = str(dst)
        archive_attrs = dict(attrs)
        if not target_graph.has_edge(src_str, dst_str):
            target_graph.add_edge(src_str, dst_str, **archive_attrs)
            continue

        target_attrs = dict(target_graph.get_edge_data(src_str, dst_str) or {})
        merged_target = merge_payload(target_attrs, archive_attrs)
        if normalize_payload(merged_target) == normalize_payload(archive_attrs):
            target_graph[src_str][dst_str].clear()
            target_graph[src_str][dst_str].update(merged_target)
            continue

        if conflict_mode == "archive_wins":
            target_graph[src_str][dst_str].clear()
            target_graph[src_str][dst_str].update(copy.deepcopy(archive_attrs))

    graph_path = target_dir / GRAPH_FILE_NAME
    graph_path.parent.mkdir(parents=True, exist_ok=True)
    nx.write_graphml(target_graph, graph_path)
    return result


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _list_relative_files(base_dir: Path, relative_root: str = "") -> dict[str, str]:
    root = base_dir / relative_root if relative_root else base_dir
    if not root.exists():
        return {}

    files: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            relative = path.relative_to(base_dir).as_posix()
            files[relative] = _hash_file(path)
    return files


def _compare_input_files(target_dir: Path, archive_dir: Path) -> tuple[MergeNamespaceResult, list[dict[str, Any]]]:
    target_files = _list_relative_files(target_dir, "input")
    archive_files = _list_relative_files(archive_dir, "input")
    result = MergeNamespaceResult()
    conflicts: list[dict[str, Any]] = []

    for relative_path, archive_hash in archive_files.items():
        if relative_path not in target_files:
            result.additions += 1
            continue
        if target_files[relative_path] == archive_hash:
            result.no_ops += 1
            continue
        result.conflicts += 1
        conflicts.append(
            {
                "namespace": "input",
                "key": relative_path,
                "target_preview": target_files[relative_path],
                "archive_preview": archive_hash,
            }
        )
    return result, conflicts


def _apply_input_merge(target_dir: Path, archive_dir: Path, conflict_mode: ConflictMode) -> MergeNamespaceResult:
    result, _ = _compare_input_files(target_dir, archive_dir)
    archive_files = _list_relative_files(archive_dir, "input")
    target_files = _list_relative_files(target_dir, "input")

    for relative_path in archive_files:
        archive_path = archive_dir / PurePosixPath(relative_path)
        target_path = target_dir / PurePosixPath(relative_path)
        if relative_path not in target_files or conflict_mode == "archive_wins":
            target_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(archive_path, target_path)

    return result


def _compare_binary_files(
    target_dir: Path,
    archive_dir: Path,
    filenames: list[str],
    namespace: str,
) -> tuple[MergeNamespaceResult, list[dict[str, Any]]]:
    result = MergeNamespaceResult()
    conflicts: list[dict[str, Any]] = []

    for filename in filenames:
        archive_path = archive_dir / PurePosixPath(filename)
        target_path = target_dir / PurePosixPath(filename)
        archive_exists = archive_path.is_file()
        target_exists = target_path.is_file()

        if not archive_exists:
            continue
        if not target_exists:
            result.additions += 1
            continue

        archive_hash = _hash_file(archive_path)
        target_hash = _hash_file(target_path)
        if archive_hash == target_hash:
            result.no_ops += 1
            continue

        result.conflicts += 1
        conflicts.append(
            {
                "namespace": namespace,
                "key": filename,
                "target_preview": target_hash,
                "archive_preview": archive_hash,
            }
        )

    return result, conflicts


def _apply_binary_file_merge(
    target_dir: Path,
    archive_dir: Path,
    filenames: list[str],
    conflict_mode: ConflictMode,
    namespace: str,
) -> MergeNamespaceResult:
    result, _ = _compare_binary_files(target_dir, archive_dir, filenames, namespace)

    for filename in filenames:
        archive_path = archive_dir / PurePosixPath(filename)
        target_path = target_dir / PurePosixPath(filename)
        if not archive_path.is_file():
            continue
        if not target_path.exists() or conflict_mode == "archive_wins":
            target_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(archive_path, target_path)

    return result


def _build_storage_fingerprint(storage_dir: str) -> dict[str, Any]:
    base_dir = Path(storage_dir)
    files = {
        relative_path: digest
        for relative_path, digest in _list_relative_files(base_dir).items()
        if relative_path != ARCHIVE_MANIFEST_NAME
    }
    return {
        "storage_dir": str(base_dir.resolve()),
        "files": files,
    }


def _ensure_storage_unchanged(storage_dir: str, expected_fingerprint: dict[str, Any]) -> None:
    current_fingerprint = _build_storage_fingerprint(storage_dir)
    if current_fingerprint != expected_fingerprint:
        raise StorageArchiveError(
            "Target storage changed after analysis. Run analyze again before applying the merge."
        )


def cleanup_expired_merge_analyses() -> None:
    now = datetime.now(timezone.utc).timestamp()
    expired_ids = [
        analysis_id
        for analysis_id, record in _MERGE_ANALYSIS_REGISTRY.items()
        if (now - record.created_at) > MERGE_ANALYSIS_TTL_SECONDS
    ]
    for analysis_id in expired_ids:
        cleanup_merge_analysis(analysis_id)


def cleanup_merge_analysis(analysis_id: str) -> None:
    record = _MERGE_ANALYSIS_REGISTRY.pop(analysis_id, None)
    if record and os.path.isdir(record.extracted_dir):
        shutil.rmtree(record.extracted_dir, ignore_errors=True)


def get_merge_analysis_record(analysis_id: str) -> MergeAnalysisRecord:
    cleanup_expired_merge_analyses()
    record = _MERGE_ANALYSIS_REGISTRY.get(analysis_id)
    if not record:
        raise StorageArchiveError("Merge analysis not found or expired")
    return record


def _build_blocking_issues(
    target_settings: dict[str, str],
    archive_settings: dict[str, str],
) -> list[str]:
    blocking_issues: list[str] = []
    for key in MERGE_COMPATIBILITY_KEYS:
        if target_settings.get(key, "") != archive_settings.get(key, ""):
            blocking_issues.append(
                f"Incompatible storage setting for {key}: target={target_settings.get(key, '')!r}, archive={archive_settings.get(key, '')!r}"
            )
    return blocking_issues


def analyze_storage_merge(
    storage_id: int,
    storage_dir: str,
    target_settings: list[Any] | dict[str, Any],
    archive_path: str,
) -> dict[str, Any]:
    cleanup_expired_merge_analyses()
    target_settings_map = normalize_storage_settings(target_settings)
    validate_file_based_storage_settings(target_settings_map)
    validate_required_archive_settings(target_settings_map)

    with zipfile.ZipFile(archive_path, "r") as archive:
        manifest = validate_archive_structure(archive)

    blocking_issues = _build_blocking_issues(target_settings_map, manifest.storage_settings)
    if blocking_issues:
        return {
            "analysis_id": "",
            "target_storage_id": storage_id,
            "archive_manifest": manifest.to_dict(),
            "summary": {
                "additions": 0,
                "no_ops": 0,
                "conflicts": 0,
                "blocking_issues": len(blocking_issues),
                "namespaces": {},
            },
            "blocking_issues": blocking_issues,
            "conflicts": [],
            "samples": [],
        }

    extracted_dir = tempfile.mkdtemp(prefix=f"storage-merge-{storage_id}-")
    try:
        manifest = extract_storage_archive(archive_path, extracted_dir)

        summary = {
            "additions": 0,
            "no_ops": 0,
            "conflicts": 0,
            "blocking_issues": len(blocking_issues),
            "namespaces": {},
        }
        conflicts: list[dict[str, Any]] = []

        target_dir = Path(storage_dir)
        archive_dir = Path(extracted_dir)

        for filename in JSON_NAMESPACE_SPECS:
            target_records, _ = _load_namespace_records(target_dir, filename)
            archive_records, _ = _load_namespace_records(archive_dir, filename)
            namespace_result, namespace_conflicts = _compare_keyed_payloads(
                target_records, archive_records, filename
            )
            summary["namespaces"][filename] = namespace_result.__dict__
            summary["additions"] += namespace_result.additions
            summary["no_ops"] += namespace_result.no_ops
            summary["conflicts"] += namespace_result.conflicts
            conflicts.extend(namespace_conflicts)

        graph_result, graph_conflicts = _compare_graphs(target_dir, archive_dir)
        summary["namespaces"][GRAPH_FILE_NAME] = graph_result.__dict__
        summary["additions"] += graph_result.additions
        summary["no_ops"] += graph_result.no_ops
        summary["conflicts"] += graph_result.conflicts
        conflicts.extend(graph_conflicts)

        input_result, input_conflicts = _compare_input_files(target_dir, archive_dir)
        summary["namespaces"]["input"] = input_result.__dict__
        summary["additions"] += input_result.additions
        summary["no_ops"] += input_result.no_ops
        summary["conflicts"] += input_result.conflicts
        conflicts.extend(input_conflicts)

        bm25_result, bm25_conflicts = _compare_binary_files(
            target_dir,
            archive_dir,
            BM25_ARCHIVE_FILES,
            "bm25",
        )
        summary["namespaces"]["bm25"] = bm25_result.__dict__
        summary["additions"] += bm25_result.additions
        summary["no_ops"] += bm25_result.no_ops
        summary["conflicts"] += bm25_result.conflicts
        conflicts.extend(bm25_conflicts)

        analysis_id = uuid.uuid4().hex
        record = MergeAnalysisRecord(
            analysis_id=analysis_id,
            storage_id=storage_id,
            created_at=datetime.now(timezone.utc).timestamp(),
            extracted_dir=extracted_dir,
            fingerprint=_build_storage_fingerprint(storage_dir),
            archive_manifest=manifest,
            summary=summary,
            blocking_issues=blocking_issues,
            conflicts=conflicts,
        )
        _MERGE_ANALYSIS_REGISTRY[analysis_id] = record

        return {
            "analysis_id": analysis_id,
            "target_storage_id": storage_id,
            "archive_manifest": manifest.to_dict(),
            "summary": summary,
            "blocking_issues": blocking_issues,
            "conflicts": conflicts,
            "samples": conflicts[:10],
        }
    except Exception:
        shutil.rmtree(extracted_dir, ignore_errors=True)
        raise


def apply_storage_merge(
    storage_dir: str,
    analysis_id: str,
    conflict_mode: ConflictMode,
) -> dict[str, Any]:
    if conflict_mode not in {"archive_wins", "keep_existing"}:
        raise StorageArchiveError("conflict_mode must be 'archive_wins' or 'keep_existing'")

    record = get_merge_analysis_record(analysis_id)
    if record.blocking_issues:
        raise StorageArchiveError("Merge has blocking compatibility issues and cannot be applied")

    _ensure_storage_unchanged(storage_dir, record.fingerprint)

    target_dir = Path(storage_dir)
    archive_dir = Path(record.extracted_dir)
    merged_counts = {"additions": 0, "no_ops": 0, "conflicts": 0}

    for filename in JSON_NAMESPACE_SPECS:
        result = _apply_json_namespace_merge(target_dir, archive_dir, filename, conflict_mode)
        merged_counts["additions"] += result.additions
        merged_counts["no_ops"] += result.no_ops
        merged_counts["conflicts"] += result.conflicts

    graph_result = _apply_graph_merge(target_dir, archive_dir, conflict_mode)
    merged_counts["additions"] += graph_result.additions
    merged_counts["no_ops"] += graph_result.no_ops
    merged_counts["conflicts"] += graph_result.conflicts

    input_result = _apply_input_merge(target_dir, archive_dir, conflict_mode)
    merged_counts["additions"] += input_result.additions
    merged_counts["no_ops"] += input_result.no_ops
    merged_counts["conflicts"] += input_result.conflicts

    bm25_result = _apply_binary_file_merge(
        target_dir,
        archive_dir,
        BM25_ARCHIVE_FILES,
        conflict_mode,
        "bm25",
    )
    merged_counts["additions"] += bm25_result.additions
    merged_counts["no_ops"] += bm25_result.no_ops
    merged_counts["conflicts"] += bm25_result.conflicts

    cleanup_merge_analysis(analysis_id)
    return {
        "status": "success",
        "message": "Storage archive merged into existing storage",
        "merged_counts": merged_counts,
    }


def storage_archive_http_exception(exc: Exception) -> HTTPException:
    if isinstance(exc, HTTPException):
        return exc
    if isinstance(exc, StorageArchiveError):
        return HTTPException(status_code=400, detail=str(exc))
    return HTTPException(status_code=500, detail=str(exc))
