#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

# Defaults (override with env vars or CLI flags).
DEFAULT_MAX_FILES = int(os.getenv("AEGIS_INGEST_MAX_FILES", "1500"))
DEFAULT_MAX_FILE_BYTES = int(os.getenv("AEGIS_INGEST_MAX_FILE_BYTES", "250000"))
DEFAULT_MAX_TOTAL_BYTES = int(os.getenv("AEGIS_INGEST_MAX_TOTAL_BYTES", "7000000"))
DEFAULT_BATCH_FILES = int(os.getenv("AEGIS_INGEST_BATCH_FILES", "200"))
DEFAULT_MANIFEST_MAX_FILES = int(os.getenv("AEGIS_INGEST_MANIFEST_MAX_FILES", "4000"))
MAX_EXTRACT_CHARS = int(os.getenv("AEGIS_INGEST_MAX_EXTRACT_CHARS", "200000"))
MAX_EXTRACT_PAGES = int(os.getenv("AEGIS_INGEST_MAX_EXTRACT_PAGES", "30"))
MAX_EXTRACT_ROWS = int(os.getenv("AEGIS_INGEST_MAX_EXTRACT_ROWS", "2000"))

try:
    from pypdf import PdfReader  # type: ignore
except Exception:
    PdfReader = None  # type: ignore

try:
    from docx import Document  # type: ignore
except Exception:
    Document = None  # type: ignore

try:
    from openpyxl import load_workbook  # type: ignore
except Exception:
    load_workbook = None  # type: ignore

try:
    from pptx import Presentation  # type: ignore
except Exception:
    Presentation = None  # type: ignore

def _apply_thread_env(threads: int) -> None:
    """Allow embedding to use more CPU threads if configured."""
    for var in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        os.environ.setdefault(var, str(threads))


raw_threads = os.getenv("AEGIS_INGEST_THREADS", "").strip()
if raw_threads.isdigit() and int(raw_threads) > 0:
    _apply_thread_env(int(raw_threads))
else:
    # Default to using most CPU cores to speed up embeddings.
    cpu_count = os.cpu_count() or 1
    _apply_thread_env(max(1, cpu_count - 1))

from app.services.retrieval_service import add_documents, count_project_chunks, remove_project_documents  # noqa: E402
from app.services.project_ingest_state import load_project_ingest_state, save_project_ingest_state  # noqa: E402
from app.services.project_manifest import save_project_manifest  # noqa: E402

DEFAULT_EXTS = {
    ".py",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".html",
    ".css",
    ".scss",
    ".md",
    ".txt",
    ".json",
    ".yml",
    ".yaml",
    ".toml",
    ".ini",
    ".env",
    ".sql",
    ".csv",
    ".tsv",
    ".xml",
    ".conf",
    ".cfg",
    ".properties",
    ".rst",
    ".mdx",
    ".sh",
    ".bash",
    ".zsh",
    ".go",
    ".rs",
    ".java",
    ".kt",
    ".php",
    ".pdf",
    ".docx",
    ".xlsx",
    ".pptx",
}

EXCLUDED_DIRS = {
    ".git",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    "node_modules",
    "venv",
    ".venv",
    "dist",
    "build",
    "data",
    "uploads",
    "logs",
    "artifacts",
}

EXCLUDED_FILES = {
    "aegis.db",
    ".aegis_manifest.json",
    ".aegis_ingest_state.json",
}

CODE_EXTS = {
    ".py",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".go",
    ".rs",
    ".java",
    ".kt",
    ".php",
    ".swift",
    ".dart",
    ".sh",
}

LANG_BY_EXT = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".kt": "kotlin",
    ".php": "php",
    ".swift": "swift",
    ".dart": "dart",
    ".sh": "shell",
}

