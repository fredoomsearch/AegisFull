from __future__ import annotations

"""
Project manifest builder and summarizer.

Why this module exists:
- Produce deterministic project inventory/architecture metadata.
- Power “what contains this ZIP/repo?” responses without LLM guessing.
"""

import json
import os
import re
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.services.project_introspection import build_architecture_profile, summarize_architecture

MANIFEST_FILENAME = ".aegis_manifest.json"
MAX_MANIFEST_FILES = int(os.getenv("AEGIS_PROJECT_MANIFEST_MAX_FILES", "1500"))
MAX_README_CHARS = int(os.getenv("AEGIS_PROJECT_README_MAX_CHARS", "3000"))

_LANG_BY_EXT = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".jsx": "javascript",
    ".html": "html",
    ".css": "css",
    ".scss": "scss",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".md": "markdown",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".kt": "kotlin",
    ".swift": "swift",
    ".dart": "dart",
    ".php": "php",
    ".sql": "sql",
    ".sh": "shell",
}

_PACKAGE_FILES = (
    "requirements.txt",
    "pyproject.toml",
    "package.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "package-lock.json",
    "Cargo.toml",
    "go.mod",
    "composer.json",
    "Gemfile",
    "pubspec.yaml",
)

_CONFIG_FILES = (
    ".env",
    ".env.example",
    "Dockerfile",
    "docker-compose.yml",
    "docker-compose.yaml",
    "nginx.conf",
    "alembic.ini",
    "pytest.ini",
    "tsconfig.json",
    "vite.config.ts",
    "vite.config.js",
    "next.config.js",
)

_ENTRYPOINT_HINTS = (
    "main.py",
    "app.py",
    "manage.py",
    "server.py",
    "wsgi.py",
    "asgi.py",
    "index.js",
    "src/main.ts",
    "src/main.js",
    "main.dart",
)

_INTERNAL_FILES = {
    ".aegis_manifest.json",
    ".aegis_ingest_state.json",
}


def _iter_files(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in {".git", "__pycache__", "node_modules", ".venv", "venv"}]
        for filename in filenames:
            if filename in _INTERNAL_FILES:
                continue
            yield Path(dirpath) / filename


def _read_text(path: Path, limit: int = MAX_README_CHARS) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")[:limit]
    except Exception:
        return ""


def _read_package_json(path: Path) -> Dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _detect_frameworks(file_paths: List[str], root: Path) -> List[str]:
    found: set[str] = set()
    lower_paths = [p.lower() for p in file_paths]

    if "pyproject.toml" in lower_paths or "requirements.txt" in lower_paths:
        req_path = root / "requirements.txt"
        pyproject = root / "pyproject.toml"
        text = _read_text(req_path, 4000) + "\n" + _read_text(pyproject, 4000)
        for name in ("fastapi", "django", "flask", "sqlalchemy", "streamlit"):
            if name in text.lower():
                found.add(name)

    if "package.json" in lower_paths:
        payload = _read_package_json(root / "package.json")
        dep_blob = json.dumps(payload.get("dependencies") or {}) + json.dumps(payload.get("devDependencies") or {})
        for name in ("react", "next", "vue", "angular", "vite", "express"):
            if name in dep_blob.lower():
                found.add(name)

    if "pubspec.yaml" in lower_paths:
        found.add("flutter")

    return sorted(found)


def _detect_entrypoints(file_paths: List[str]) -> List[str]:
    results: List[str] = []
    lower_paths = {path.lower(): path for path in file_paths}
    for hint in _ENTRYPOINT_HINTS:
        if hint.lower() in lower_paths:
            results.append(lower_paths[hint.lower()])
    return results[:20]


def _summarize_readme(root: Path) -> str:
    for candidate in ("README.md", "README.txt", "readme.md", "readme.txt"):
        path = root / candidate
        if path.exists() and path.is_file():
            text = _read_text(path)
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            summary = " ".join(lines[:12]).strip()
            return summary[:MAX_README_CHARS]
    return ""


def _key_files(file_paths: List[str]) -> List[str]:
    important: List[str] = []
    patterns = (
        "readme",
        "requirements.txt",
        "pyproject.toml",
        "package.json",
        "main.py",
        "app.py",
        "server.py",
        "dockerfile",
        "alembic.ini",
        "auth",
        "login",
        "jwt",
    )
    for path in file_paths:
        lowered = path.lower()
        if any(pattern in lowered for pattern in patterns):
            important.append(path)
    return important[:30]


def build_project_manifest(
    root: Path,
    project_id: str,
    *,
    chunk_count: int = 0,
    chunked_files: int = 0,
    skipped: Optional[Dict[str, int]] = None,
) -> Dict[str, Any]:
    """Build deterministic manifest snapshot from a project root directory."""
    file_tree: List[str] = []
    ext_counter: Counter[str] = Counter()
    total_bytes = 0
    total_files = 0
    total_dirs = 0

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in {".git", "__pycache__", "node_modules", ".venv", "venv"}]
        total_dirs += len(dirnames)
        for filename in filenames:
            if filename in _INTERNAL_FILES:
                continue
            path = Path(dirpath) / filename
            try:
                rel = str(path.relative_to(root))
                st = path.stat()
            except Exception:
                continue
            total_files += 1
            total_bytes += int(st.st_size)
            ext_counter[path.suffix.lower() or "(no_ext)"] += 1
            if len(file_tree) < MAX_MANIFEST_FILES:
                file_tree.append(rel)

    languages = Counter()
    for ext, count in ext_counter.items():
        lang = _LANG_BY_EXT.get(ext)
        if lang:
            languages[lang] += count

    frameworks = _detect_frameworks(file_tree, root)
    entrypoints = _detect_entrypoints(file_tree)
    package_files = [path for path in file_tree if Path(path).name in _PACKAGE_FILES]
    config_files = [path for path in file_tree if Path(path).name in _CONFIG_FILES or Path(path).name.lower() in {name.lower() for name in _CONFIG_FILES}]
    readme_summary = _summarize_readme(root)
    key_files = _key_files(file_tree)

    manifest = {
        "project_id": project_id,
        "root_path": str(root),
        "generated_at": int(os.path.getmtime(root)),
        "stats": {
            "files": total_files,
            "dirs": total_dirs,
            "bytes": total_bytes,
            "chunk_count": int(chunk_count),
            "chunked_files": int(chunked_files),
            "skipped": skipped or {},
        },
        "file_tree": file_tree,
        "languages": [{"name": name, "count": count} for name, count in languages.most_common(12)],
        "frameworks": frameworks,
        "entrypoints": entrypoints,
        "package_files": package_files,
        "config_files": config_files,
        "key_files": key_files,
        "readme_summary": readme_summary,
    }
    manifest["architecture"] = build_architecture_profile(manifest)
    return manifest


