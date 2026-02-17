from __future__ import annotations

"""
FAISS-backed retrieval service.

Public functions:
  - chunk_text(text: str, chunk_size: int = 1200, overlap: int = 200) -> List[str]
  - add_documents(docs: List[Tuple[str, str]]) -> int
  - query(text: str, top_k: int = 6) -> List[dict]
"""

import hashlib
import json
import logging
import os
import re
from pathlib import Path
from threading import Event, RLock, Thread
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

FAST_MODE = os.getenv("AEGIS_FAST_MODE", "").strip().lower() in {"1", "true", "yes", "on"}
_raw_batch = os.getenv("AEGIS_EMBED_BATCH_SIZE", "").strip()
if _raw_batch:
    try:
        EMBED_BATCH_SIZE = max(1, int(_raw_batch))
    except ValueError:
        EMBED_BATCH_SIZE = 0
else:
    # In fast mode, keep embedding batches small to avoid large memory spikes.
    EMBED_BATCH_SIZE = 64 if FAST_MODE else 0
_raw_hard_timeout = os.getenv("AEGIS_EMBED_HARD_TIMEOUT", "").strip()
if _raw_hard_timeout:
    try:
        EMBED_HARD_TIMEOUT = float(_raw_hard_timeout)
    except ValueError:
        EMBED_HARD_TIMEOUT = 0.0
else:
    # Hard timeout prevents hung embed backends from blocking ingest forever.
    EMBED_HARD_TIMEOUT = 45.0 if FAST_MODE else 180.0
FALLBACK_DIM = int(os.getenv("AEGIS_EMBED_DIM", "256"))
try:  # pragma: no cover
    import faiss  # type: ignore
except Exception:  # noqa: BLE001
    faiss = None  # type: ignore[assignment]
    logger.warning("faiss not installed; retrieval service disabled. Install 'faiss-cpu'.")

try:  # pragma: no cover
    import numpy as np  # type: ignore
except Exception:  # noqa: BLE001
    np = None  # type: ignore[assignment]
    logger.warning("numpy not installed; retrieval normalization disabled.")

try:
    from app.services.embedding_service import EMBEDDING_DIM, embed_texts
except Exception as exc:  # noqa: BLE001
    logger.warning(
        "Embedding service not available (embedding_service import failed: %s). Retrieval disabled.",
        exc,
    )
    EMBEDDING_DIM = None  # type: ignore[assignment]

    def embed_texts(_texts: List[str]) -> List[List[float]]:  # type: ignore[redefinition]
        raise RuntimeError(
            "Embedding service not available. Ensure app.services.embedding_service "
            "exists and exposes EMBEDDING_DIM + embed_texts()."
        )

INDEX_DIR = Path(os.getenv("AEGIS_INDEX_DIR", "./data/faiss_index"))
INDEX_FILE = INDEX_DIR / "index.faiss"
META_FILE = INDEX_DIR / "metadata.json"

_index: Any = None
_meta: Dict[str, Any] = {"ids": [], "meta": {}}
# Re-entrant: add_documents() can call _save_index() while already holding the lock.
_state_lock = RLock()
_state_loaded = False


def _ensure_index_dir() -> None:
    INDEX_DIR.mkdir(parents=True, exist_ok=True)


def _atomic_write_json(path: Path, data: object) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        tmp.replace(path)
    except Exception:  # noqa: BLE001
        logger.exception("Failed to write metadata JSON at %s", path)