CODE_SYMBOL_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^\s*(?:async\s+)?def\s+([A-Za-z_]\w*)\s*\(", re.MULTILINE),
    re.compile(r"^\s*class\s+([A-Za-z_]\w*)\b", re.MULTILINE),
    re.compile(r"^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\(", re.MULTILINE),
    re.compile(r"^\s*(?:export\s+)?class\s+([A-Za-z_$][\w$]*)\b", re.MULTILINE),
    re.compile(r"^\s*(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\(", re.MULTILINE),
    re.compile(r"^\s*func\s+([A-Za-z_]\w*)\s*\(", re.MULTILINE),
    re.compile(r"^\s*fn\s+([A-Za-z_]\w*)\s*\(", re.MULTILINE),
    re.compile(r"^\s*(?:public|private|protected|internal|open|final|suspend|inline|\s)*\s*fun\s+([A-Za-z_]\w*)\s*\(", re.MULTILINE),
    re.compile(r"^\s*(?:public|private|protected|internal|open|final|\s)*\s*class\s+([A-Za-z_]\w*)\b", re.MULTILINE),
)

CODE_WINDOW_LINES = max(40, int(os.getenv("AEGIS_CODE_WINDOW_LINES", "80")))
CODE_WINDOW_OVERLAP = max(10, int(os.getenv("AEGIS_CODE_WINDOW_OVERLAP", "20")))
MAX_SYMBOLS_PER_FILE = max(10, int(os.getenv("AEGIS_INGEST_MAX_SYMBOLS_PER_FILE", "80")))


def _iter_files(root: Path) -> Iterable[Path]:
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDED_DIRS]
        for fname in filenames:
            if fname in EXCLUDED_FILES:
                continue
            path = Path(dirpath) / fname
            yield path


def _truncate_text(text: str, limit: int = MAX_EXTRACT_CHARS) -> str:
    if not text:
        return ""
    if limit <= 0 or len(text) <= limit:
        return text
    return text[:limit]


def _read_pdf(path: Path) -> str:
    if PdfReader is None:
        return ""
    try:
        reader = PdfReader(str(path))
    except Exception:
        return ""

    chunks: List[str] = []
    pages = reader.pages[: max(1, MAX_EXTRACT_PAGES)]
    for page in pages:
        try:
            txt = page.extract_text() or ""
        except Exception:
            txt = ""
        if txt.strip():
            chunks.append(txt.strip())
        if sum(len(c) for c in chunks) >= MAX_EXTRACT_CHARS:
            break
    return _truncate_text("\n\n".join(chunks))


def _read_docx(path: Path) -> str:
    if Document is None:
        return ""
    try:
        doc = Document(str(path))
    except Exception:
        return ""
    chunks: List[str] = []
    for p in doc.paragraphs:
        txt = (p.text or "").strip()
        if txt:
            chunks.append(txt)
        if sum(len(c) for c in chunks) >= MAX_EXTRACT_CHARS:
            break
    return _truncate_text("\n".join(chunks))


def _read_xlsx(path: Path) -> str:
    if load_workbook is None:
        return ""
    try:
        wb = load_workbook(str(path), read_only=True, data_only=True)
    except Exception:
        return ""

    chunks: List[str] = []
    row_budget = max(1, MAX_EXTRACT_ROWS)
    seen_rows = 0
    try:
        for ws in wb.worksheets:
            chunks.append(f"# Sheet: {ws.title}")
            for row in ws.iter_rows(values_only=True):
                values = [str(v).strip() for v in row if v is not None and str(v).strip()]
                if values:
                    chunks.append(" | ".join(values))
                seen_rows += 1
                if seen_rows >= row_budget or sum(len(c) for c in chunks) >= MAX_EXTRACT_CHARS:
                    break
            if seen_rows >= row_budget or sum(len(c) for c in chunks) >= MAX_EXTRACT_CHARS:
                break
    finally:
        try:
            wb.close()
        except Exception:
            pass
    return _truncate_text("\n".join(chunks))


