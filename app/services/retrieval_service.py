from __future__ import annotations

"""
FAISS-backed retrieval service.

Public functions:
  - chunk_text(text: str, chunk_size: int = 1200, overlap: int = 200) -> List[str]
  - add_documents(docs: List[Tuple[str, str] | Dict[str, Any]]) -> int
  - query(text: str, top_k: int = 6, project_id: str | None = None) -> List[dict]

Why this module exists:
- Keep retrieval deterministic and project-scoped.
- Support vector search with safe lexical/hash fallbacks.
"""

import json
import hashlib
import logging
import os
import re
from pathlib import Path
from threading import RLock
from typing import Any, Dict, List, Optional, Tuple
from app.utils.ml_helpers import hash_embed as _hash_embed
from app.utils.threading_helpers import call_with_timeout

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
faiss = None  # type: ignore[assignment]
_faiss_import_error: Exception | None = None

try:  # pragma: no cover
    import numpy as np  # type: ignore
except Exception:  # noqa: BLE001
    np = None  # type: ignore[assignment]
    logger.warning("numpy not installed; retrieval normalization disabled.")

EMBEDDING_DIM = None  # type: ignore[assignment]
_embedder_import_error: Exception | None = None
_embed_texts_impl = None


def _get_faiss():  # type: ignore[no-untyped-def]
    global faiss, _faiss_import_error
    if faiss is not None:
        return faiss
    if _faiss_import_error is not None:
        return None
    try:  # pragma: no cover
        import faiss as _faiss  # type: ignore

        faiss = _faiss  # type: ignore[assignment]
        return faiss
    except Exception as exc:  # noqa: BLE001
        _faiss_import_error = exc
        logger.warning("faiss not installed; retrieval service disabled. Install 'faiss-cpu'.")
        return None


def _ensure_embedder_loaded() -> None:
    global EMBEDDING_DIM, _embed_texts_impl, _embedder_import_error
    if _embed_texts_impl is not None:
        return
    if _embedder_import_error is not None:
        raise RuntimeError(f"Embedding service not available: {_embedder_import_error}")
    try:
        from app.services.embedding_service import EMBEDDING_DIM as _DIM, embed_texts as _embed

        EMBEDDING_DIM = _DIM  # type: ignore[assignment]
        _embed_texts_impl = _embed
    except Exception as exc:  # noqa: BLE001
        _embedder_import_error = exc
        raise RuntimeError(f"Embedding service not available: {exc}") from exc


def embed_texts(texts: List[str]) -> List[List[float]]:  # type: ignore[override]
    _ensure_embedder_loaded()
    assert _embed_texts_impl is not None
    return _embed_texts_impl(texts)

INDEX_DIR = Path(os.getenv("AEGIS_INDEX_DIR", "./data/faiss_index"))
INDEX_FILE = INDEX_DIR / "index.faiss"
META_FILE = INDEX_DIR / "metadata.json"

_index: Any = None
_meta: Dict[str, Any] = {"ids": [], "meta": {}}
# Re-entrant: add_documents() can call _save_index() while already holding the lock.
_state_lock = RLock()
_state_loaded = False


def _doc_project_id(meta: Dict[str, Any]) -> str:
    raw = str(meta.get("project_id") or "").strip()
    if raw:
        return raw
    source = str(meta.get("source") or "").strip()
    if "/" in source:
        return source.split("/", 1)[0].strip()
    return source


def _doc_rel_path(meta: Dict[str, Any]) -> str:
    raw = str(meta.get("rel_path") or "").strip()
    if raw:
        return raw
    source = str(meta.get("source") or "").strip()
    project_id = _doc_project_id(meta)
    if project_id and source.startswith(project_id + "/"):
        return source[len(project_id) + 1 :]
    return source


def _doc_matches_scope(meta: Dict[str, Any], project_id: Optional[str], rel_paths: Optional[set[str]] = None) -> bool:
    if not project_id:
        return True
    if _doc_project_id(meta).lower() != str(project_id).strip().lower():
        return False
    if rel_paths:
        rel = _doc_rel_path(meta)
        return rel in rel_paths
    return True


