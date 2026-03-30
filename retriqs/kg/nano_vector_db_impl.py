import base64
import gc
import os
import pickle
import re
import tempfile
import time
import zlib
from dataclasses import dataclass
from typing import Any, final

import numpy as np
from nano_vectordb import NanoVectorDB
from rank_bm25 import BM25Okapi

from retriqs.base import BaseVectorStorage
from retriqs.utils import compute_mdhash_id, logger
from .shared_storage import (
    get_namespace_lock,
    get_update_flag,
    set_all_update_flags,
)


@final
@dataclass
class NanoVectorDBStorage(BaseVectorStorage):
    def __post_init__(self):
        self._validate_embedding_func()

        self._client = None
        self._storage_lock = None
        self.storage_updated = None

        self._bm25 = None
        self._corpus_ids: list[str] = []
        self._tokenized_corpus: list[list[str]] = []
        self.bm25_weight = float(self.global_config.get("bm25_weight", 0.3))

        kwargs = self.global_config.get("vector_db_storage_cls_kwargs", {})
        cosine_threshold = kwargs.get("cosine_better_than_threshold")
        if cosine_threshold is None:
            raise ValueError("cosine_better_than_threshold must be specified")
        self.cosine_better_than_threshold = cosine_threshold

        working_dir = self.global_config["working_dir"]
        workspace_dir = (
            os.path.join(working_dir, self.workspace) if self.workspace else working_dir
        )
        os.makedirs(workspace_dir, exist_ok=True)

        self._client_file_name = os.path.join(
            workspace_dir, f"vdb_{self.namespace}.json"
        )
        self._bm25_file_name = os.path.join(
            workspace_dir, f"bm25_{self.namespace}.pkl"
        )
        self._max_batch_size = max(
            1, int(self.global_config.get("embedding_batch_num", 16))
        )

        logger.info(
            f"Initializing NanoVectorDB for {self.namespace} at {self._client_file_name}"
        )
        self._client = NanoVectorDB(
            self.embedding_func.embedding_dim,
            storage_file=self._client_file_name,
        )

        self._load_bm25()

    def _tokenize(self, text: str) -> list[str]:
        return re.findall(r"[\w']+", (text or "").lower())

    def _extract_bm25_text(self, payload: dict[str, Any]) -> str:
        """
        Build a BM25 corpus string independently from meta_fields.
        This avoids the bug where BM25 has no text when 'content'
        is not part of self.meta_fields.
        """
        parts: list[str] = []

        def collect(value: Any):
            if value is None:
                return
            if isinstance(value, str):
                stripped = value.strip()
                if stripped:
                    parts.append(stripped)
                return
            if isinstance(value, dict):
                for key, inner_value in value.items():
                    if str(key).startswith("__"):
                        continue
                    collect(inner_value)
                return
            if isinstance(value, (list, tuple, set)):
                for inner_value in value:
                    collect(inner_value)

        if "content" in payload and isinstance(payload["content"], str):
            collect(payload["content"])
        else:
            collect(payload)

        return " ".join(parts)

    def _save_bm25(self) -> None:
        """
        Persist only the minimal BM25 state needed to reconstruct the index.
        Pickling the full BM25Okapi object is less robust across versions.
        """
        if not self._corpus_ids or not self._tokenized_corpus:
            if os.path.exists(self._bm25_file_name):
                os.remove(self._bm25_file_name)
            return

        payload = {
            "ids": self._corpus_ids,
            "tokenized_corpus": self._tokenized_corpus,
        }

        tmp_dir = os.path.dirname(self._bm25_file_name) or "."
        fd, tmp_path = tempfile.mkstemp(
            prefix="bm25_", suffix=".tmp", dir=tmp_dir
        )
        try:
            with os.fdopen(fd, "wb") as f:
                pickle.dump(payload, f, protocol=pickle.HIGHEST_PROTOCOL)
            os.replace(tmp_path, self._bm25_file_name)
            logger.info(f"BM25: Saved persistent index for {self.namespace}")
        except Exception:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            raise

    def _refresh_bm25(self, save_to_disk: bool = False) -> None:
        """
        Rebuild BM25 from current NanoVectorDB in-memory storage.
        """
        try:
            storage = getattr(self._client, "_NanoVectorDB__storage", {}) or {}
            data = storage.get("data", []) or []

            if not data:
                self._bm25 = None
                self._corpus_ids = []
                self._tokenized_corpus = []
                if save_to_disk and os.path.exists(self._bm25_file_name):
                    os.remove(self._bm25_file_name)
                logger.info(f"BM25: No data for {self.namespace}; cache cleared")
                return

            corpus_ids: list[str] = []
            tokenized_corpus: list[list[str]] = []

            for item in data:
                item_id = item.get("__id__")
                if item_id is None:
                    continue

                raw_text = item.get("__bm25_text__")
                if not isinstance(raw_text, str) or not raw_text.strip():
                    raw_text = " ".join(
                        str(v)
                        for k, v in item.items()
                        if isinstance(v, str) and not str(k).startswith("__")
                    )

                tokens = self._tokenize(raw_text)
                if not tokens:
                    continue

                corpus_ids.append(item_id)
                tokenized_corpus.append(tokens)

            self._corpus_ids = corpus_ids
            self._tokenized_corpus = tokenized_corpus
            self._bm25 = BM25Okapi(tokenized_corpus) if tokenized_corpus else None

            if save_to_disk:
                self._save_bm25()

            logger.info(
                f"BM25: Refreshed index for {self.namespace} ({len(self._corpus_ids)} docs)"
            )
        except Exception as e:
            logger.error(f"BM25 refresh error for {self.namespace}: {e}")
            self._bm25 = None
            self._corpus_ids = []
            self._tokenized_corpus = []

    def _load_bm25(self) -> None:
        """
        Load BM25 from disk when possible, otherwise rebuild from NanoVectorDB storage.
        """
        if os.path.exists(self._bm25_file_name):
            try:
                with open(self._bm25_file_name, "rb") as f:
                    payload = pickle.load(f)

                ids = payload.get("ids", [])
                tokenized_corpus = payload.get("tokenized_corpus", [])

                if ids and tokenized_corpus and len(ids) == len(tokenized_corpus):
                    self._corpus_ids = ids
                    self._tokenized_corpus = tokenized_corpus
                    self._bm25 = BM25Okapi(tokenized_corpus)
                    logger.info(f"BM25: Loaded persistent index for {self.namespace}")
                    return

                logger.warning(
                    f"BM25: Cache file invalid for {self.namespace}; rebuilding"
                )
            except Exception as e:
                logger.warning(
                    f"BM25: Failed to load cache for {self.namespace}: {e}; rebuilding"
                )

        self._refresh_bm25(save_to_disk=True)

    async def initialize(self):
        self.storage_updated = await get_update_flag(
            self.namespace, workspace=self.workspace
        )
        self._storage_lock = get_namespace_lock(
            self.namespace, workspace=self.workspace
        )

    async def _get_client(self):
        async with self._storage_lock:
            if self.storage_updated.value:
                logger.info(
                    f"[{self.workspace}] Process {os.getpid()} reloading "
                    f"{self.namespace} due to update flag."
                )
                self._client = NanoVectorDB(
                    self.embedding_func.embedding_dim,
                    storage_file=self._client_file_name,
                )
                self.storage_updated.value = False
                self._load_bm25()
            return self._client

    async def upsert(self, data: dict[str, dict[str, Any]]) -> None:
        """
        Memory-safe sequential upsert:
        - embeds one batch at a time
        - upserts one batch at a time
        - does not accumulate all embeddings in RAM
        """
        if not data:
            return

        logger.info(f"Upsert: Processing {len(data)} items for {self.namespace}")
        current_time = int(time.time())
        items = list(data.items())

        client = await self._get_client()

        for batch_idx, start in enumerate(range(0, len(items), self._max_batch_size), 1):
            batch_items = items[start : start + self._max_batch_size]

            batch_texts: list[str] = []
            batch_bm25_texts: list[str] = []

            for _, payload in batch_items:
                text = payload.get("content")
                if not isinstance(text, str) or not text.strip():
                    text = self._extract_bm25_text(payload)

                batch_texts.append(text)
                batch_bm25_texts.append(self._extract_bm25_text(payload))

            logger.info(
                f"Embedding batch {batch_idx}/"
                f"{(len(items) + self._max_batch_size - 1) // self._max_batch_size} "
                f"for {self.namespace}"
            )

            try:
                batch_embeddings = await self.embedding_func(batch_texts)
            except Exception as e:
                logger.error(
                    f"Embedding failed on batch {batch_idx} for {self.namespace}: {e}"
                )
                raise

            if len(batch_embeddings) != len(batch_items):
                raise RuntimeError(
                    f"Embedding/data mismatch in {self.namespace}: "
                    f"{len(batch_embeddings)} != {len(batch_items)}"
                )

            batch_records: list[dict[str, Any]] = []
            for (item_id, payload), embedding, bm25_text in zip(
                batch_items, batch_embeddings, batch_bm25_texts
            ):
                vector_f32 = np.asarray(embedding, dtype=np.float32)
                vector_f16 = vector_f32.astype(np.float16)

                compressed_vector = zlib.compress(vector_f16.tobytes())
                encoded_vector = base64.b64encode(compressed_vector).decode("utf-8")

                record = {
                    "__id__": item_id,
                    "__created_at__": current_time,
                    "__bm25_text__": bm25_text,
                    **{k: v for k, v in payload.items() if k in self.meta_fields},
                    "vector": encoded_vector,
                    "__vector__": vector_f32,
                }
                batch_records.append(record)

            async with self._storage_lock:
                client.upsert(datas=batch_records)

            del batch_embeddings
            del batch_records
            gc.collect()

        async with self._storage_lock:
            self._refresh_bm25(save_to_disk=False)

        logger.info(f"Upsert: Finished processing {len(data)} items for {self.namespace}")

    async def query(
        self, query: str, top_k: int, query_embedding: list[float] = None
    ) -> list[dict[str, Any]]:
        logger.info(
            f"Query: Processing request for '{query}...' "
            f"(namespace: {self.namespace})"
        )

        logger.info(
            f"BM25 DEBUG [{self.namespace}] query_start "
            f"query={query!r} "
            f"bm25_loaded={self._bm25 is not None} "
            f"corpus_size={len(self._corpus_ids)}"
        )

        if query_embedding is not None:
            embedding = query_embedding
        else:
            emb_result = await self.embedding_func([query], _priority=5)
            embedding = emb_result[0]

        client = await self._get_client()

        # Define a constant for RRF k (often 60 for good performance)
        RRF_K = 60

        # Fetch vector candidates
        vector_candidates = client.query(
            query=embedding,
            top_k=top_k * 2,  # Fetch more candidates for RRF
            better_than_threshold=self.cosine_better_than_threshold,
        ) or []

        logger.info(
            f"VECTOR DEBUG [{self.namespace}] candidates={len(vector_candidates)}"
        )

        if vector_candidates:
            logger.info(
                f"VECTOR DEBUG [{self.namespace}] top_vector_sample="
                f"{[(r.get('__id__'), round(float(r.get('__metrics__', 0.0)), 4)) for r in vector_candidates[:5]]}"
            )

        # Prepare BM25 candidates
        bm25_candidates = []
        if self._bm25:
            query_tokens = self._tokenize(query)

            logger.info(
                f"BM25 DEBUG [{self.namespace}] query_tokens={query_tokens[:20]} "
                f"total={len(query_tokens)}"
            )

            if query_tokens:
                bm25_scores = self._bm25.get_scores(query_tokens)

                nonzero_scores = sum(1 for s in bm25_scores if float(s) > 0.0)
                max_bm25 = float(np.max(bm25_scores)) if len(bm25_scores) else 0.0

                logger.info(
                    f"BM25 DEBUG [{self.namespace}] bm25_scores "
                    f"docs={len(bm25_scores)} "
                    f"nonzero={nonzero_scores} "
                    f"max={max_bm25:.4f}"
                )

                # Get top BM25 IDs based on scores
                bm25_top_ids_with_scores = sorted(
                    [(self._corpus_ids[i], float(s)) for i, s in enumerate(bm25_scores)],
                    key=lambda x: x[1],
                    reverse=True,
                )[:top_k * 2] # Fetch more candidates for RRF

                bm25_top_ids = [item_id for item_id, _ in bm25_top_ids_with_scores]

                bm25_candidates = client.get(bm25_top_ids) if bm25_top_ids else []

                logger.info(
                    f"BM25 DEBUG [{self.namespace}] bm25_candidate_ids={len(bm25_top_ids)} "
                    f"bm25_candidates_fetched={len(bm25_candidates)}"
                )
            else:
                logger.info(f"BM25 DEBUG [{self.namespace}] No query tokens for BM25.")
        else:
            logger.info(f"Query: BM25 unavailable for {self.namespace}; vector only")

        # If no candidates from either source, return empty
        if not vector_candidates and not bm25_candidates:
            logger.info(f"Query: No candidates found for {self.namespace}")
            return []

        # Apply Reciprocal Rank Fusion (RRF)
        fused_scores: dict[str, float] = {}
        all_candidate_ids: set[str] = set()

        # Process vector candidates
        vector_ranks: dict[str, int] = {}
        for rank, item in enumerate(vector_candidates):
            if item and item.get("__id__"):
                doc_id = item["__id__"]
                vector_ranks[doc_id] = rank + 1
                all_candidate_ids.add(doc_id)
                fused_scores[doc_id] = fused_scores.get(doc_id, 0.0) + (1.0 / (RRF_K + rank + 1))

        # Process BM25 candidates
        bm25_ranks: dict[str, int] = {}
        for rank, item in enumerate(bm25_candidates):
            if item and item.get("__id__"):
                doc_id = item["__id__"]
                bm25_ranks[doc_id] = rank + 1
                all_candidate_ids.add(doc_id)
                fused_scores[doc_id] = fused_scores.get(doc_id, 0.0) + (1.0 / (RRF_K + rank + 1))

        # Fetch full data for all unique candidates
        all_candidates_data = client.get(list(all_candidate_ids))
        candidate_data_map = {item["__id__"]: item for item in all_candidates_data if item}

        # Assemble final ranked list using RRF scores
        combined = []
        for doc_id, rrf_score in fused_scores.items():
            item = candidate_data_map.get(doc_id)
            if not item:
                continue
            item = dict(item)
            item["__metrics__"] = rrf_score
            combined.append(item)

        combined.sort(key=lambda x: float(x.get("__metrics__", 0.0)), reverse=True)

        logger.info(
            f"FUSION DEBUG [{self.namespace}] top_results="
            f"{[(r.get('__id__'), round(float(r.get('__metrics__', 0.0)), 4)) for r in combined[:5]]}"
        )

        logger.info(
            f"Query: Found {len(combined)} hybrid matches for {self.namespace}"
        )
        return self._format_results(combined[:top_k])
    
    def _format_results(self, results):
        if not results:
            return []

        return [
            {
                **{
                    k: v
                    for k, v in dp.items()
                    if k not in {"vector", "__vector__", "__bm25_text__"}
                },
                "id": dp.get("__id__"),
                "distance": dp.get("__metrics__"),
                "created_at": dp.get("__created_at__"),
            }
            for dp in results
            if dp
        ]

    async def export_data(self) -> dict[str, Any]:
        client = await self._get_client()
        storage = getattr(client, "_NanoVectorDB__storage", {})
        raw_data = storage.get("data", [])
        cleaned_data = [
            {
                k: v
                for k, v in item.items()
                if k not in {"vector", "__vector__", "__bm25_text__"}
            }
            for item in raw_data
        ]
        return {
            "namespace": self.namespace,
            "workspace": self.workspace,
            "data": cleaned_data,
        }

    @property
    async def client_storage(self):
        client = await self._get_client()
        return getattr(client, "_NanoVectorDB__storage")

    async def delete(self, ids: list[str]):
        try:
            client = await self._get_client()
            async with self._storage_lock:
                client.delete(ids)
                self._refresh_bm25(save_to_disk=False)
            logger.info(f"Delete: Removed {len(ids)} items from {self.namespace}")
        except Exception as e:
            logger.error(f"Delete error for {self.namespace}: {e}")

    async def index_done_callback(self) -> bool:
        async with self._storage_lock:
            if self.storage_updated.value:
                self._client = NanoVectorDB(
                    self.embedding_func.embedding_dim,
                    storage_file=self._client_file_name,
                )
                self.storage_updated.value = False
                self._load_bm25()
                return False

            try:
                self._client.save()
                self._save_bm25()
                self._refresh_bm25(save_to_disk=True)
                await set_all_update_flags(self.namespace, workspace=self.workspace)
                self.storage_updated.value = False
                logger.info(
                    f"Persistence: Saved vector DB and BM25 cache for {self.namespace}"
                )
                return True
            except Exception as e:
                logger.error(f"Save error for {self.namespace}: {e}")
                return False

    async def get_by_id(self, id: str) -> dict[str, Any] | None:
        client = await self._get_client()
        result = client.get([id])
        if result:
            dp = result[0]
            return {
                **{
                    k: v
                    for k, v in dp.items()
                    if k not in {"vector", "__vector__", "__bm25_text__"}
                },
                "id": dp.get("__id__"),
                "created_at": dp.get("__created_at__"),
            }
        return None

    async def get_by_ids(self, ids: list[str]) -> list[dict[str, Any]]:
        if not ids:
            return []

        client = await self._get_client()
        results = client.get(ids)

        result_map = {
            str(dp["__id__"]): {
                **{
                    k: v
                    for k, v in dp.items()
                    if k not in {"vector", "__vector__", "__bm25_text__"}
                },
                "id": dp.get("__id__"),
                "created_at": dp.get("__created_at__"),
            }
            for dp in results
            if dp
        }
        return [result_map.get(str(rid)) for rid in ids]

    async def get_vectors_by_ids(self, ids: list[str]) -> dict[str, list[float]]:
        if not ids:
            return {}

        client = await self._get_client()
        results = client.get(ids)

        vectors_dict = {}
        for result in results:
            if result and "vector" in result:
                decompressed = zlib.decompress(base64.b64decode(result["vector"]))
                vectors_dict[result["__id__"]] = (
                    np.frombuffer(decompressed, dtype=np.float16)
                    .astype(np.float32)
                    .tolist()
                )
        return vectors_dict

    async def drop(self) -> dict[str, str]:
        try:
            async with self._storage_lock:
                if os.path.exists(self._client_file_name):
                    os.remove(self._client_file_name)
                if os.path.exists(self._bm25_file_name):
                    os.remove(self._bm25_file_name)

                self._client = NanoVectorDB(
                    self.embedding_func.embedding_dim,
                    storage_file=self._client_file_name,
                )
                self._bm25 = None
                self._corpus_ids = []
                self._tokenized_corpus = []

                await set_all_update_flags(self.namespace, workspace=self.workspace)
                self.storage_updated.value = False
                logger.info(f"Drop: Cleared all data for {self.namespace}")

            return {"status": "success", "message": "data dropped"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def delete_entity(self, entity_name: str) -> None:
        try:
            entity_id = compute_mdhash_id(entity_name, prefix="ent-")
            client = await self._get_client()
            async with self._storage_lock:
                if client.get([entity_id]):
                    client.delete([entity_id])
                    self._refresh_bm25(save_to_disk=False)
        except Exception as e:
            logger.error(f"Error deleting entity {entity_name}: {e}")

    async def delete_entity_relation(self, entity_name: str) -> None:
        try:
            client = await self._get_client()
            storage = getattr(client, "_NanoVectorDB__storage", {})
            raw_data = storage.get("data", [])

            ids_to_delete = [
                dp["__id__"]
                for dp in raw_data
                if dp.get("src_id") == entity_name or dp.get("tgt_id") == entity_name
            ]

            if ids_to_delete:
                async with self._storage_lock:
                    client.delete(ids_to_delete)
                    self._refresh_bm25(save_to_disk=False)
        except Exception as e:
            logger.error(f"Error deleting relations for {entity_name}: {e}")