def save_project_manifest(
    root: Path,
    project_id: str,
    *,
    chunk_count: int = 0,
    chunked_files: int = 0,
    skipped: Optional[Dict[str, int]] = None,
    target: Optional[Path] = None,
) -> Path:
    """Persist manifest JSON under project root (or custom target)."""
    manifest = build_project_manifest(
        root,
        project_id,
        chunk_count=chunk_count,
        chunked_files=chunked_files,
        skipped=skipped,
    )
    out = target or (root / MANIFEST_FILENAME)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def load_project_manifest(path: Path | str) -> Optional[Dict[str, Any]]:
    try:
        target = Path(path)
        if target.is_dir():
            target = target / MANIFEST_FILENAME
        if not target.exists():
            return None
        payload = json.loads(target.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else None
    except Exception:
        return None


def summarize_manifest(manifest: Dict[str, Any], *, lang: str = "es") -> str:
    """Render concise human summary from canonical manifest data."""
    es = (lang or "es").lower().startswith("es")
    stats = manifest.get("stats") if isinstance(manifest.get("stats"), dict) else {}
    languages = ", ".join(
        f"{row.get('name')} ({row.get('count')})"
        for row in (manifest.get("languages") or [])[:6]
        if isinstance(row, dict)
    ) or "-"
    frameworks = ", ".join(manifest.get("frameworks") or []) or "-"
    entrypoints = ", ".join((manifest.get("entrypoints") or [])[:6]) or "-"
    key_files = ", ".join((manifest.get("key_files") or [])[:8]) or "-"
    readme_summary = str(manifest.get("readme_summary") or "").strip()

    if es:
        lines = [
            f"Proyecto activo: {manifest.get('project_id')}",
            f"Archivos: {stats.get('files', 0)} | Carpetas: {stats.get('dirs', 0)} | Chunks: {stats.get('chunk_count', 0)}",
            f"Lenguajes: {languages}",
            f"Frameworks: {frameworks}",
            f"Entrypoints: {entrypoints}",
            f"Archivos clave: {key_files}",
        ]
        if readme_summary:
            lines.append(f"README: {readme_summary}")
        architecture = manifest.get("architecture") if isinstance(manifest.get("architecture"), dict) else None
        if architecture:
            lines.append(summarize_architecture(architecture, lang=lang))
        return "\n".join(lines)

    lines = [
        f"Active project: {manifest.get('project_id')}",
        f"Files: {stats.get('files', 0)} | Dirs: {stats.get('dirs', 0)} | Chunks: {stats.get('chunk_count', 0)}",
        f"Languages: {languages}",
        f"Frameworks: {frameworks}",
        f"Entrypoints: {entrypoints}",
        f"Key files: {key_files}",
    ]
    if readme_summary:
        lines.append(f"README: {readme_summary}")
    architecture = manifest.get("architecture") if isinstance(manifest.get("architecture"), dict) else None
    if architecture:
        lines.append(summarize_architecture(architecture, lang=lang))
    return "\n".join(lines)


def infer_file_focus(text: str, manifest: Dict[str, Any]) -> Optional[str]:
    query = (text or "").lower()
    for path in manifest.get("file_tree") or []:
        if isinstance(path, str) and path.lower() in query:
            return path
    if not query:
        return None
    basename_matches = []
    for path in manifest.get("file_tree") or []:
        if not isinstance(path, str):
            continue
        name = Path(path).name.lower()
        if name and name in query:
            basename_matches.append(path)
    if basename_matches:
        return basename_matches[0]

    query_tokens = {tok for tok in re.split(r"[^a-zA-Z0-9_./-]+", query) if tok}
    stem_matches: List[str] = []
    normalized_query = re.sub(r"[^a-zA-Z0-9]+", " ", query).strip()
    for path in manifest.get("file_tree") or []:
        if not isinstance(path, str):
            continue
        file_name = Path(path).name
        stem = Path(file_name).stem.lower()
        if not stem:
            continue
        stem_phrase = re.sub(r"[_\-.]+", " ", stem).strip()
        if stem in query_tokens or (stem_phrase and stem_phrase in normalized_query):
            stem_matches.append(path)
    unique_matches = sorted(set(stem_matches))
    return unique_matches[0] if len(unique_matches) == 1 else None


def manifest_contains_auth_hints(manifest: Dict[str, Any]) -> List[str]:
    results: List[str] = []
    for path in manifest.get("key_files") or []:
        lowered = str(path).lower()
        if any(token in lowered for token in ("auth", "login", "jwt", "oauth", "token")):
            results.append(str(path))
    return results[:10]