def _build_embed_input(source: str, text: str) -> str:
    return f"SOURCE_PATH: {source}\n{text}"


def _build_embed_input_from_meta(meta: Dict[str, Any]) -> str:
    return _build_embed_input(str(meta.get("source") or ""), str(meta.get("text") or ""))


def _result_row(meta: Dict[str, Any], score: float) -> Dict[str, Any]:
    row = {
        "source": meta.get("source"),
        "text": meta.get("text"),
        "score": float(score),
    }
    for key in ("project_id", "rel_path", "symbol", "chunk_type", "language", "line_start", "line_end", "file_sha"):
        value = meta.get(key)
        if value is not None:
            row[key] = value
    return row


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

    result = call_with_timeout(
        lambda: embed_texts(texts),
        timeout_s=EMBED_HARD_TIMEOUT,
        thread_name="retrieval-embed",
        daemon=True,
    )
    if not result.completed:
        logger.warning("embed_texts timed out after %.1fs; using hash fallback.", EMBED_HARD_TIMEOUT)
        dim = _current_dim() or FALLBACK_DIM
        return _hash_embed_batch(texts, dim)
    if result.error is not None:
        logger.warning("embed_texts failed; using hash fallback. %s", result.error)
        dim = _current_dim() or FALLBACK_DIM
        return _hash_embed_batch(texts, dim)
    return result.value or []


def _current_dim() -> Optional[int]:
    dim = EMBEDDING_DIM
    if not dim:
        dim = _meta.get("dim")
    try:
        return int(dim) if dim is not None else None
    except Exception:  # noqa: BLE001
        return None


def _create_index():
    f = _get_faiss()
    if f is None:
        raise RuntimeError("faiss not installed; cannot create FAISS index")
    dim = _current_dim()
    if dim is None:
        raise RuntimeError("EMBEDDING_DIM not set; cannot create FAISS index yet.")
    idx = f.IndexFlatIP(int(dim))
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

        f = _get_faiss()
        if f is None:
            _index = None
            _state_loaded = True
            logger.info("FAISS unavailable; retrieval running in lexical-only mode.")
            return

        if INDEX_FILE.exists():
            try:
                _index = f.read_index(str(INDEX_FILE))
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
            f = _get_faiss()
            if _index is not None and f is not None:
                f.write_index(_index, str(INDEX_FILE))
            elif INDEX_FILE.exists():
                INDEX_FILE.unlink()
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


def _coerce_optional_int(value: Any) -> Optional[int]:
    try:
        if value in (None, ""):
            return None
        return int(value)
    except Exception:  # noqa: BLE001
        return None