def _read_pptx(path: Path) -> str:
    if Presentation is None:
        return ""
    try:
        prs = Presentation(str(path))
    except Exception:
        return ""
    chunks: List[str] = []
    for idx, slide in enumerate(prs.slides[: max(1, MAX_EXTRACT_PAGES)], start=1):
        chunks.append(f"# Slide {idx}")
        for shape in slide.shapes:
            txt = getattr(shape, "text", "") or ""
            txt = txt.strip()
            if txt:
                chunks.append(txt)
            if sum(len(c) for c in chunks) >= MAX_EXTRACT_CHARS:
                break
        if sum(len(c) for c in chunks) >= MAX_EXTRACT_CHARS:
            break
    return _truncate_text("\n".join(chunks))


def _read_text(path: Path) -> str:
    try:
        suffix = path.suffix.lower()
        if suffix == ".pdf":
            return _read_pdf(path)
        if suffix == ".docx":
            return _read_docx(path)
        if suffix == ".xlsx":
            return _read_xlsx(path)
        if suffix == ".pptx":
            return _read_pptx(path)
        return _truncate_text(path.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return ""


def _language_for_path(path: Path) -> str:
    return LANG_BY_EXT.get(path.suffix.lower(), "text")


def _file_text_sha(text: str) -> str:
    return hashlib.sha1((text or "").encode("utf-8", errors="ignore")).hexdigest()


def _build_document_doc(
    *,
    project_id: str,
    rel_path: str,
    text: str,
    file_sha: str,
    language: str,
    chunk_type: str = "document",
    symbol: Optional[str] = None,
    line_start: Optional[int] = None,
    line_end: Optional[int] = None,
    prechunked: bool = False,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "project_id": project_id,
        "rel_path": rel_path,
        "source": f"{project_id}/{rel_path}",
        "text": text,
        "file_sha": file_sha,
        "language": language,
        "chunk_type": chunk_type,
        "prechunked": prechunked,
    }
    if symbol:
        payload["symbol"] = symbol
    if line_start is not None:
        payload["line_start"] = int(line_start)
    if line_end is not None:
        payload["line_end"] = int(line_end)
    return payload


def _collect_symbol_boundaries(text: str) -> List[Tuple[Optional[str], int, int]]:
    matches: List[Tuple[Optional[str], int, int]] = []
    seen: set[Tuple[Optional[str], int]] = set()
    for pattern in CODE_SYMBOL_PATTERNS:
        for match in pattern.finditer(text):
            symbol = match.group(1).strip() if match.groups() else None
            line_start = text.count("\n", 0, match.start()) + 1
            key = (symbol, line_start)
            if key in seen:
                continue
            seen.add(key)
            matches.append((symbol, line_start, match.start()))
    matches.sort(key=lambda item: item[1])
    return matches[:MAX_SYMBOLS_PER_FILE]


def _build_code_docs(project_id: str, rel_path: str, text: str, language: str) -> List[Dict[str, Any]]:
    file_sha = _file_text_sha(text)
    lines = text.splitlines()
    total_lines = len(lines)
    docs: List[Dict[str, Any]] = []

    if total_lines <= 0:
        return docs

    module_end = min(total_lines, max(CODE_WINDOW_LINES, 120))
    module_text = "\n".join(lines[:module_end]).strip()
    if module_text:
        docs.append(
            _build_document_doc(
                project_id=project_id,
                rel_path=rel_path,
                text=module_text,
                file_sha=file_sha,
                language=language,
                chunk_type="module",
                line_start=1,
                line_end=module_end,
                prechunked=True,
            )
        )

    boundaries = _collect_symbol_boundaries(text)
    for idx, (symbol, line_start, _) in enumerate(boundaries):
        next_line = boundaries[idx + 1][1] - 1 if idx + 1 < len(boundaries) else total_lines
        line_end = min(total_lines, max(line_start, next_line))
        symbol_text = "\n".join(lines[line_start - 1 : line_end]).strip()
        if not symbol_text:
            continue
        docs.append(
            _build_document_doc(
                project_id=project_id,
                rel_path=rel_path,
                text=symbol_text,
                file_sha=file_sha,
                language=language,
                chunk_type="symbol",
                symbol=symbol,
                line_start=line_start,
                line_end=line_end,
                prechunked=True,
            )
        )

    step = max(1, CODE_WINDOW_LINES - CODE_WINDOW_OVERLAP)
    start_line = 1
    while start_line <= total_lines:
        end_line = min(total_lines, start_line + CODE_WINDOW_LINES - 1)
        window_text = "\n".join(lines[start_line - 1 : end_line]).strip()
        if window_text:
            docs.append(
                _build_document_doc(
                    project_id=project_id,
                    rel_path=rel_path,
                    text=window_text,
                    file_sha=file_sha,
                    language=language,
                    chunk_type="window",
                    line_start=start_line,
                    line_end=end_line,
                    prechunked=True,
                )
            )
        if end_line >= total_lines:
            break
        start_line += step

    return docs


def _build_generic_doc(project_id: str, rel_path: str, text: str, language: str) -> Dict[str, Any]:
    return _build_document_doc(
        project_id=project_id,
        rel_path=rel_path,
        text=text,
        file_sha=_file_text_sha(text),
        language=language,
        chunk_type="document",
        prechunked=False,
    )


def _build_file_docs(project_id: str, rel_path: str, path: Path, text: str) -> List[Dict[str, Any]]:
    language = _language_for_path(path)
    if path.suffix.lower() in CODE_EXTS:
        docs = _build_code_docs(project_id, rel_path, text, language)
        if docs:
            return docs
    return [_build_generic_doc(project_id, rel_path, text, language)]


def ingest(
    root: Path,
    max_files: int,
    max_file_bytes: int,
    max_total_bytes: int,
    *,
    project_id: str | None = None,
    manifest_out: Path | None = None,
) -> int:
    """Walk files, chunk text, embed, and write to the FAISS index."""
    project_key = (project_id or root.name).strip() or root.name
    previous_state = load_project_ingest_state(root)
    previous_hashes = previous_state.get("file_hashes") if isinstance(previous_state.get("file_hashes"), dict) else {}
    previous_hashes = {str(k): str(v) for k, v in previous_hashes.items()}

    docs: List[Dict[str, Any]] = []
    manifest_lines: List[str] = []
    current_hashes: Dict[str, str] = {}
    total_bytes = 0
    scanned_files = 0
    ingested_files = 0
    total_added = 0
    total_removed = 0
    skipped_ext = 0
    skipped_large = 0
    skipped_empty = 0
    skipped_quota = 0
    manifest_truncated = False
    changed_paths: set[str] = set()

    for path in _iter_files(root):
        if not path.is_file():
            continue
        scanned_files += 1

        try:
            size = path.stat().st_size
        except OSError:
            continue

        rel = str(path.relative_to(root))
        if len(manifest_lines) < DEFAULT_MANIFEST_MAX_FILES:
            manifest_lines.append(f"{rel}\t{size}")
        else:
            manifest_truncated = True

        if ingested_files >= max_files:
            skipped_quota += 1
            continue

        ext = path.suffix.lower()
        if DEFAULT_EXTS and ext not in DEFAULT_EXTS:
            skipped_ext += 1
            continue

        if max_file_bytes and size > max_file_bytes:
            skipped_large += 1
            continue
        if max_total_bytes and total_bytes + size > max_total_bytes:
            skipped_quota += 1
            break

        text = _read_text(path)
        if not text.strip():
            skipped_empty += 1
            continue

        text_sha = _file_text_sha(text)
        current_hashes[rel] = text_sha
        total_bytes += size
        ingested_files += 1

        if previous_hashes.get(rel) == text_sha:
            continue

        changed_paths.add(rel)
        docs.extend(_build_file_docs(project_key, rel, path, text))

    deleted_paths = set(previous_hashes) - set(current_hashes)

    summary_lines = [
        f"ROOT_PATH: {root}",
        f"PROJECT_ID: {project_key}",
        f"SCANNED_FILES: {scanned_files}",
        f"INGESTED_TEXT_FILES: {ingested_files}",
        f"CHANGED_FILES: {len(changed_paths)}",
        f"DELETED_FILES: {len(deleted_paths)}",
        f"SKIPPED_EXT: {skipped_ext}",
        f"SKIPPED_FILE_SIZE: {skipped_large}",
        f"SKIPPED_EMPTY: {skipped_empty}",
        f"SKIPPED_QUOTA_OR_LIMIT: {skipped_quota}",
        "",
        "FILE_INVENTORY (REL_PATH<TAB>SIZE_BYTES):",
        *manifest_lines,
    ]
    if manifest_truncated:
        summary_lines.append(f"... (manifest truncated at {DEFAULT_MANIFEST_MAX_FILES} files)")

    docs.append(
        _build_document_doc(
            project_id=project_key,
            rel_path="__manifest__/files.tsv",
            text="\n".join(summary_lines),
            file_sha=_file_text_sha("\n".join(summary_lines)),
            language="manifest",
            chunk_type="manifest",
            prechunked=False,
        )
    )

    rel_paths_to_refresh = set(changed_paths) | set(deleted_paths) | {"__manifest__/files.tsv"}
    if rel_paths_to_refresh:
        total_removed = remove_project_documents(project_key, rel_paths=rel_paths_to_refresh)

    print(
        f"[ingest] collected text_files={ingested_files} changed={len(changed_paths)} "
        f"deleted={len(deleted_paths)} bytes={total_bytes}",
        flush=True,
    )
    print("[ingest] embedding + indexing...", flush=True)
    total_added = add_documents(docs)

    total_chunks = count_project_chunks(project_key)

    if not current_hashes and total_chunks == 0:
        print("No files ingested (nothing matched filters or root is empty).")

    if manifest_out is not None:
        save_project_manifest(
            root,
            project_id=project_key,
            chunk_count=total_chunks,
            chunked_files=ingested_files,
            skipped={
                "ext": skipped_ext,
                "size": skipped_large,
                "empty": skipped_empty,
                "quota_or_limit": skipped_quota,
            },
            target=manifest_out,
        )

    save_project_ingest_state(
        root,
        project_id=project_key,
        file_hashes=current_hashes,
        chunk_count=total_chunks,
        metadata={
            "scanned_files": scanned_files,
            "ingested_files": ingested_files,
            "changed_files": len(changed_paths),
            "deleted_files": len(deleted_paths),
            "removed_chunks": total_removed,
        },
    )

    print(
        f"[ingest] summary scanned={scanned_files} text_files={ingested_files} "
        f"skipped_ext={skipped_ext} skipped_size={skipped_large} "
        f"skipped_empty={skipped_empty} skipped_quota={skipped_quota} "
        f"removed_chunks={total_removed}",
        flush=True,
    )
    print(f"[ingest] done files={ingested_files} chunks_added={total_added} chunks_total={total_chunks}", flush=True)
    return total_chunks


def main() -> int:
    parser = argparse.ArgumentParser(description="Ingest a repo and build FAISS embeddings.")
    parser.add_argument("--root", required=True, help="Root directory to ingest")
    parser.add_argument("--max-files", type=int, default=DEFAULT_MAX_FILES)
    parser.add_argument("--max-file-bytes", type=int, default=DEFAULT_MAX_FILE_BYTES)
    parser.add_argument("--max-total-bytes", type=int, default=DEFAULT_MAX_TOTAL_BYTES)
    parser.add_argument("--project-id", default="", help="Optional stable project id for manifest metadata")
    parser.add_argument("--manifest-out", default="", help="Optional manifest output path")

    args = parser.parse_args()
    root = Path(args.root).resolve()
    if not root.exists() or not root.is_dir():
        print("Invalid root:", root)
        return 1

    try:
        ingest(
            root,
            args.max_files,
            args.max_file_bytes,
            args.max_total_bytes,
            project_id=(args.project_id or "").strip() or None,
            manifest_out=Path(args.manifest_out).resolve() if str(args.manifest_out or "").strip() else None,
        )
    except Exception as exc:
        print("Ingest failed:", exc)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