def _normalize(vecs: List[List[float]]):
    if np is None:
        raise RuntimeError("numpy is required for retrieval normalization")

    arr = np.asarray(vecs, dtype="float32")
    if arr.ndim == 1:
        arr = arr.reshape(1, -1)

    norms = np.linalg.norm(arr, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return (arr / norms).astype("float32")


def _hash_embed(text: str, dim: int) -> List[float]:
    buf = text.encode("utf-8", errors="ignore")
    if not buf:
        buf = b"\x00"
    digest = hashlib.sha1(buf).digest()
    repeats = (dim + len(digest) - 1) // len(digest)
    raw = (digest * repeats)[:dim]
    return [(b - 128) / 128.0 for b in raw]


def _hash_embed_batch(texts: List[str], dim: int) -> List[List[float]]:
    return [_hash_embed(t, dim) for t in texts]


def _embed_texts_safe(texts: List[str]) -> List[List[float]]:
    """
    Guard embedding calls with a hard timeout and a hashing fallback.
    This avoids long hangs during ingest when the embed backend stalls.
    """
    if not texts:
        return []
    if not EMBED_HARD_TIMEOUT or EMBED_HARD_TIMEOUT <= 0:
        return embed_texts(texts)

    result: dict[str, object] = {"vecs": None, "error": None}
    done = Event()

    def _worker() -> None:
        try:
            result["vecs"] = embed_texts(texts)
        except Exception as exc:  # noqa: BLE001
            result["error"] = exc
        finally:
            done.set()

    Thread(target=_worker, daemon=True).start()
    if not done.wait(EMBED_HARD_TIMEOUT):
        logger.warning("embed_texts timed out after %.1fs; using hash fallback.", EMBED_HARD_TIMEOUT)
        dim = _current_dim() or FALLBACK_DIM
        return _hash_embed_batch(texts, dim)
    if result["error"] is not None:
        logger.warning("embed_texts failed; using hash fallback. %s", result["error"])
        dim = _current_dim() or FALLBACK_DIM
        return _hash_embed_batch(texts, dim)
    return result["vecs"] or []


def _current_dim() -> Optional[int]:
    dim = EMBEDDING_DIM
    if not dim:
        dim = _meta.get("dim")
    try:
        return int(dim) if dim is not None else None
    except Exception:  # noqa: BLE001
        return None


def _create_index():
    if faiss is None:
        raise RuntimeError("faiss not installed; cannot create FAISS index")
    dim = _current_dim()
    if dim is None:
        raise RuntimeError("EMBEDDING_DIM not set; cannot create FAISS index yet.")
    idx = faiss.IndexFlatIP(int(dim))
    logger.info("Created new FAISS IndexFlatIP (dim=%s)", dim)
    return idx


def _load_index() -> None:
    global _index, _meta, _state_loaded
    with _state_lock:
        if _state_loaded:
            return

        _ensure_index_dir()

        if META_FILE.exists():
            try:
                with META_FILE.open("r", encoding="utf-8") as f:
                    loaded_meta = json.load(f)
                ids = loaded_meta.get("ids") or []
                meta_map = loaded_meta.get("meta") or {}
                dim = loaded_meta.get("dim")
                if not isinstance(ids, list) or not isinstance(meta_map, dict):
                    raise ValueError("metadata JSON has invalid structure")
                _meta = {"ids": ids, "meta": meta_map}
                if dim is not None:
                    _meta["dim"] = dim
                logger.info("Loaded retrieval metadata (%d chunks, dim=%s)", len(ids), dim or "unknown")
            except Exception as e:  # noqa: BLE001
                logger.exception("Failed to load retrieval metadata; will recreate. %s", e)
                _meta = {"ids": [], "meta": {}}

        if faiss is None:
            _index = None
            _state_loaded = True
            logger.info("FAISS unavailable; retrieval running in lexical-only mode.")
            return

        if INDEX_FILE.exists():
            try:
                _index = faiss.read_index(str(INDEX_FILE))
                logger.info("Loaded FAISS index from %s", INDEX_FILE)
                try:
                    idx_dim = _index.d  # type: ignore[attr-defined]
                except Exception:
                    idx_dim = None
                target_dim = _current_dim()
                if target_dim is not None and idx_dim not in (None, target_dim):
                    logger.warning(
                        "FAISS index dim (%s) != current embedding dim (%s). Consider rebuilding.",
                        idx_dim,
                        target_dim,
                    )
                _state_loaded = True
                return
            except Exception as e:  # noqa: BLE001
                logger.exception("Failed to load FAISS index; will recreate. %s", e)
                _index = None

        dim = _current_dim()
        if dim is None:
            logger.debug(
                "EMBEDDING_DIM not set; deferring FAISS index init until embeddings are available."
            )
            _index = None
            _state_loaded = True
            return

        try:
            _index = _create_index()
        except Exception as e:  # noqa: BLE001
            logger.warning(
                "Could not create FAISS index yet (%s). Retrieval disabled until embeddings initialize.",
                e,
            )
            _index = None
            _state_loaded = True
            return

        if not isinstance(_meta, dict):
            _meta = {"ids": [], "meta": {}}
        _meta["dim"] = int(dim)
        logger.info("Initialized empty FAISS index and metadata.")
        _state_loaded = True


def _save_index() -> None:
    global _index, _meta
    with _state_lock:
        try:
            _ensure_index_dir()
            if _index is not None and faiss is not None:
                faiss.write_index(_index, str(INDEX_FILE))
            dim = _current_dim()
            if dim is not None:
                _meta["dim"] = int(dim)
            _atomic_write_json(META_FILE, _meta)
            logger.info(
                "Saved FAISS index and metadata (vectors=%d, dim=%s)",
                len(_meta.get("ids", [])),
                dim,
            )
        except Exception:  # noqa: BLE001
            logger.exception("Failed to save FAISS index or metadata")


def chunk_text(text: str, chunk_size: int = 1200, overlap: int = 200) -> List[str]:
    if not text:
        return []
    text = text.strip()
    L = len(text)
    if L == 0:
        return []
    if chunk_size <= 0:
        return [text]

    chunks: List[str] = []
    start = 0
    while start < L:
        end = min(start + chunk_size, L)
        window = text[start:end]
        sep_pos = max(window.rfind("\n"), window.rfind(". "), window.rfind("; "), window.rfind(")"))
        if sep_pos > int(chunk_size * 0.5):
            cut = start + sep_pos + 1
        else:
            cut = end
        chunk = text[start:cut].strip()
        if chunk:
            chunks.append(chunk)
        if cut >= L:
            break
        start = max(cut - overlap, cut) if overlap > 0 else cut
    return chunks


def _is_path_like_query(text: str) -> bool:
    t = (text or "").lower()
    if not t:
        return False
    if "/" in text or "\\" in text:
        return True
    if "data/uploads" in t or "path" in t or "ruta" in t or "archivo" in t or "file" in t:
        return True
    if re.search(r"\b[\w.-]+\.(py|js|ts|tsx|jsx|md|txt|json|yml|yaml|html|css|sql|ini|toml)\b", t):
        return True
    return False


def _lexical_path_matches(
    text: str,
    ids: List[str],
    meta_map: Dict[str, Dict[str, str]],
    top_k: int,
) -> List[dict]:
    """
    Fallback retrieval for direct path/file questions.
    Useful when user asks "what is inside /data/uploads/...".
    """
    q = (text or "").strip().lower()
    if not q:
        return []

    tokens = [tok for tok in re.split(r"[^a-zA-Z0-9_./-]+", q) if len(tok) >= 3]
    scored: List[Tuple[float, dict]] = []
    for cid in ids:
        m = meta_map.get(cid) or {}
        src = (m.get("source") or "").lower()
        body = (m.get("text") or "").lower()
        if not src:
            continue

        score = 0.0
        if q in src:
            score += 100.0
        for tok in tokens:
            if tok in src:
                score += 6.0
            elif tok in body:
                score += 1.0
        if score <= 0:
            continue
        scored.append(
            (
                score,
                {
                    "source": m.get("source"),
                    "text": m.get("text"),
                    "score": float(score),
                },
            )
        )

    scored.sort(key=lambda x: x[0], reverse=True)
    return [row for _, row in scored[: max(1, top_k)]]


def _lexical_text_matches(
    text: str,
    ids: List[str],
    meta_map: Dict[str, Dict[str, str]],
    top_k: int,
) -> List[dict]:
    q = (text or "").strip().lower()
    if not q:
        return []

    tokens = [tok for tok in re.split(r"[^a-zA-Z0-9_./-]+", q) if len(tok) >= 2]
    scored: List[Tuple[float, dict]] = []
    for cid in ids:
        m = meta_map.get(cid) or {}
        src = (m.get("source") or "").lower()
        body = (m.get("text") or "").lower()
        if not src and not body:
            continue

        score = 0.0
        if q and q in body:
            score += 40.0
        if q and q in src:
            score += 30.0
        for tok in tokens:
            if tok in src:
                score += 4.0
            if tok in body:
                score += 2.0
        if score <= 0:
            continue
        scored.append(
            (
                score,
                {
                    "source": m.get("source"),
                    "text": m.get("text"),
                    "score": float(score),
                },
            )
        )

    scored.sort(key=lambda x: x[0], reverse=True)
    return [row for _, row in scored[: max(1, top_k)]]


def add_documents(docs: List[Tuple[str, str]]) -> int:
    global _index, _meta, EMBEDDING_DIM

    _load_index()

    to_embed: List[str] = []
    metas: List[Tuple[str, Dict[str, str]]] = []
    existing_meta: Dict[str, Dict[str, str]] = _meta.get("meta", {})  # type: ignore[assignment]
    duplicate_count = 0
    empty_count = 0

    for source, text in docs:
        if not text:
            empty_count += 1
            continue
        for chunk in chunk_text(text):
            if not chunk:
                continue
            chunk_sha = hashlib.sha1(chunk.encode("utf-8")).hexdigest()
            chunk_id = hashlib.sha1((str(source) + chunk_sha).encode("utf-8")).hexdigest()
            if chunk_id in existing_meta:
                duplicate_count += 1
                continue
            metas.append((chunk_id, {"source": str(source), "text": chunk, "sha": chunk_sha}))
            # Include source path tokens in embedding text so path/file queries
            # (e.g. "what is in data/uploads/.../app/api.py") can retrieve it.
            to_embed.append(f"SOURCE_PATH: {source}\n{chunk}")

    if not to_embed:
        logger.info(
            "add_documents: nothing to add (duplicates=%d, empty_docs=%d, incoming_docs=%d)",
            duplicate_count,
            empty_count,
            len(docs),
        )
        return 0

    if faiss is None or np is None:
        with _state_lock:
            ids_list: List[str] = _meta.setdefault("ids", [])  # type: ignore[assignment]
            meta_map: Dict[str, Dict[str, str]] = _meta.setdefault("meta", {})  # type: ignore[assignment]
            for cid, m in metas:
                ids_list.append(cid)
                meta_map[cid] = m
            _save_index()
        logger.info(
            "add_documents: added %d chunks in lexical-only mode (total=%d)",
            len(metas),
            len(_meta.get("ids", [])),
        )
        return len(metas)

    if EMBED_BATCH_SIZE <= 0:
        vectors = _embed_texts_safe(to_embed)
        if not vectors:
            logger.warning("add_documents: embed_texts returned no vectors; aborting indexing.")
            return 0

        try:
            dim_from_vecs = len(vectors[0])
        except Exception:
            dim_from_vecs = None

        if dim_from_vecs is not None and dim_from_vecs > 0:
            if EMBEDDING_DIM is None:
                EMBEDDING_DIM = dim_from_vecs  # type: ignore[assignment]
                logger.info("Inferred EMBEDDING_DIM=%s from first embedding batch.", EMBEDDING_DIM)
            _meta["dim"] = int(dim_from_vecs)

        vecs = _normalize(vectors)

        with _state_lock:
            if _index is None:
                _index = _create_index()

            try:
                idx_dim = _index.d  # type: ignore[attr-defined]
            except Exception:
                idx_dim = None

            if idx_dim is not None and vecs.shape[1] != idx_dim:
                raise RuntimeError(
                    f"Vector dimension mismatch: index dim={idx_dim}, vectors dim={vecs.shape[1]}"
                )

            _index.add(vecs)

            ids_list: List[str] = _meta.setdefault("ids", [])  # type: ignore[assignment]
            meta_map: Dict[str, Dict[str, str]] = _meta.setdefault("meta", {})  # type: ignore[assignment]

            for cid, m in metas:
                ids_list.append(cid)
                meta_map[cid] = m

            _save_index()

        logger.info("add_documents: added %d chunks (total=%d)", len(metas), len(_meta.get("ids", [])))
        return len(metas)

    total_added = 0
    for i in range(0, len(to_embed), EMBED_BATCH_SIZE):
        batch_texts = to_embed[i : i + EMBED_BATCH_SIZE]
        batch_metas = metas[i : i + EMBED_BATCH_SIZE]
        vectors = _embed_texts_safe(batch_texts)
        if not vectors:
            logger.warning("add_documents: empty embedding batch at offset %s", i)
            continue

        try:
            dim_from_vecs = len(vectors[0])
        except Exception:
            dim_from_vecs = None

        if dim_from_vecs is not None and dim_from_vecs > 0:
            if EMBEDDING_DIM is None:
                EMBEDDING_DIM = dim_from_vecs  # type: ignore[assignment]
                logger.info("Inferred EMBEDDING_DIM=%s from first embedding batch.", EMBEDDING_DIM)
            _meta["dim"] = int(dim_from_vecs)

        vecs = _normalize(vectors)

        with _state_lock:
            if _index is None:
                _index = _create_index()

            try:
                idx_dim = _index.d  # type: ignore[attr-defined]
            except Exception:
                idx_dim = None

            if idx_dim is not None and vecs.shape[1] != idx_dim:
                raise RuntimeError(
                    f"Vector dimension mismatch: index dim={idx_dim}, vectors dim={vecs.shape[1]}"
                )

            _index.add(vecs)

            ids_list: List[str] = _meta.setdefault("ids", [])  # type: ignore[assignment]
            meta_map: Dict[str, Dict[str, str]] = _meta.setdefault("meta", {})  # type: ignore[assignment]

            for cid, m in batch_metas:
                ids_list.append(cid)
                meta_map[cid] = m

        total_added += len(batch_metas)

    if total_added:
        _save_index()
    logger.info("add_documents: added %d chunks (total=%d)", total_added, len(_meta.get("ids", [])))
    return total_added


def query(text: str, top_k: int = 6) -> List[dict]:
    global _index, _meta, EMBEDDING_DIM

    if not text:
        return []

    _load_index()

    with _state_lock:
        ids: List[str] = _meta.get("ids", [])  # type: ignore[assignment]
        meta_map: Dict[str, Dict[str, str]] = _meta.get("meta", {})  # type: ignore[assignment]
        if not ids:
            return []

        lexical_first: List[dict] = _lexical_text_matches(text, ids, meta_map, top_k=top_k)
        if _is_path_like_query(text):
            lexical_path = _lexical_path_matches(text, ids, meta_map, top_k=top_k)
            merged_lex: List[dict] = []
            seen_keys: set[tuple[str, str]] = set()
            for row in lexical_path + lexical_first:
                key = ((row.get("source") or ""), (row.get("text") or ""))
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                merged_lex.append(row)
                if len(merged_lex) >= top_k:
                    break
            lexical_first = merged_lex

        if faiss is None or np is None or _index is None:
            return lexical_first[:top_k]

    vectors = _embed_texts_safe([text])
    if not vectors:
        return lexical_first[:top_k]

    try:
        dim_from_vecs = len(vectors[0])
    except Exception:
        dim_from_vecs = None

    if dim_from_vecs is not None and dim_from_vecs > 0 and EMBEDDING_DIM is None:
        EMBEDDING_DIM = dim_from_vecs  # type: ignore[assignment]
        _meta["dim"] = int(dim_from_vecs)
        logger.info("Inferred EMBEDDING_DIM=%s during query()", EMBEDDING_DIM)

    try:
        qv = _normalize(vectors)
    except Exception:  # noqa: BLE001
        logger.exception("query: normalization failed")
        return lexical_first[:top_k]

    with _state_lock:
        ids = _meta.get("ids", [])  # type: ignore[assignment]
        meta_map = _meta.get("meta", {})  # type: ignore[assignment]

        try:
            D, I = _index.search(qv, top_k)  # type: ignore[call-arg]
        except Exception:  # noqa: BLE001
            logger.exception("FAISS search failed in query()")
            return lexical_first

        results: List[dict] = []

        try:
            distances = D[0].tolist()
            indices = I[0].tolist()
        except Exception:  # noqa: BLE001
            logger.exception("query: unexpected FAISS search output shape")
            return lexical_first[:top_k]

        seen: set[tuple[str, str]] = set()
        for row in lexical_first:
            key = ((row.get("source") or ""), (row.get("text") or ""))
            if key in seen:
                continue
            seen.add(key)
            results.append(row)
            if len(results) >= top_k:
                return results[:top_k]

        for dist, idx in zip(distances, indices):
            if idx < 0 or idx >= len(ids):
                continue
            cid = ids[idx]
            m = meta_map.get(cid, {})
            row = {
                "source": m.get("source"),
                "text": m.get("text"),
                "score": float(dist),
            }
            key = ((row.get("source") or ""), (row.get("text") or ""))
            if key in seen:
                continue
            seen.add(key)
            results.append(row)
            if len(results) >= top_k:
                break

    return results[:top_k]


def get_retrieval_status() -> dict:
    _load_index()
    with _state_lock:
        ids = _meta.get("ids", []) if isinstance(_meta, dict) else []
        dim = _meta.get("dim") if isinstance(_meta, dict) else None
        vectors = 0
        if _index is not None and faiss is not None:
            try:
                vectors = int(_index.ntotal)  # type: ignore[attr-defined]
            except Exception:
                vectors = 0
        mode = "faiss" if (_index is not None and faiss is not None and np is not None) else "lexical"
        return {
            "mode": mode,
            "faiss_available": faiss is not None,
            "numpy_available": np is not None,
            "index_file": str(INDEX_FILE),
            "meta_file": str(META_FILE),
            "index_exists": INDEX_FILE.exists(),
            "meta_exists": META_FILE.exists(),
            "chunks": len(ids) if isinstance(ids, list) else 0,
            "vectors": vectors,
            "dim": int(dim) if isinstance(dim, int) else (int(dim) if str(dim).isdigit() else None),
        }