def _chunk_id_from_meta(meta: Dict[str, Any], chunk_index: int = 0) -> str:
    payload = "|".join(
        [
            str(meta.get("project_id") or ""),
            str(meta.get("rel_path") or ""),
            str(meta.get("source") or ""),
            str(meta.get("file_sha") or ""),
            str(meta.get("chunk_type") or ""),
            str(meta.get("symbol") or ""),
            str(meta.get("line_start") or ""),
            str(meta.get("line_end") or ""),
            str(chunk_index),
            hashlib.sha1(str(meta.get("text") or "").encode("utf-8")).hexdigest(),
        ]
    )
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def _prepare_document_chunks(doc: Tuple[str, str] | Dict[str, Any]) -> List[Tuple[str, Dict[str, Any]]]:
    if isinstance(doc, tuple):
        source, text = doc
        source_str = str(source)
        project_id = _doc_project_id({"source": source_str}) or None
        rel_path = _doc_rel_path({"source": source_str}) or None
        prepared: List[Tuple[str, Dict[str, Any]]] = []
        for idx, chunk in enumerate(chunk_text(text)):
            chunk_clean = chunk.strip()
            if not chunk_clean:
                continue
            meta: Dict[str, Any] = {
                "source": source_str,
                "text": chunk_clean,
                "sha": hashlib.sha1(chunk_clean.encode("utf-8")).hexdigest(),
                "chunk_type": "text",
            }
            if project_id:
                meta["project_id"] = project_id
            if rel_path:
                meta["rel_path"] = rel_path
            prepared.append((_chunk_id_from_meta(meta, idx), meta))
        return prepared

    source = str(doc.get("source") or "").strip()
    project_id = str(doc.get("project_id") or "").strip() or None
    rel_path = str(doc.get("rel_path") or "").strip() or None
    if not source:
        if project_id and rel_path:
            source = f"{project_id}/{rel_path}"
        elif rel_path:
            source = rel_path
        else:
            source = project_id or ""
    text = str(doc.get("text") or "")
    if not text.strip():
        return []

    file_sha = str(doc.get("file_sha") or "").strip() or None
    language = str(doc.get("language") or "").strip() or None
    chunk_type = str(doc.get("chunk_type") or "").strip() or "text"
    symbol = str(doc.get("symbol") or "").strip() or None
    prechunked = bool(doc.get("prechunked"))
    line_start = _coerce_optional_int(doc.get("line_start"))
    line_end = _coerce_optional_int(doc.get("line_end"))

    base_meta: Dict[str, Any] = {
        "source": source,
        "chunk_type": chunk_type,
    }
    if project_id:
        base_meta["project_id"] = project_id
    if rel_path:
        base_meta["rel_path"] = rel_path
    if file_sha:
        base_meta["file_sha"] = file_sha
    if language:
        base_meta["language"] = language
    if symbol:
        base_meta["symbol"] = symbol

    chunks: List[Tuple[str, Optional[int], Optional[int]]] = []
    if prechunked:
        chunks.append((text.strip(), line_start, line_end))
    else:
        for chunk in chunk_text(text):
            chunks.append((chunk.strip(), None, None))

    prepared = []
    for idx, (chunk_text_value, chunk_line_start, chunk_line_end) in enumerate(chunks):
        if not chunk_text_value:
            continue
        meta = dict(base_meta)
        meta["text"] = chunk_text_value
        meta["sha"] = hashlib.sha1(chunk_text_value.encode("utf-8")).hexdigest()
        if chunk_line_start is not None:
            meta["line_start"] = int(chunk_line_start)
        if chunk_line_end is not None:
            meta["line_end"] = int(chunk_line_end)
        if "project_id" not in meta:
            derived_project = _doc_project_id(meta)
            if derived_project:
                meta["project_id"] = derived_project
        if "rel_path" not in meta:
            derived_rel = _doc_rel_path(meta)
            if derived_rel:
                meta["rel_path"] = derived_rel
        prepared.append((_chunk_id_from_meta(meta, idx), meta))
    return prepared


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
    meta_map: Dict[str, Dict[str, Any]],
    top_k: int,
    project_id: Optional[str] = None,
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
        if not _doc_matches_scope(m, project_id):
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
        scored.append((score, _result_row(m, score)))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [row for _, row in scored[: max(1, top_k)]]


def _lexical_text_matches(
    text: str,
    ids: List[str],
    meta_map: Dict[str, Dict[str, Any]],
    top_k: int,
    project_id: Optional[str] = None,
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
        if not _doc_matches_scope(m, project_id):
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
        scored.append((score, _result_row(m, score)))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [row for _, row in scored[: max(1, top_k)]]


def _rebuild_index_locked() -> None:
    global _index, EMBEDDING_DIM

    if _get_faiss() is None or np is None:
        _index = None
        return

    ids_list: List[str] = _meta.get("ids", [])  # type: ignore[assignment]
    meta_map: Dict[str, Dict[str, Any]] = _meta.get("meta", {})  # type: ignore[assignment]
    kept_ids = [cid for cid in ids_list if cid in meta_map]
    _meta["ids"] = kept_ids

    if not kept_ids:
        dim = _current_dim()
        _index = _create_index() if dim is not None else None
        return

    embed_inputs = [_build_embed_input_from_meta(meta_map[cid]) for cid in kept_ids]
    vectors = _embed_texts_safe(embed_inputs)
    if not vectors:
        raise RuntimeError("rebuild index failed: no vectors returned")

    dim_from_vecs = len(vectors[0])
    if dim_from_vecs > 0:
        if EMBEDDING_DIM is None:
            EMBEDDING_DIM = dim_from_vecs  # type: ignore[assignment]
        _meta["dim"] = int(dim_from_vecs)

    vecs = _normalize(vectors)
    _index = _create_index()
    _index.add(vecs)


def _ensure_index_dim_locked(vector_dim: int) -> None:
    """Keep the FAISS index dimension aligned with the vectors being added."""
    global _index, EMBEDDING_DIM

    if vector_dim <= 0:
        raise RuntimeError("vector_dim must be positive")

    target_dim = int(vector_dim)
    try:
        idx_dim = _index.d if _index is not None else None  # type: ignore[attr-defined]
    except Exception:
        idx_dim = None

    EMBEDDING_DIM = target_dim  # type: ignore[assignment]
    _meta["dim"] = target_dim

    if _index is None:
        _index = _create_index()
        return

    if idx_dim in (None, target_dim):
        return

    logger.warning(
        "Rebuilding FAISS index to reconcile vector dimension mismatch: index dim=%s, vectors dim=%s",
        idx_dim,
        target_dim,
    )
    _rebuild_index_locked()


def remove_project_documents(project_id: str, rel_paths: Optional[set[str]] = None) -> int:
    _load_index()
    if not project_id:
        return 0

    removed = 0
    with _state_lock:
        ids_list: List[str] = list(_meta.get("ids", []))  # type: ignore[assignment]
        meta_map: Dict[str, Dict[str, Any]] = dict(_meta.get("meta", {}))  # type: ignore[assignment]

        kept_ids: List[str] = []
        kept_meta: Dict[str, Dict[str, Any]] = {}
        for cid in ids_list:
            meta = meta_map.get(cid)
            if not meta:
                continue
            if _doc_matches_scope(meta, project_id, rel_paths=rel_paths):
                removed += 1
                continue
            kept_ids.append(cid)
            kept_meta[cid] = meta

        if removed <= 0:
            return 0

        _meta["ids"] = kept_ids
        _meta["meta"] = kept_meta
        _rebuild_index_locked()
        _save_index()
    logger.info("remove_project_documents: removed %d chunks for project=%s", removed, project_id)
    return removed


def count_project_chunks(project_id: str) -> int:
    _load_index()
    if not project_id:
        return 0
    with _state_lock:
        meta_map: Dict[str, Dict[str, Any]] = _meta.get("meta", {})  # type: ignore[assignment]
        return sum(1 for meta in meta_map.values() if _doc_matches_scope(meta, project_id))


def list_project_symbols(project_id: str, q: str = "", limit: int = 80) -> List[Dict[str, Any]]:
    _load_index()
    if not project_id:
        return []

    q_clean = (q or "").strip().lower()
    rows: List[Dict[str, Any]] = []
    seen: set[tuple[str, str, Optional[int], Optional[int]]] = set()
    with _state_lock:
        ids_list: List[str] = _meta.get("ids", [])  # type: ignore[assignment]
        meta_map: Dict[str, Dict[str, Any]] = _meta.get("meta", {})  # type: ignore[assignment]
        for cid in ids_list:
            meta = meta_map.get(cid) or {}
            if not _doc_matches_scope(meta, project_id):
                continue
            if str(meta.get("chunk_type") or "") != "symbol":
                continue
            symbol = str(meta.get("symbol") or "").strip()
            rel_path = _doc_rel_path(meta)
            if not symbol or not rel_path:
                continue
            haystack = f"{symbol} {rel_path}".lower()
            if q_clean and q_clean not in haystack:
                continue
            line_start = _coerce_optional_int(meta.get("line_start"))
            line_end = _coerce_optional_int(meta.get("line_end"))
            key = (rel_path, symbol, line_start, line_end)
            if key in seen:
                continue
            seen.add(key)
            row = {
                "symbol": symbol,
                "path": rel_path,
                "language": meta.get("language"),
                "line_start": line_start,
                "line_end": line_end,
            }
            rows.append(row)
            if len(rows) >= limit:
                break
    return rows


def add_documents(docs: List[Tuple[str, str] | Dict[str, Any]]) -> int:
    """Index documents/chunks and persist FAISS+metadata state."""
    global _index, _meta, EMBEDDING_DIM

    _load_index()

    to_embed: List[str] = []
    metas: List[Tuple[str, Dict[str, Any]]] = []
    existing_meta: Dict[str, Dict[str, Any]] = _meta.get("meta", {})  # type: ignore[assignment]
    duplicate_count = 0
    empty_count = 0

    for doc in docs:
        prepared = _prepare_document_chunks(doc)
        if not prepared:
            empty_count += 1
            continue
        for chunk_id, meta in prepared:
            if chunk_id in existing_meta:
                duplicate_count += 1
                continue
            metas.append((chunk_id, meta))
            to_embed.append(_build_embed_input_from_meta(meta))

    if not to_embed:
        logger.info(
            "add_documents: nothing to add (duplicates=%d, empty_docs=%d, incoming_docs=%d)",
            duplicate_count,
            empty_count,
            len(docs),
        )
        return 0

    if _get_faiss() is None or np is None:
        with _state_lock:
            ids_list: List[str] = _meta.setdefault("ids", [])  # type: ignore[assignment]
            meta_map: Dict[str, Dict[str, Any]] = _meta.setdefault("meta", {})  # type: ignore[assignment]
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
            _ensure_index_dim_locked(int(vecs.shape[1]))
            _index.add(vecs)

            ids_list: List[str] = _meta.setdefault("ids", [])  # type: ignore[assignment]
            meta_map: Dict[str, Dict[str, Any]] = _meta.setdefault("meta", {})  # type: ignore[assignment]

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
            _ensure_index_dim_locked(int(vecs.shape[1]))
            _index.add(vecs)

            ids_list: List[str] = _meta.setdefault("ids", [])  # type: ignore[assignment]
            meta_map: Dict[str, Dict[str, Any]] = _meta.setdefault("meta", {})  # type: ignore[assignment]

            for cid, m in batch_metas:
                ids_list.append(cid)
                meta_map[cid] = m

        total_added += len(batch_metas)

    if total_added:
        _save_index()
    logger.info("add_documents: added %d chunks (total=%d)", total_added, len(_meta.get("ids", [])))
    return total_added


def _source_in_project(source: str, project_id: str) -> bool:
    clean_source = (source or "").strip().lower()
    clean_project = (project_id or "").strip().lower()
    if not clean_source or not clean_project:
        return False
    return clean_source == clean_project or clean_source.startswith(f"{clean_project}/")


def query(text: str, top_k: int = 6, project_id: str | None = None) -> List[dict]:
    """Query indexed evidence, scoped by project_id when provided."""
    global _index, _meta, EMBEDDING_DIM

    if not text:
        return []

    _load_index()

    with _state_lock:
        ids: List[str] = _meta.get("ids", [])  # type: ignore[assignment]
        meta_map: Dict[str, Dict[str, Any]] = _meta.get("meta", {})  # type: ignore[assignment]
        if not ids:
            return []

        lexical_first: List[dict] = _lexical_text_matches(text, ids, meta_map, top_k=top_k, project_id=project_id)
        if _is_path_like_query(text):
            lexical_path = _lexical_path_matches(text, ids, meta_map, top_k=top_k, project_id=project_id)
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

        if _get_faiss() is None or np is None or _index is None:
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
            search_k = min(max(top_k * 8, 24), len(ids))
            D, I = _index.search(qv, search_k)  # type: ignore[call-arg]
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
            if not _doc_matches_scope(m, project_id):
                continue
            row = _result_row(m, dist)
            key = ((row.get("source") or ""), (row.get("text") or ""))
            if key in seen:
                continue
            seen.add(key)
            results.append(row)
            if len(results) >= top_k:
                break

    return results[:top_k]


def get_retrieval_status() -> dict:
    """Return retrieval/index capability summary for readiness endpoints."""
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
