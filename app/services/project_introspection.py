from __future__ import annotations

"""
Project introspection utilities.

Why this module exists:
- Provide deterministic file/symbol/architecture extraction for project tools.
- Support agent evidence retrieval without relying on LLM inference.
"""

import ast
import os
import re
import hashlib
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Iterable, List, Optional, Tuple

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

PY_IMPORT_PATTERN = re.compile(r"^\s*import\s+([A-Za-z_][\w.,\s]*)", re.MULTILINE)
PY_FROM_IMPORT_PATTERN = re.compile(r"^\s*from\s+([.\w]+)\s+import\s+([^\n#]+)", re.MULTILINE)
JS_IMPORT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"""^\s*import(?:[\s\w{},*$]+?\s+from\s+)?['"]([^'"]+)['"]""", re.MULTILINE),
    re.compile(r"""^\s*export\s+.*?\s+from\s+['"]([^'"]+)['"]""", re.MULTILINE),
    re.compile(r"""require\(\s*['"]([^'"]+)['"]\s*\)""", re.MULTILINE),
)
ROUTE_METHODS = {"get", "post", "put", "delete", "patch", "options", "head", "all", "websocket"}
PY_ROUTE_DECORATOR_PATTERN = re.compile(r"""@([A-Za-z_][\w.]*)\.(get|post|put|delete|patch|options|head|all|websocket|route|api_route)\s*\(""")
ROUTE_STRING_PATTERN = re.compile(r"""['"](/[^'"]*)['"]""")
ROUTE_METHODS_PATTERN = re.compile(r"""methods\s*=\s*\[([^\]]+)\]|methods\s*=\s*\(([^\)]+)\)""", re.IGNORECASE)
JS_ROUTE_PATTERN = re.compile(r"""\b(?:router|app)\.(get|post|put|delete|patch|options|head|all)\(\s*(['"`])([^'"`]+)\2""")
IDENTIFIER_PATTERN = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*\b")
VALID_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
PY_ENV_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"""os\.getenv\(\s*['"]([A-Z][A-Z0-9_]*)['"]"""),
    re.compile(r"""os\.environ\.get\(\s*['"]([A-Z][A-Z0-9_]*)['"]"""),
    re.compile(r"""os\.environ\[\s*['"]([A-Z][A-Z0-9_]*)['"]\s*\]"""),
)
JS_ENV_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"""process\.env\.([A-Z][A-Z0-9_]*)"""),
    re.compile(r"""process\.env\[\s*['"]([A-Z][A-Z0-9_]*)['"]\s*\]"""),
    re.compile(r"""import\.meta\.env\.([A-Z][A-Z0-9_]*)"""),
)

MAX_SYMBOLS_PER_FILE = max(10, int(os.getenv("AEGIS_INGEST_MAX_SYMBOLS_PER_FILE", "80")))
_ARCH_QUESTION_HINTS = (
    "architecture",
    "arquitectura",
    "how is this project organized",
    "como esta organizado",
    "cómo está organizado",
    "structure",
    "estructura",
    "design",
    "diseño",
    "system design",
    "stack",
    "capabilities",
    "capacidades",
)


def language_for_path(path: Path) -> str:
    """Infer programming language label from file extension."""
    return LANG_BY_EXT.get(path.suffix.lower(), "text")


def collect_symbol_boundaries(text: str, max_symbols: int = MAX_SYMBOLS_PER_FILE) -> List[Tuple[Optional[str], int, int]]:
    """Extract lightweight symbol boundaries for chunk metadata and lookups."""
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
    return matches[:max_symbols]


def scan_file_symbols(path: Path, *, rel_path: Optional[str] = None) -> List[Dict[str, Any]]:
    if path.suffix.lower() not in CODE_EXTS:
        return []
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return []
    if not text.strip():
        return []

    boundaries = collect_symbol_boundaries(text)
    if not boundaries:
        return []

    lines = text.splitlines()
    total_lines = len(lines)
    rel = rel_path or path.name
    language = language_for_path(path)
    rows: List[Dict[str, Any]] = []

    for idx, (symbol, line_start, _offset) in enumerate(boundaries):
        if not symbol:
            continue
        next_line = boundaries[idx + 1][1] - 1 if idx + 1 < len(boundaries) else total_lines
        line_end = min(total_lines, max(line_start, next_line))
        rows.append(
            {
                "symbol": symbol,
                "path": rel,
                "language": language,
                "line_start": int(line_start),
                "line_end": int(line_end),
            }
        )
    return rows


def _iter_manifest_code_files(root: Path, manifest: Optional[Dict[str, Any]] = None) -> Iterable[Tuple[Path, str]]:
    file_tree = manifest.get("file_tree") if isinstance(manifest, dict) else None
    if isinstance(file_tree, list):
        for rel in file_tree:
            if not isinstance(rel, str):
                continue
            path = (root / rel).resolve()
            if path.exists() and path.is_file() and path.suffix.lower() in CODE_EXTS:
                yield path, rel
        return

    for path in root.rglob("*"):
        if path.is_file() and path.suffix.lower() in CODE_EXTS:
            try:
                yield path, str(path.relative_to(root))
            except Exception:
                continue


def scan_project_symbols(
    root: Path,
    *,
    manifest: Optional[Dict[str, Any]] = None,
    q: str = "",
    limit: int = 80,
) -> List[Dict[str, Any]]:
    q_clean = (q or "").strip().lower()
    rows: List[Dict[str, Any]] = []
    seen: set[tuple[str, str, int, int]] = set()
    for path, rel in _iter_manifest_code_files(root, manifest):
        for row in scan_file_symbols(path, rel_path=rel):
            haystack = f"{row['symbol']} {row['path']}".lower()
            if q_clean and q_clean not in haystack:
                continue
            key = (row["path"], row["symbol"], int(row["line_start"]), int(row["line_end"]))
            if key in seen:
                continue
            seen.add(key)
            rows.append(row)
            if len(rows) >= max(1, limit):
                return rows
    return rows


def fuzzy_search_project_files(
    manifest: Optional[Dict[str, Any]],
    *,
    q: str = "",
    limit: int = 80,
) -> List[Dict[str, Any]]:
    file_tree = manifest.get("file_tree") if isinstance(manifest, dict) else None
    if not isinstance(file_tree, list):
        return []
    q_clean = (q or "").strip().lower()
    if not q_clean:
        return [{"path": str(path), "score": 0.0} for path in file_tree[: max(1, limit)] if isinstance(path, str)]

    tokens = [tok for tok in re.split(r"[^a-zA-Z0-9_./-]+", q_clean) if tok]
    scored: List[Tuple[float, str]] = []
    for raw in file_tree:
        if not isinstance(raw, str):
            continue
        path = raw.strip()
        lower = path.lower()
        basename = Path(path).name.lower()
        score = 0.0
        if q_clean == lower:
            score += 200.0
        if q_clean == basename:
            score += 180.0
        if q_clean in lower:
            score += 100.0
        if q_clean in basename:
            score += 80.0
        for tok in tokens:
            if tok in basename:
                score += 24.0
            if tok in lower:
                score += 12.0
        if lower.startswith(q_clean.rstrip("/") + "/"):
            score += 60.0
        if score <= 0:
            continue
        scored.append((score, path))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [{"path": path, "score": round(score, 3)} for score, path in scored[: max(1, limit)]]


def summarize_project_subtree(
    manifest: Optional[Dict[str, Any]],
    *,
    prefix: str = "",
    lang: str = "es",
    limit: int = 30,
) -> str:
    file_tree = manifest.get("file_tree") if isinstance(manifest, dict) else None
    if not isinstance(file_tree, list):
        return ""
    prefix_clean = str(prefix or "").strip().strip("/")
    rows: List[str] = []
    for raw in file_tree:
        if not isinstance(raw, str):
            continue
        path = raw.strip()
        if prefix_clean:
            if path == prefix_clean or path.startswith(prefix_clean + "/"):
                rows.append(path)
        else:
            rows.append(path)
        if len(rows) >= max(1, limit):
            break
    if not rows:
        if (lang or "es").lower().startswith("es"):
            return f"No encontré archivos bajo {prefix_clean or 'la raíz del proyecto'}."
        return f"I couldn't find files under {prefix_clean or 'the project root'}."
    header = (
        f"Archivos bajo {prefix_clean}:"
        if (lang or "es").lower().startswith("es")
        else f"Files under {prefix_clean}:"
    ) if prefix_clean else (
        "Archivos del proyecto:"
        if (lang or "es").lower().startswith("es")
        else "Project files:"
    )
    body = "\n".join(f"- {row}" for row in rows)
    return f"{header}\n{body}"


def build_architecture_profile(manifest: Dict[str, Any]) -> Dict[str, Any]:
    file_tree = [str(path) for path in (manifest.get("file_tree") or []) if isinstance(path, str)]
    lower_paths = [path.lower() for path in file_tree]
    frameworks = [str(item).lower() for item in (manifest.get("frameworks") or [])]
    key_files = [str(path) for path in (manifest.get("key_files") or []) if isinstance(path, str)]
    config_files = [str(path) for path in (manifest.get("config_files") or []) if isinstance(path, str)]
    entrypoints = [str(path) for path in (manifest.get("entrypoints") or []) if isinstance(path, str)]

    def has_any(*needles: str) -> bool:
        return any(needle in path for path in lower_paths for needle in needles)

    top_dirs = Counter(path.split("/", 1)[0] for path in file_tree if "/" in path)
    backend = bool(set(frameworks) & {"fastapi", "flask", "django", "express", "spring"}) or has_any("app/api", "backend/", "routes/", "controllers/", "server.py", "main.py")
    frontend = bool(set(frameworks) & {"react", "next", "vue", "angular", "flutter"}) or has_any("ui/", "src/components", "pages/", "frontend/")
    auth = any(token in path.lower() for path in key_files + file_tree for token in ("auth", "jwt", "oauth", "login", "token"))
    database = has_any("models", "migrations", "alembic", ".sql", "postgres", "mysql", "sqlite", "dynamodb")
    tests = has_any("tests/", "test_", "spec.")
    infra = any(name.lower() in {"dockerfile", "docker-compose.yml", "docker-compose.yaml", "nginx.conf"} for name in config_files) or has_any(".github/workflows", "terraform", "prometheus", "nginx")
    serverless = has_any("lambda", "serverless", "template.yaml", "template.yml", "api-gateway")
    ci = has_any(".github/workflows", ".gitlab-ci", "azure-pipelines", "jenkins")
    monitoring = has_any("prometheus", "grafana", "monitoring", "otel", "telemetry")
    ai_rag = has_any("embedding", "retrieval", "faiss", "rag", "llm", "vector")
    image = has_any("image", "comfyui", "diffusion", "stable-diffusion")
    crypto = has_any("crypto", "ohlcv", "trade", "binance", "prediction")
    security = auth or has_any("csp", "helmet", "secure", "oauth", "jwt")

    layers: List[str] = []
    for name, enabled in (
        ("backend", backend),
        ("frontend", frontend),
        ("auth", auth),
        ("database", database),
        ("tests", tests),
        ("infra", infra),
        ("serverless", serverless),
        ("ci", ci),
        ("monitoring", monitoring),
        ("ai_rag", ai_rag),
        ("image", image),
        ("crypto", crypto),
        ("security", security),
    ):
        if enabled:
            layers.append(name)

    return {
        "layers": layers,
        "top_dirs": [{"name": name, "count": count} for name, count in top_dirs.most_common(10)],
        "backend": backend,
        "frontend": frontend,
        "auth": auth,
        "database": database,
        "tests": tests,
        "infra": infra,
        "serverless": serverless,
        "ci": ci,
        "monitoring": monitoring,
        "ai_rag": ai_rag,
        "image": image,
        "crypto": crypto,
        "security": security,
        "entrypoints": entrypoints[:8],
        "config_files": config_files[:12],
        "key_files": key_files[:12],
    }


def summarize_architecture(profile: Dict[str, Any], *, lang: str = "es") -> str:
    es = (lang or "es").lower().startswith("es")
    layers = ", ".join(profile.get("layers") or []) or "-"
    top_dirs = ", ".join(
        f"{row.get('name')} ({row.get('count')})"
        for row in (profile.get("top_dirs") or [])[:6]
        if isinstance(row, dict)
    ) or "-"
    entrypoints = ", ".join(profile.get("entrypoints") or []) or "-"
    config_files = ", ".join(profile.get("config_files") or []) or "-"

    if es:
        return "\n".join(
            [
                f"Capas detectadas: {layers}",
                f"Directorios principales: {top_dirs}",
                f"Entrypoints probables: {entrypoints}",
                f"Configs/infra: {config_files}",
            ]
        )
    return "\n".join(
        [
            f"Detected layers: {layers}",
            f"Top directories: {top_dirs}",
            f"Likely entrypoints: {entrypoints}",
            f"Config/infra files: {config_files}",
        ]
    )


def build_project_improvement_ideas(
    manifest: Dict[str, Any],
    *,
    lang: str = "es",
    limit: int = 8,
) -> List[Dict[str, Any]]:
    es = (lang or "es").lower().startswith("es")
    profile = manifest.get("architecture") if isinstance(manifest.get("architecture"), dict) else build_architecture_profile(manifest)
    file_tree = [str(path).lower() for path in (manifest.get("file_tree") or []) if isinstance(path, str)]
    config_files = {str(path).lower() for path in (manifest.get("config_files") or []) if isinstance(path, str)}
    readme_summary = str(manifest.get("readme_summary") or "").strip()
    ideas: List[Dict[str, Any]] = []

    def add(
        idea_id: str,
        priority: str,
        title_es: str,
        title_en: str,
        detail_es: str,
        detail_en: str,
        evidence: Optional[List[str]] = None,
    ) -> None:
        ideas.append(
            {
                "id": idea_id,
                "priority": priority,
                "title": title_es if es else title_en,
                "detail": detail_es if es else detail_en,
                "evidence": list(evidence or []),
            }
        )

    if not profile.get("tests"):
        add(
            "tests",
            "high",
            "Agregar pruebas automáticas",
            "Add automated tests",
            "El proyecto no muestra carpeta `tests/` ni archivos `test_*/spec.*`. Agrega al menos smoke tests de rutas críticas.",
            "The project does not show a `tests/` folder or `test_*/spec.*` files. Add at least smoke tests for critical flows.",
            ["tests missing in manifest"],
        )
    if not profile.get("ci"):
        add(
            "ci",
            "high",
            "Agregar CI reproducible",
            "Add reproducible CI",
            "No se detectó `.github/workflows` ni otro pipeline CI. Agrega validación automática de lint/tests/startup.",
            "No `.github/workflows` or other CI pipeline was detected. Add automated lint/test/startup validation.",
            [".github/workflows missing"],
        )
    if not readme_summary:
        add(
            "readme",
            "medium",
            "Documentar arranque y arquitectura",
            "Document startup and architecture",
            "No se detectó un README útil. Agrega instalación, variables de entorno, comandos y mapa del sistema.",
            "No useful README was detected. Add install steps, environment variables, commands, and a system map.",
            ["README summary missing"],
        )
    if ".env.example" not in config_files and "docker-compose.yml" not in config_files and "docker-compose.yaml" not in config_files:
        add(
            "env-contract",
            "medium",
            "Definir contrato de entorno",
            "Define environment contract",
            "No se detectó `.env.example` ni compose. Publica un archivo ejemplo con variables mínimas y defaults seguros.",
            "No `.env.example` or compose file was detected. Publish an example env file with minimum variables and safe defaults.",
            [".env.example missing"],
        )
    if profile.get("backend") and not profile.get("security"):
        add(
            "security",
            "medium",
            "Endurecer seguridad del backend",
            "Harden backend security",
            "Hay backend pero no se detectan señales claras de auth/seguridad. Revisa auth, scopes, rate limits y validación de entrada.",
            "There is a backend but no clear auth/security signals were detected. Review auth, scopes, rate limits, and input validation.",
            ["backend without security signals"],
        )
    if profile.get("backend") and profile.get("frontend"):
        add(
            "api-contract",
            "medium",
            "Fijar contrato frontend/backend",
            "Lock frontend/backend contract",
            "Hay frontend y backend. Conviene publicar contratos API, errores esperados y compatibilidad de payloads.",
            "There is both frontend and backend. Publish API contracts, expected errors, and payload compatibility.",
            ["frontend + backend detected"],
        )
    if profile.get("ai_rag") and not profile.get("monitoring"):
        add(
            "observability",
            "medium",
            "Agregar observabilidad operativa",
            "Add operational observability",
            "Se detecta stack RAG/LLM pero no señales de monitoreo. Agrega métricas, salud y alertas por degradación.",
            "A RAG/LLM stack is detected but no monitoring signals. Add metrics, health, and degradation alerts.",
            ["ai_rag without monitoring"],
        )
    if profile.get("backend") and not profile.get("infra"):
        add(
            "dev-runtime",
            "low",
            "Empaquetar runtime de desarrollo",
            "Package the development runtime",
            "No se detecta Docker/infra básica. Agrega un runner reproducible para acelerar onboarding y pruebas.",
            "No Docker/basic infra was detected. Add a reproducible runner to speed up onboarding and testing.",
            ["infra files missing"],
        )
    if not ideas:
        add(
            "baseline",
            "low",
            "Base técnica saludable",
            "Healthy technical baseline",
            "La estructura detectada ya cubre pruebas, CI, documentación e infraestructura básica. Revisa deuda puntual por módulo.",
            "The detected structure already covers tests, CI, documentation, and basic infrastructure. Review module-level debt next.",
            ["tests/ci/readme/infra detected"],
        )
    return ideas[: max(1, limit)]


def _python_module_for_rel_path(rel_path: str) -> str:
    rel = str(rel_path or "").replace("\\", "/").strip("/")
    if not rel.endswith(".py"):
        return ""
    parts = list(Path(rel).with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _python_package_parts_for_rel_path(rel_path: str) -> List[str]:
    module = _python_module_for_rel_path(rel_path)
    if not module:
        return []
    parts = module.split(".")
    path_parts = list(Path(str(rel_path or "")).parts)
    if path_parts and path_parts[-1] == "__init__.py":
        return parts
    return parts[:-1]


def _build_relation_indexes(
    root: Path,
    manifest: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    files: List[Tuple[Path, str]] = []
    rel_set: set[str] = set()
    python_modules: Dict[str, str] = {}

    for path, rel in _iter_manifest_code_files(root, manifest):
        rel_norm = str(rel or "").replace("\\", "/").strip("/")
        if not rel_norm:
            continue
        files.append((path, rel_norm))
        rel_set.add(rel_norm)
        module = _python_module_for_rel_path(rel_norm)
        if module and module not in python_modules:
            python_modules[module] = rel_norm

    return {
        "files": files,
        "rel_set": rel_set,
        "python_modules": python_modules,
    }


def _parse_imported_names(raw: str) -> List[str]:
    text = str(raw or "").split("#", 1)[0].replace("(", " ").replace(")", " ")
    names: List[str] = []
    for part in text.split(","):
        clean = part.strip()
        if not clean or clean == "*":
            continue
        names.append(clean.split(" as ", 1)[0].strip())
    return [name for name in names if name]


def _imported_names_from_specifier(specifier: str) -> List[str]:
    text = str(specifier or "").strip()
    if "::" not in text:
        return []
    return _parse_imported_names(text.split("::", 1)[1])


def _resolve_python_from_module(current_rel: str, raw_module: str) -> str:
    token = str(raw_module or "").strip()
    if not token:
        return ""
    if not token.startswith("."):
        return token
    dots = len(token) - len(token.lstrip("."))
    remainder = token[dots:].strip(".")
    base_parts = _python_package_parts_for_rel_path(current_rel)
    climb = max(0, dots - 1)
    if climb:
        base_parts = base_parts[: max(0, len(base_parts) - climb)]
    extra_parts = [part for part in remainder.split(".") if part]
    return ".".join(base_parts + extra_parts)


def _resolve_js_specifier(rel_path: str, specifier: str, rel_set: set[str]) -> Optional[str]:
    spec = str(specifier or "").strip()
    if not spec:
        return None
    base_candidates: List[str] = []
    if spec.startswith("."):
        base_dir = PurePosixPath(rel_path).parent
        base_candidates.append((base_dir / spec).as_posix())
    elif "/" in spec and not spec.startswith("@"):
        base_candidates.append(PurePosixPath(spec).as_posix())
    else:
        return None

    suffixes = ("", ".js", ".jsx", ".ts", ".tsx", "/index.js", "/index.jsx", "/index.ts", "/index.tsx")
    for base in base_candidates:
        normalized = re.sub(r"/{2,}", "/", os.path.normpath(PurePosixPath(base).as_posix()).replace("\\", "/"))
        while normalized.startswith("./"):
            normalized = normalized[2:]
        for suffix in suffixes:
            candidate = re.sub(r"/{2,}", "/", os.path.normpath((normalized + suffix).replace("\\", "/")).replace("\\", "/")).lstrip("/")
            if candidate in rel_set:
                return candidate
    return None


def scan_file_imports(
    path: Path,
    *,
    rel_path: Optional[str] = None,
    indexes: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    rel = str(rel_path or path.name).replace("\\", "/")
    ext = path.suffix.lower()
    if ext not in {".py", ".js", ".jsx", ".ts", ".tsx"}:
        return []
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return []
    if not text.strip():
        return []

    rel_set = set((indexes or {}).get("rel_set") or set())
    python_modules = dict((indexes or {}).get("python_modules") or {})
    rows: List[Dict[str, Any]] = []

    if ext == ".py":
        for match in PY_IMPORT_PATTERN.finditer(text):
            modules = [part.strip().split(" as ", 1)[0].strip() for part in match.group(1).split(",")]
            for module in modules:
                if not module:
                    continue
                target = python_modules.get(module)
                rows.append({"path": rel, "specifier": module, "target": target, "language": "python", "kind": "import"})
        for match in PY_FROM_IMPORT_PATTERN.finditer(text):
            base_module = _resolve_python_from_module(rel, match.group(1))
            imported_names = _parse_imported_names(match.group(2))
            targets: set[str] = set()
            if base_module and base_module in python_modules:
                targets.add(python_modules[base_module])
            for name in imported_names:
                candidate = f"{base_module}.{name}" if base_module else name
                target = python_modules.get(candidate)
                if target:
                    targets.add(target)
            if not targets:
                rows.append(
                    {
                        "path": rel,
                        "specifier": f"{match.group(1)}::{match.group(2).strip()}",
                        "target": None,
                        "language": "python",
                        "kind": "from-import",
                    }
                )
            else:
                for target in sorted(targets):
                    rows.append(
                        {
                            "path": rel,
                            "specifier": f"{match.group(1)}::{match.group(2).strip()}",
                            "target": target,
                            "language": "python",
                            "kind": "from-import",
                        }
                    )
        return rows

    for pattern in JS_IMPORT_PATTERNS:
        for match in pattern.finditer(text):
            spec = str(match.group(1) or "").strip()
            target = _resolve_js_specifier(rel, spec, rel_set)
            rows.append({"path": rel, "specifier": spec, "target": target, "language": language_for_path(path), "kind": "import"})
    return rows


def scan_file_identifiers(path: Path) -> Counter[str]:
    if path.suffix.lower() not in CODE_EXTS:
        return Counter()
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return Counter()
    if not text.strip():
        return Counter()
    return Counter(IDENTIFIER_PATTERN.findall(text))


def scan_python_call_counts(path: Path) -> Counter[str]:
    if path.suffix.lower() != ".py":
        return Counter()
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return Counter()
    if not text.strip():
        return Counter()
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return Counter()
    counts: Counter[str] = Counter()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name):
            counts[str(func.id)] += 1
        elif isinstance(func, ast.Attribute) and isinstance(func.attr, str):
            counts[str(func.attr)] += 1
    return counts


def scan_file_env_vars(path: Path) -> Counter[str]:
    ext = path.suffix.lower()
    if ext not in CODE_EXTS:
        return Counter()
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return Counter()
    if not text.strip():
        return Counter()
    counts: Counter[str] = Counter()
    patterns = PY_ENV_PATTERNS if ext in {".py", ".sh"} else JS_ENV_PATTERNS if ext in {".js", ".jsx", ".ts", ".tsx"} else ()
    for pattern in patterns:
        for match in pattern.finditer(text):
            env_name = str(match.group(1) or "").strip()
            if env_name:
                counts[env_name] += 1
    return counts


def _extract_route_methods(raw: str) -> List[str]:
    text = str(raw or "").strip()
    if not text:
        return []
    methods: List[str] = []
    for chunk in re.split(r"[^A-Za-z]+", text):
        token = chunk.strip().upper()
        if not token:
            continue
        if token in {"GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD", "ALL", "WEBSOCKET"}:
            methods.append(token)
    deduped: List[str] = []
    for method in methods:
        if method not in deduped:
            deduped.append(method)
    return deduped


def _join_route_path(prefix: str, route_path: str) -> str:
    prefix_clean = str(prefix or "").strip()
    route_clean = str(route_path or "").strip()
    if not prefix_clean:
        return route_clean or "/"
    if not route_clean:
        return prefix_clean if prefix_clean.startswith("/") else f"/{prefix_clean}"
    left = prefix_clean.rstrip("/")
    right = route_clean if route_clean.startswith("/") else f"/{route_clean}"
    joined = f"{left}{right}" if left else right
    return joined or "/"


def scan_file_routes(path: Path, *, rel_path: Optional[str] = None) -> List[Dict[str, Any]]:
    ext = path.suffix.lower()
    if ext not in {".py", ".js", ".jsx", ".ts", ".tsx"}:
        return []
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return []
    if not text.strip():
        return []

    rel = rel_path or path.name
    language = language_for_path(path)
    rows: List[Dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()

    if ext == ".py":
        lines = text.splitlines()
        idx = 0
        while idx < len(lines):
            stripped = lines[idx].lstrip()
            if not stripped.startswith("@"):
                idx += 1
                continue
            buffer = [lines[idx]]
            depth = lines[idx].count("(") - lines[idx].count(")")
            idx += 1
            while idx < len(lines) and depth > 0:
                buffer.append(lines[idx])
                depth += lines[idx].count("(") - lines[idx].count(")")
                idx += 1
            decorator_text = "\n".join(buffer)
            match = PY_ROUTE_DECORATOR_PATTERN.search(decorator_text)
            if not match:
                continue
            route_match = ROUTE_STRING_PATTERN.search(decorator_text)
            if not route_match:
                continue
            handler_name = ""
            look_ahead = idx
            while look_ahead < len(lines):
                candidate = lines[look_ahead].strip()
                if not candidate or candidate.startswith("@"):
                    look_ahead += 1
                    continue
                handler_match = re.match(r"^(?:async\s+)?def\s+([A-Za-z_]\w*)\s*\(", candidate)
                if handler_match:
                    handler_name = str(handler_match.group(1) or "").strip()
                break
            method_name = str(match.group(2) or "").strip().lower()
            router_ref = str(match.group(1) or "").strip()
            route_path = str(route_match.group(1) or "").strip()
            methods: List[str]
            if method_name in ROUTE_METHODS:
                methods = [method_name.upper()]
            else:
                methods_match = ROUTE_METHODS_PATTERN.search(decorator_text)
                methods = _extract_route_methods((methods_match.group(1) or methods_match.group(2) or "") if methods_match else "")
                if not methods:
                    methods = ["ANY"]
            for method in methods:
                key = (rel, method, route_path)
                if key in seen:
                    continue
                seen.add(key)
                rows.append(
                    {
                        "path": rel,
                        "method": method,
                        "route": route_path,
                        "resolved_route": route_path,
                        "router_ref": router_ref,
                        "handler": handler_name,
                        "language": language,
                    }
                )
        return rows

    for match in JS_ROUTE_PATTERN.finditer(text):
        method = str(match.group(1) or "").strip().upper()
        route_path = str(match.group(3) or "").strip()
        key = (rel, method, route_path)
        if key in seen:
            continue
        seen.add(key)
        rows.append(
            {
                "path": rel,
                "method": method,
                "route": route_path,
                "resolved_route": route_path,
                "router_ref": "",
                "handler": "",
                "language": language,
            }
        )
    return rows


def scan_python_router_mounts(
    path: Path,
    *,
    rel_path: Optional[str] = None,
    indexes: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    rel = str(rel_path or path.name).replace("\\", "/")
    if path.suffix.lower() != ".py":
        return []
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return []
    if not text.strip():
        return []
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []

    python_modules = dict((indexes or {}).get("python_modules") or {})
    alias_map: Dict[str, Dict[str, str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module_token = "." * int(getattr(node, "level", 0)) + str(node.module or "")
            resolved_module = _resolve_python_from_module(rel, module_token)
            for alias in node.names:
                imported_name = str(alias.name or "").strip()
                if not imported_name or imported_name == "*":
                    continue
                alias_name = str(alias.asname or imported_name).strip()
                target = ""
                candidate_module = f"{resolved_module}.{imported_name}" if resolved_module else imported_name
                if candidate_module in python_modules:
                    target = python_modules[candidate_module]
                elif resolved_module in python_modules:
                    target = python_modules[resolved_module]
                if target:
                    alias_map[alias_name] = {"target": target, "imported": imported_name}
        elif isinstance(node, ast.Import):
            for alias in node.names:
                module_name = str(alias.name or "").strip()
                alias_name = str(alias.asname or module_name.split(".")[-1]).strip()
                target = python_modules.get(module_name, "")
                if target:
                    alias_map[alias_name] = {"target": target, "imported": module_name.split(".")[-1]}

    rows: List[Dict[str, Any]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Attribute) or str(node.func.attr or "") != "include_router":
            continue
        if not node.args:
            continue
        arg = node.args[0]
        target = ""
        router_name = ""
        if isinstance(arg, ast.Name):
            info = alias_map.get(str(arg.id or ""))
            if info:
                target = str(info.get("target") or "")
                router_name = str(info.get("imported") or "")
        elif isinstance(arg, ast.Attribute) and isinstance(arg.value, ast.Name):
            info = alias_map.get(str(arg.value.id or ""))
            if info:
                target = str(info.get("target") or "")
                router_name = str(arg.attr or "")
        if not target:
            continue
        prefix = ""
        for keyword in node.keywords or []:
            if str(keyword.arg or "") != "prefix":
                continue
            if isinstance(keyword.value, ast.Constant) and isinstance(keyword.value.value, str):
                prefix = str(keyword.value.value)
            break
        rows.append(
            {
                "path": rel,
                "target": target,
                "router_name": router_name or "router",
                "prefix": prefix,
            }
        )
    return rows


def scan_python_runtime_apps(path: Path, *, rel_path: Optional[str] = None) -> List[Dict[str, Any]]:
    rel = str(rel_path or path.name).replace("\\", "/")
    if path.suffix.lower() != ".py":
        return []
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return []
    if not text.strip():
        return []
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []

    rows: List[Dict[str, Any]] = []
    seen_names: set[str] = set()
    uvicorn_targets: Dict[str, str] = {}

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
            if str(func.value.id or "") == "uvicorn" and str(func.attr or "") == "run":
                target_literal = ""
                if node.args:
                    arg = node.args[0]
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        target_literal = str(arg.value)
                    elif isinstance(arg, ast.Name):
                        uvicorn_targets[str(arg.id or "")] = ""
                for keyword in node.keywords or []:
                    if str(keyword.arg or "") == "app":
                        value = keyword.value
                        if isinstance(value, ast.Constant) and isinstance(value.value, str):
                            target_literal = str(value.value)
                        elif isinstance(value, ast.Name):
                            uvicorn_targets[str(value.id or "")] = ""
                if target_literal and ":" in target_literal:
                    target_name = target_literal.split(":", 1)[1].strip()
                    if target_name:
                        uvicorn_targets[target_name] = target_literal

    for node in ast.walk(tree):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets: List[ast.expr] = []
        value: Optional[ast.expr] = None
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
            value = node.value
        else:
            if node.target is not None:
                targets = [node.target]
            value = node.value
        if not value or not isinstance(value, ast.Call):
            continue
        func = value.func
        func_name = ""
        if isinstance(func, ast.Name):
            func_name = str(func.id or "")
        elif isinstance(func, ast.Attribute):
            func_name = str(func.attr or "")
        if func_name != "FastAPI":
            continue
        for target in targets:
            if not isinstance(target, ast.Name):
                continue
            app_name = str(target.id or "").strip()
            if not app_name or app_name in seen_names:
                continue
            seen_names.add(app_name)
            rows.append(
                {
                    "path": rel,
                    "framework": "fastapi",
                    "app_name": app_name,
                    "uvicorn_target": uvicorn_targets.get(app_name, ""),
                }
            )
    return rows


def _normalize_symbol_body(body: str, symbol: str) -> str:
    text = str(body or "")
    if not text.strip():
        return ""
    text = re.sub(r'"""[\s\S]*?"""', " DOC ", text)
    text = re.sub(r"'''[\s\S]*?'''", " DOC ", text)
    text = re.sub(r"/\*[\s\S]*?\*/", " DOC ", text)
    text = re.sub(r"#.*", "", text)
    text = re.sub(r"//.*", "", text)
    text = re.sub(r'"(?:\\.|[^"\\])*"', " STR ", text)
    text = re.sub(r"'(?:\\.|[^'\\])*'", " STR ", text)
    if symbol:
        text = re.sub(rf"\b{re.escape(symbol)}\b", " SYM ", text)
    text = re.sub(r"\b\d+(?:\.\d+)?\b", " NUM ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def scan_file_symbol_bodies(path: Path, *, rel_path: Optional[str] = None) -> List[Dict[str, Any]]:
    if path.suffix.lower() not in CODE_EXTS:
        return []
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return []
    if not text.strip():
        return []

    boundaries = collect_symbol_boundaries(text)
    if not boundaries:
        return []

    lines = text.splitlines()
    total_lines = len(lines)
    rel = rel_path or path.name
    language = language_for_path(path)
    rows: List[Dict[str, Any]] = []
    for idx, (symbol, line_start, _offset) in enumerate(boundaries):
        if not symbol:
            continue
        next_line = boundaries[idx + 1][1] - 1 if idx + 1 < len(boundaries) else total_lines
        line_end = min(total_lines, max(line_start, next_line))
        body_lines = lines[max(0, line_start - 1):max(0, line_end)]
        body = "\n".join(body_lines).strip()
        normalized = _normalize_symbol_body(body, symbol)
        if len(normalized) < 24:
            continue
        rows.append(
            {
                "symbol": symbol,
                "path": rel,
                "language": language,
                "line_start": int(line_start),
                "line_end": int(line_end),
                "line_count": max(0, line_end - line_start + 1),
                "body_hash": hashlib.sha1(normalized.encode("utf-8")).hexdigest(),
            }
        )
    return rows


def _iter_symbol_rows(root: Path, manifest: Optional[Dict[str, Any]] = None) -> Iterable[Dict[str, Any]]:
    for path, rel in _iter_manifest_code_files(root, manifest):
        for row in scan_file_symbols(path, rel_path=rel):
            yield row


def _build_relation_state(root: Path, manifest: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    indexes = _build_relation_indexes(root, manifest)
    adjacency: Dict[str, set[str]] = defaultdict(set)
    reverse: Dict[str, set[str]] = defaultdict(set)
    edge_rows: List[Dict[str, Any]] = []
    seen_edges: set[tuple[str, str, str]] = set()
    unresolved: Counter[str] = Counter()
    identifier_counts_by_file: Dict[str, Counter[str]] = {}
    call_counts_by_file: Dict[str, Counter[str]] = {}
    env_vars_by_file: Dict[str, Counter[str]] = {}
    symbol_bodies: List[Dict[str, Any]] = []
    routes_by_file: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    route_mounts: List[Dict[str, Any]] = []
    runtime_apps_by_file: Dict[str, List[Dict[str, Any]]] = defaultdict(list)

    for path, rel in indexes["files"]:
        identifier_counts_by_file[rel] = scan_file_identifiers(path)
        call_counts_by_file[rel] = scan_python_call_counts(path)
        env_vars_by_file[rel] = scan_file_env_vars(path)
        symbol_bodies.extend(scan_file_symbol_bodies(path, rel_path=rel))
        routes_by_file[rel].extend(scan_file_routes(path, rel_path=rel))
        route_mounts.extend(scan_python_router_mounts(path, rel_path=rel, indexes=indexes))
        runtime_apps_by_file[rel].extend(scan_python_runtime_apps(path, rel_path=rel))
        imports = scan_file_imports(path, rel_path=rel, indexes=indexes)
        for item in imports:
            target = str(item.get("target") or "").strip()
            if not target:
                unresolved[rel] += 1
                continue
            if target == rel:
                continue
            adjacency[rel].add(target)
            reverse[target].add(rel)
            edge_key = (rel, target, str(item.get("kind") or "import"))
            if edge_key in seen_edges:
                continue
            seen_edges.add(edge_key)
            edge_rows.append(
                {
                    "from": rel,
                    "to": target,
                    "kind": str(item.get("kind") or "import"),
                    "language": str(item.get("language") or ""),
                    "specifier": str(item.get("specifier") or ""),
                }
            )

    symbol_groups: Dict[str, set[str]] = defaultdict(set)
    symbol_definitions: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in _iter_symbol_rows(root, manifest):
        symbol = str(row.get("symbol") or "").strip()
        rel = str(row.get("path") or "").strip()
        if symbol and rel:
            symbol_groups[symbol].add(rel)
            symbol_definitions[symbol].append(
                {
                    "path": rel,
                    "line_start": int(row.get("line_start") or 0),
                    "line_end": int(row.get("line_end") or 0),
                    "language": str(row.get("language") or ""),
                }
            )

    shared_symbol_clusters = [
        {"symbol": symbol, "count": len(paths), "paths": sorted(paths)[:8]}
        for symbol, paths in symbol_groups.items()
        if len(paths) > 1
    ]
    shared_symbol_clusters.sort(key=lambda item: (-int(item["count"]), str(item["symbol"])))

    mutual_edges: List[Dict[str, Any]] = []
    seen_pairs: set[tuple[str, str]] = set()
    for src, targets in adjacency.items():
        for dst in targets:
            pair = tuple(sorted((src, dst)))
            if src in adjacency.get(dst, set()) and pair not in seen_pairs:
                seen_pairs.add(pair)
                mutual_edges.append({"a": pair[0], "b": pair[1]})
    mutual_edges.sort(key=lambda item: (item["a"], item["b"]))

    inbound: Counter[str] = Counter()
    outbound: Counter[str] = Counter()
    for _path, rel in indexes["files"]:
        inbound[rel] = len(reverse.get(rel, set()))
        outbound[rel] = len(adjacency.get(rel, set()))

    symbol_reference_files: Dict[str, List[Dict[str, Any]]] = {}
    symbol_hotspots: List[Dict[str, Any]] = []
    refactor_candidates: List[Dict[str, Any]] = []
    definitions_by_path: Dict[str, set[str]] = defaultdict(set)
    for symbol, definitions in symbol_definitions.items():
        for item in definitions:
            rel = str(item.get("path") or "").strip()
            if rel:
                definitions_by_path[rel].add(symbol)
    for symbol, definitions in symbol_definitions.items():
        defining_paths = {str(item.get("path") or "") for item in definitions}
        references: List[Dict[str, Any]] = []
        total_refs = 0
        for rel, counts in identifier_counts_by_file.items():
            count = int(counts.get(symbol, 0))
            if count <= 0:
                continue
            if rel in defining_paths:
                count = max(0, count - 1)
            if count <= 0:
                continue
            references.append({"path": rel, "count": count})
            total_refs += count
        references.sort(key=lambda item: (-int(item["count"]), str(item["path"])))
        symbol_reference_files[symbol] = references
        if total_refs > 0 or len(defining_paths) > 1:
            symbol_hotspots.append(
                {
                    "symbol": symbol,
                    "definition_count": len(definitions),
                    "reference_count": total_refs,
                    "defined_in": sorted(defining_paths)[:8],
                    "referenced_by": references[:8],
                }
            )
        if len(defining_paths) > 1:
            refactor_candidates.append(
                {
                    "symbol": symbol,
                    "definition_count": len(definitions),
                    "reference_count": total_refs,
                    "paths": sorted(defining_paths)[:8],
                    "referenced_by_files": [item["path"] for item in references[:8]],
                    "reason": "duplicate-symbol-with-external-usage" if total_refs > 0 else "duplicate-symbol",
                }
            )

    symbol_hotspots.sort(key=lambda item: (-int(item["reference_count"]), -int(item["definition_count"]), str(item["symbol"])))
    refactor_candidates.sort(key=lambda item: (-int(item["reference_count"]), -int(item["definition_count"]), str(item["symbol"])))

    env_var_files: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    env_var_hotspots: List[Dict[str, Any]] = []
    for rel, counts in env_vars_by_file.items():
        for env_name, count in counts.items():
            env_var_files[env_name].append({"path": rel, "count": int(count)})
    for env_name, rows in env_var_files.items():
        rows.sort(key=lambda item: (-int(item["count"]), str(item["path"])))
        env_var_hotspots.append(
            {
                "env": env_name,
                "file_count": len(rows),
                "usage_count": sum(int(item["count"]) for item in rows),
                "files": rows[:8],
            }
        )
    env_var_hotspots.sort(key=lambda item: (-int(item["file_count"]), -int(item["usage_count"]), str(item["env"])))

    duplicate_logic_clusters: List[Dict[str, Any]] = []
    clusters_by_hash: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in symbol_bodies:
        clusters_by_hash[str(row.get("body_hash") or "")].append(row)
    for body_hash, rows in clusters_by_hash.items():
        if len(rows) < 2:
            continue
        unique_paths = {str(item.get("path") or "") for item in rows}
        if len(unique_paths) < 2:
            continue
        unique_symbols = sorted({str(item.get("symbol") or "") for item in rows if str(item.get("symbol") or "")})
        duplicate_logic_clusters.append(
            {
                "fingerprint": body_hash[:12],
                "count": len(rows),
                "path_count": len(unique_paths),
                "symbols": unique_symbols[:8],
                "paths": sorted(unique_paths)[:8],
            }
        )
    duplicate_logic_clusters.sort(key=lambda item: (-int(item["path_count"]), -int(item["count"]), str(item["fingerprint"])))

    symbol_call_edges: List[Dict[str, Any]] = []
    seen_symbol_edges: set[tuple[str, str, str]] = set()
    for item in edge_rows:
        if str(item.get("kind") or "") != "from-import":
            continue
        src = str(item.get("from") or "").strip()
        dst = str(item.get("to") or "").strip()
        if not src or not dst:
            continue
        imported_names = _imported_names_from_specifier(str(item.get("specifier") or ""))
        if not imported_names:
            continue
        counts = call_counts_by_file.get(src) or identifier_counts_by_file.get(src, Counter())
        target_defs = definitions_by_path.get(dst, set())
        for name in imported_names:
            if name not in target_defs:
                continue
            edge_key = (src, dst, name)
            if edge_key in seen_symbol_edges:
                continue
            seen_symbol_edges.add(edge_key)
            symbol_call_edges.append(
                {
                    "from_path": src,
                    "to_path": dst,
                    "symbol": name,
                    "count": int(counts.get(name, 0)),
                }
            )
    symbol_call_edges.sort(key=lambda item: (-int(item["count"]), str(item["symbol"]), str(item["from_path"]), str(item["to_path"])))

    symbol_call_hotspots: List[Dict[str, Any]] = []
    for symbol in sorted({str(item.get("symbol") or "") for item in symbol_call_edges if str(item.get("symbol") or "")}):
        edges = [item for item in symbol_call_edges if str(item.get("symbol") or "") == symbol]
        symbol_call_hotspots.append(
            {
                "symbol": symbol,
                "call_edge_count": len(edges),
                "total_mentions": sum(int(item.get("count") or 0) for item in edges),
                "from_paths": sorted({str(item.get("from_path") or "") for item in edges})[:8],
                "to_paths": sorted({str(item.get("to_path") or "") for item in edges})[:8],
            }
        )
    symbol_call_hotspots.sort(key=lambda item: (-int(item["total_mentions"]), -int(item["call_edge_count"]), str(item["symbol"])))

    route_rows: List[Dict[str, Any]] = []
    route_hotspots: List[Dict[str, Any]] = []
    for rel, rows in routes_by_file.items():
        mounts = [item for item in route_mounts if str(item.get("target") or "") == rel]
        normalized_rows = [
            {
                "path": rel,
                "method": str(item.get("method") or "").strip(),
                "route": str(item.get("route") or "").strip(),
                "resolved_route": str(item.get("resolved_route") or item.get("route") or "").strip(),
                "router_ref": str(item.get("router_ref") or "").strip(),
                "handler": str(item.get("handler") or "").strip(),
                "language": str(item.get("language") or "").strip(),
            }
            for item in rows
            if str(item.get("route") or "").strip()
        ]
        if mounts:
            mounted_rows: List[Dict[str, Any]] = []
            for item in normalized_rows:
                router_ref = str(item.get("router_ref") or "").strip().split(".")[-1]
                matched_mounts = [
                    mount
                    for mount in mounts
                    if not str(mount.get("router_name") or "").strip()
                    or str(mount.get("router_name") or "").strip() == router_ref
                ]
                if not matched_mounts:
                    mounted_rows.append(item)
                    continue
                for mount in matched_mounts:
                    mounted_row = dict(item)
                    mounted_row["resolved_route"] = _join_route_path(str(mount.get("prefix") or ""), str(item.get("route") or ""))
                    mounted_row["mounted_by"] = str(mount.get("path") or "").strip()
                    mounted_rows.append(mounted_row)
            normalized_rows = mounted_rows
        normalized_rows.sort(key=lambda item: (str(item["method"]), str(item["route"])))
        route_rows.extend(normalized_rows)
        if not normalized_rows:
            continue
        route_hotspots.append(
            {
                "path": rel,
                "route_count": len(normalized_rows),
                "methods": sorted({str(item.get("method") or "") for item in normalized_rows if str(item.get("method") or "")})[:8],
                "routes": normalized_rows[:8],
            }
        )
    route_rows.sort(key=lambda item: (str(item["path"]), str(item.get("resolved_route") or item["route"]), str(item["method"])))
    route_hotspots.sort(key=lambda item: (-int(item["route_count"]), str(item["path"])))

    runtime_surfaces: List[Dict[str, Any]] = []
    runtime_surface_hotspots: List[Dict[str, Any]] = []
    for rel, app_rows in runtime_apps_by_file.items():
        if not app_rows:
            continue
        direct_routes = [item for item in route_rows if str(item.get("path") or "") == rel]
        mounted_routes = [item for item in route_rows if str(item.get("mounted_by") or "") == rel]
        served_routes: List[Dict[str, Any]] = []
        for item in direct_routes + mounted_routes:
            if item not in served_routes:
                served_routes.append(item)
        for app_row in app_rows:
            runtime_surfaces.append(
                {
                    "path": rel,
                    "framework": str(app_row.get("framework") or ""),
                    "app_name": str(app_row.get("app_name") or ""),
                    "uvicorn_target": str(app_row.get("uvicorn_target") or ""),
                    "served_route_count": len(served_routes),
                    "routes": served_routes[:8],
                }
            )
        runtime_surface_hotspots.append(
            {
                "path": rel,
                "app_count": len(app_rows),
                "served_route_count": len(served_routes),
                "apps": [
                    {
                        "app_name": str(item.get("app_name") or ""),
                        "uvicorn_target": str(item.get("uvicorn_target") or ""),
                    }
                    for item in app_rows[:8]
                ],
                "routes": served_routes[:8],
            }
        )
    runtime_surfaces.sort(key=lambda item: (-int(item["served_route_count"]), str(item["path"]), str(item["app_name"])))
    runtime_surface_hotspots.sort(key=lambda item: (-int(item["served_route_count"]), -int(item["app_count"]), str(item["path"])))

    route_handlers_by_path: Dict[str, set[str]] = defaultdict(set)
    for route in route_rows:
        handler_name = str(route.get("handler") or "").strip()
        route_path = str(route.get("path") or "").strip()
        if handler_name and route_path:
            route_handlers_by_path[route_path].add(handler_name)

    runtime_apps_by_name: Dict[str, set[str]] = defaultdict(set)
    for rel, app_rows in runtime_apps_by_file.items():
        for item in app_rows:
            app_name = str(item.get("app_name") or "").strip()
            if app_name:
                runtime_apps_by_name[rel].add(app_name)

    public_api_symbols: List[Dict[str, Any]] = []
    isolated_symbol_candidates: List[Dict[str, Any]] = []
    for symbol, definitions in symbol_definitions.items():
        references = symbol_reference_files.get(symbol, [])
        external_ref_count = sum(int(item.get("count") or 0) for item in references)
        for definition in definitions:
            rel = str(definition.get("path") or "").strip()
            if not rel:
                continue
            local_ref_count = max(0, int(identifier_counts_by_file.get(rel, Counter()).get(symbol, 0)) - 1)
            exposure_reasons: List[str] = []
            if external_ref_count > 0:
                exposure_reasons.append("imported")
            if symbol in route_handlers_by_path.get(rel, set()):
                exposure_reasons.append("route-handler")
            if symbol in runtime_apps_by_name.get(rel, set()):
                exposure_reasons.append("runtime-app")
            if exposure_reasons:
                public_api_symbols.append(
                    {
                        "symbol": symbol,
                        "path": rel,
                        "line_start": int(definition.get("line_start") or 0),
                        "line_end": int(definition.get("line_end") or 0),
                        "reasons": exposure_reasons,
                        "external_reference_count": external_ref_count,
                        "local_reference_count": local_ref_count,
                    }
                )
            if (
                len(definitions) == 1
                and external_ref_count == 0
                and local_ref_count == 0
                and symbol not in route_handlers_by_path.get(rel, set())
                and symbol not in runtime_apps_by_name.get(rel, set())
                and not str(symbol).startswith("__")
            ):
                isolated_symbol_candidates.append(
                    {
                        "symbol": symbol,
                        "path": rel,
                        "line_start": int(definition.get("line_start") or 0),
                        "line_end": int(definition.get("line_end") or 0),
                        "confidence": "medium" if not str(symbol).startswith("_") else "low",
                    }
                )

    public_api_symbols.sort(
        key=lambda item: (
            -len(item.get("reasons") or []),
            -int(item.get("external_reference_count") or 0),
            str(item.get("path") or ""),
            str(item.get("symbol") or ""),
        )
    )
    isolated_symbol_candidates.sort(
        key=lambda item: (
            str(item.get("confidence") or ""),
            str(item.get("path") or ""),
            str(item.get("symbol") or ""),
        )
    )

    return {
        "files": [rel for _path, rel in indexes["files"]],
        "edges": edge_rows,
        "adjacency": adjacency,
        "reverse": reverse,
        "inbound": inbound,
        "outbound": outbound,
        "shared_symbol_clusters": shared_symbol_clusters,
        "symbol_groups": symbol_groups,
        "symbol_definitions": symbol_definitions,
        "symbol_reference_files": symbol_reference_files,
        "symbol_hotspots": symbol_hotspots,
        "refactor_candidates": refactor_candidates,
        "env_var_files": env_var_files,
        "env_var_hotspots": env_var_hotspots,
        "symbol_bodies": symbol_bodies,
        "duplicate_logic_clusters": duplicate_logic_clusters,
        "symbol_call_edges": symbol_call_edges,
        "symbol_call_hotspots": symbol_call_hotspots,
        "public_api_symbols": public_api_symbols,
        "isolated_symbol_candidates": isolated_symbol_candidates,
        "routes": route_rows,
        "route_hotspots": route_hotspots,
        "routes_by_file": routes_by_file,
        "route_mounts": route_mounts,
        "runtime_surfaces": runtime_surfaces,
        "runtime_surface_hotspots": runtime_surface_hotspots,
        "runtime_apps_by_file": runtime_apps_by_file,
        "mutual_edges": mutual_edges,
        "unresolved_imports": unresolved,
    }


def _rename_safety_summary(
    state: Dict[str, Any],
    *,
    symbol: str,
    changed_paths: List[str],
) -> Dict[str, Any]:
    definitions = list(state["symbol_definitions"].get(symbol, []))
    refs = list(state["symbol_reference_files"].get(symbol, []))
    unresolved = state["unresolved_imports"]
    ref_count = sum(int(item.get("count") or 0) for item in refs)
    score = 100
    warnings: List[str] = []
    if len(definitions) > 1:
        score -= 35
        warnings.append("multiple-definitions")
    if ref_count > 30:
        score -= 20
        warnings.append("high-reference-count")
    elif ref_count > 10:
        score -= 10
        warnings.append("moderate-reference-count")
    unresolved_hits = sum(int(unresolved.get(path, 0)) for path in changed_paths)
    if unresolved_hits > 0:
        score -= 15
        warnings.append("touched-files-have-unresolved-imports")
    if not changed_paths:
        score -= 50
        warnings.append("no-safe-text-edits-detected")

    score = max(0, min(100, score))
    if score >= 80:
        level = "high"
    elif score >= 55:
        level = "medium"
    else:
        level = "low"
    return {
        "level": level,
        "score": score,
        "warnings": warnings,
        "definition_count": len(definitions),
        "reference_count": ref_count,
        "changed_path_count": len(changed_paths),
    }


def build_project_intelligence_summary(
    root: Path,
    *,
    manifest: Optional[Dict[str, Any]] = None,
    limit: int = 8,
) -> Dict[str, Any]:
    state = _build_relation_state(root, manifest)
    files = list(state["files"])
    adjacency = state["adjacency"]
    reverse = state["reverse"]
    inbound = state["inbound"]
    outbound = state["outbound"]
    unresolved_imports = state["unresolved_imports"]
    shared_symbol_clusters = list(state["shared_symbol_clusters"])
    symbol_hotspots = list(state["symbol_hotspots"])
    refactor_candidates = list(state["refactor_candidates"])
    env_var_hotspots = list(state["env_var_hotspots"])
    duplicate_logic_clusters = list(state["duplicate_logic_clusters"])
    symbol_call_hotspots = list(state["symbol_call_hotspots"])
    public_api_symbols = list(state["public_api_symbols"])
    isolated_symbol_candidates = list(state["isolated_symbol_candidates"])
    route_rows = list(state["routes"])
    route_hotspots = list(state["route_hotspots"])
    runtime_surfaces = list(state["runtime_surfaces"])
    runtime_surface_hotspots = list(state["runtime_surface_hotspots"])
    mutual_edges = list(state["mutual_edges"])

    hotspots = [
        {
            "path": rel,
            "inbound_refs": int(inbound.get(rel, 0)),
            "outbound_refs": int(outbound.get(rel, 0)),
            "imported_by": sorted(reverse.get(rel, set()))[:6],
            "imports_to": sorted(adjacency.get(rel, set()))[:6],
        }
        for rel in files
        if inbound.get(rel, 0) > 0 or outbound.get(rel, 0) > 0
    ]
    hotspots.sort(key=lambda item: (-int(item["inbound_refs"]), -int(item["outbound_refs"]), str(item["path"])))

    outbound_hotspots = sorted(
        hotspots,
        key=lambda item: (-int(item["outbound_refs"]), -int(item["inbound_refs"]), str(item["path"])),
    )
    unresolved_rows = [
        {"path": rel, "count": int(count)}
        for rel, count in unresolved_imports.most_common(max(1, limit))
    ]

    return {
        "files_scanned": len(files),
        "internal_edge_count": len(state["edges"]),
        "files_with_links": sum(1 for rel in files if inbound.get(rel, 0) or outbound.get(rel, 0)),
        "hotspots": hotspots[: max(1, limit)],
        "outbound_hotspots": outbound_hotspots[: max(1, limit)],
        "mutual_edges": mutual_edges[: max(1, limit)],
        "shared_symbol_clusters": shared_symbol_clusters[: max(1, limit)],
        "symbol_hotspots": symbol_hotspots[: max(1, limit)],
        "symbol_call_hotspots": symbol_call_hotspots[: max(1, limit)],
        "public_api_symbols": public_api_symbols[: max(1, limit)],
        "isolated_symbol_candidates": isolated_symbol_candidates[: max(1, limit)],
        "route_count": len(route_rows),
        "routes": route_rows[: max(1, limit * 2)],
        "route_hotspots": route_hotspots[: max(1, limit)],
        "runtime_surface_count": len(runtime_surfaces),
        "runtime_surfaces": runtime_surfaces[: max(1, limit)],
        "runtime_surface_hotspots": runtime_surface_hotspots[: max(1, limit)],
        "refactor_candidates": refactor_candidates[: max(1, limit)],
        "env_var_hotspots": env_var_hotspots[: max(1, limit)],
        "duplicate_logic_clusters": duplicate_logic_clusters[: max(1, limit)],
        "unresolved_imports": unresolved_rows,
    }


def build_project_impact_report(
    root: Path,
    *,
    manifest: Optional[Dict[str, Any]] = None,
    q: str = "",
    limit: int = 8,
) -> Dict[str, Any]:
    query = str(q or "").strip()
    if not query:
        return {
            "query": "",
            "matched_files": [],
            "matched_symbols": [],
            "imported_by": [],
            "imports_to": [],
            "same_symbol_neighbors": [],
            "likely_touched_files": [],
        }

    state = _build_relation_state(root, manifest)
    file_matches = fuzzy_search_project_files(manifest, q=query, limit=max(2, limit))
    symbol_matches = scan_project_symbols(root, manifest=manifest, q=query, limit=max(4, limit * 2))

    selected_files = [str(item.get("path") or "").strip() for item in file_matches if str(item.get("path") or "").strip()]
    matched_symbols = [
        row
        for row in symbol_matches
        if str(row.get("symbol") or "").strip()
    ]

    imports_to: set[str] = set()
    imported_by: set[str] = set()
    same_symbol_neighbors: set[str] = set()
    likely_touched: List[str] = []
    defined_in: List[Dict[str, Any]] = []
    referenced_by_files: List[Dict[str, Any]] = []
    refactor_candidates: List[Dict[str, Any]] = []
    call_edges_to: List[Dict[str, Any]] = []
    call_edges_from: List[Dict[str, Any]] = []
    env_vars_in_scope: List[Dict[str, Any]] = []
    duplicate_logic_neighbors: List[Dict[str, Any]] = []
    routes_in_scope: List[Dict[str, Any]] = []
    runtime_surfaces_in_scope: List[Dict[str, Any]] = []
    public_api_symbols_in_scope: List[Dict[str, Any]] = []
    isolated_symbols_in_scope: List[Dict[str, Any]] = []

    for rel in selected_files[: max(1, limit)]:
        imports_to.update(state["adjacency"].get(rel, set()))
        imported_by.update(state["reverse"].get(rel, set()))
        likely_touched.append(rel)
        for surface in state["runtime_surfaces"]:
            surface_path = str(surface.get("path") or "").strip()
            route_paths = {str(item.get("path") or "").strip() for item in surface.get("routes") or []}
            mounted_by_paths = {str(item.get("mounted_by") or "").strip() for item in surface.get("routes") or []}
            if rel == surface_path or rel in route_paths or rel in mounted_by_paths:
                if surface not in runtime_surfaces_in_scope:
                    runtime_surfaces_in_scope.append(surface)
        for item in state["public_api_symbols"]:
            if str(item.get("path") or "").strip() == rel and item not in public_api_symbols_in_scope:
                public_api_symbols_in_scope.append(item)
        for item in state["isolated_symbol_candidates"]:
            if str(item.get("path") or "").strip() == rel and item not in isolated_symbols_in_scope:
                isolated_symbols_in_scope.append(item)
        for route in state["routes"]:
            if str(route.get("path") or "").strip() != rel:
                continue
            normalized = {
                "path": rel,
                "method": str(route.get("method") or "").strip(),
                "route": str(route.get("route") or "").strip(),
                "resolved_route": str(route.get("resolved_route") or route.get("route") or "").strip(),
                "handler": str(route.get("handler") or "").strip(),
            }
            if normalized["route"] and normalized not in routes_in_scope:
                routes_in_scope.append(normalized)
        for env_name, rows in state["env_var_files"].items():
            match = next((item for item in rows if str(item.get("path") or "") == rel), None)
            if match and not any(str(item.get("env") or "") == env_name and str(item.get("path") or "") == rel for item in env_vars_in_scope):
                env_vars_in_scope.append({"env": env_name, "path": rel, "count": int(match.get("count") or 0)})
        for symbol, definitions in state["symbol_definitions"].items():
            if any(str(item.get("path") or "") == rel for item in definitions):
                refs = state["symbol_reference_files"].get(symbol, [])
                if refs:
                    refactor_candidates.append(
                        {
                            "symbol": symbol,
                            "definition_count": len(definitions),
                            "reference_count": sum(int(item.get("count") or 0) for item in refs),
                            "paths": sorted({str(item.get("path") or "") for item in definitions})[:8],
                            "referenced_by_files": [item["path"] for item in refs[:8]],
                        }
                    )
        for cluster in state["duplicate_logic_clusters"]:
            if rel in set(cluster.get("paths") or []):
                if cluster not in duplicate_logic_neighbors:
                    duplicate_logic_neighbors.append(cluster)

    for row in matched_symbols[: max(1, limit * 2)]:
        rel = str(row.get("path") or "").strip()
        symbol = str(row.get("symbol") or "").strip()
        if rel:
            likely_touched.append(rel)
            imports_to.update(state["adjacency"].get(rel, set()))
            imported_by.update(state["reverse"].get(rel, set()))
        for neighbor in state["symbol_groups"].get(symbol, set()):
            if neighbor != rel:
                same_symbol_neighbors.add(neighbor)
        for item in state["symbol_definitions"].get(symbol, []):
            if item not in defined_in:
                defined_in.append(item)
        for item in state["symbol_reference_files"].get(symbol, []):
            if item not in referenced_by_files:
                referenced_by_files.append(item)
        for item in state["symbol_call_edges"]:
            if str(item.get("symbol") or "") != symbol:
                continue
            if item not in call_edges_to and rel and str(item.get("to_path") or "") == rel:
                call_edges_to.append(item)
            if item not in call_edges_from and rel and str(item.get("from_path") or "") == rel:
                call_edges_from.append(item)
        candidate = next((item for item in state["refactor_candidates"] if str(item.get("symbol") or "") == symbol), None)
        if candidate and candidate not in refactor_candidates:
            refactor_candidates.append(candidate)
        for item in state["public_api_symbols"]:
            if str(item.get("symbol") or "") == symbol and item not in public_api_symbols_in_scope:
                public_api_symbols_in_scope.append(item)
        for item in state["isolated_symbol_candidates"]:
            if str(item.get("symbol") or "") == symbol and item not in isolated_symbols_in_scope:
                isolated_symbols_in_scope.append(item)
        for cluster in state["duplicate_logic_clusters"]:
            if symbol in set(cluster.get("symbols") or []):
                if cluster not in duplicate_logic_neighbors:
                    duplicate_logic_neighbors.append(cluster)
        for surface in state["runtime_surfaces"]:
            route_items = surface.get("routes") or []
            if any(str(item.get("handler") or "") == symbol for item in route_items):
                if surface not in runtime_surfaces_in_scope:
                    runtime_surfaces_in_scope.append(surface)
        query_lower = query.lower()
        for route in state["routes"]:
            if str(route.get("path") or "").strip() != rel:
                continue
            normalized = {
                "path": rel,
                "method": str(route.get("method") or "").strip(),
                "route": str(route.get("route") or "").strip(),
                "resolved_route": str(route.get("resolved_route") or route.get("route") or "").strip(),
                "handler": str(route.get("handler") or "").strip(),
            }
            if normalized["route"] and normalized not in routes_in_scope:
                routes_in_scope.append(normalized)

    query_lower = query.lower()
    for route in state["routes"]:
        route_path = str(route.get("route") or "").strip().lower()
        route_file = str(route.get("path") or "").strip().lower()
        if query_lower and query_lower not in route_path and query_lower not in route_file:
            continue
        normalized = {
            "path": str(route.get("path") or "").strip(),
            "method": str(route.get("method") or "").strip(),
            "route": str(route.get("route") or "").strip(),
            "resolved_route": str(route.get("resolved_route") or route.get("route") or "").strip(),
            "handler": str(route.get("handler") or "").strip(),
        }
        if normalized["route"] and normalized not in routes_in_scope:
            routes_in_scope.append(normalized)

    combined = []
    for candidate in likely_touched + sorted(imported_by) + sorted(imports_to) + sorted(same_symbol_neighbors):
        if candidate and candidate not in combined:
            combined.append(candidate)

    defined_in.sort(key=lambda item: (str(item.get("path") or ""), int(item.get("line_start") or 0)))
    referenced_by_files.sort(key=lambda item: (-int(item.get("count") or 0), str(item.get("path") or "")))
    refactor_candidates.sort(key=lambda item: (-int(item.get("reference_count") or 0), -int(item.get("definition_count") or 0), str(item.get("symbol") or "")))
    call_edges_to.sort(key=lambda item: (-int(item.get("count") or 0), str(item.get("from_path") or ""), str(item.get("to_path") or "")))
    call_edges_from.sort(key=lambda item: (-int(item.get("count") or 0), str(item.get("to_path") or ""), str(item.get("from_path") or "")))
    env_vars_in_scope.sort(key=lambda item: (str(item.get("env") or ""), str(item.get("path") or "")))
    duplicate_logic_neighbors.sort(key=lambda item: (-int(item.get("path_count") or 0), -int(item.get("count") or 0), str(item.get("fingerprint") or "")))
    routes_in_scope.sort(key=lambda item: (str(item.get("path") or ""), str(item.get("method") or ""), str(item.get("route") or "")))
    runtime_surfaces_in_scope.sort(key=lambda item: (-int(item.get("served_route_count") or 0), str(item.get("path") or ""), str(item.get("app_name") or "")))
    public_api_symbols_in_scope.sort(key=lambda item: (-len(item.get("reasons") or []), -int(item.get("external_reference_count") or 0), str(item.get("path") or ""), str(item.get("symbol") or "")))
    isolated_symbols_in_scope.sort(key=lambda item: (str(item.get("confidence") or ""), str(item.get("path") or ""), str(item.get("symbol") or "")))

    rename_scope = None
    if matched_symbols:
        primary_symbol = str(matched_symbols[0].get("symbol") or "").strip()
        if primary_symbol:
            rename_scope = {
                "symbol": primary_symbol,
                "safety": _rename_safety_summary(
                    state,
                    symbol=primary_symbol,
                    changed_paths=combined[: max(1, limit * 2)],
                ),
            }

    return {
        "query": query,
        "matched_files": selected_files[: max(1, limit)],
        "matched_symbols": matched_symbols[: max(1, limit)],
        "defined_in": defined_in[: max(1, limit * 2)],
        "referenced_by_files": referenced_by_files[: max(1, limit)],
        "call_edges_to": call_edges_to[: max(1, limit)],
        "call_edges_from": call_edges_from[: max(1, limit)],
        "routes_in_scope": routes_in_scope[: max(1, limit * 2)],
        "runtime_surfaces_in_scope": runtime_surfaces_in_scope[: max(1, limit)],
        "public_api_symbols_in_scope": public_api_symbols_in_scope[: max(1, limit)],
        "isolated_symbols_in_scope": isolated_symbols_in_scope[: max(1, limit)],
        "env_vars_in_scope": env_vars_in_scope[: max(1, limit)],
        "imported_by": [{"path": rel, "count": int(state["outbound"].get(rel, 0))} for rel in sorted(imported_by)[: max(1, limit)]],
        "imports_to": [{"path": rel, "count": int(state["inbound"].get(rel, 0))} for rel in sorted(imports_to)[: max(1, limit)]],
        "same_symbol_neighbors": sorted(same_symbol_neighbors)[: max(1, limit)],
        "likely_touched_files": combined[: max(1, limit * 2)],
        "refactor_candidates": refactor_candidates[: max(1, limit)],
        "duplicate_logic_neighbors": duplicate_logic_neighbors[: max(1, limit)],
        "rename_scope": rename_scope,
    }


def build_symbol_rename_plan(
    root: Path,
    *,
    manifest: Optional[Dict[str, Any]] = None,
    symbol: str,
    new_symbol: str,
    limit: int = 20,
) -> Dict[str, Any]:
    source_symbol = str(symbol or "").strip()
    target_symbol = str(new_symbol or "").strip()
    if not VALID_IDENTIFIER_PATTERN.match(source_symbol):
        raise ValueError("invalid-source-symbol")
    if not VALID_IDENTIFIER_PATTERN.match(target_symbol):
        raise ValueError("invalid-target-symbol")
    if source_symbol == target_symbol:
        raise ValueError("symbol-unchanged")

    impact = build_project_impact_report(root, manifest=manifest, q=source_symbol, limit=limit)
    state = _build_relation_state(root, manifest)
    candidate_paths: List[str] = []
    for item in impact.get("defined_in") or []:
        path = str((item or {}).get("path") or "").strip()
        if path and path not in candidate_paths:
            candidate_paths.append(path)
    for item in impact.get("referenced_by_files") or []:
        path = str((item or {}).get("path") or "").strip()
        if path and path not in candidate_paths:
            candidate_paths.append(path)
    for item in impact.get("matched_files") or []:
        path = str(item or "").strip()
        if path and path not in candidate_paths:
            candidate_paths.append(path)

    operations: List[Dict[str, Any]] = []
    changed_paths: List[str] = []
    pattern = re.compile(rf"\b{re.escape(source_symbol)}\b")
    for rel in candidate_paths[: max(1, limit)]:
        file_path = root / rel
        try:
            text = file_path.read_text(encoding="utf-8", errors="strict")
        except Exception:
            continue
        updated = pattern.sub(target_symbol, text)
        if updated == text:
            continue
        operations.append(
            {
                "op": "write",
                "path": rel,
                "content": updated,
                "create": False,
            }
        )
        changed_paths.append(rel)

    symbol_refs = state["symbol_reference_files"].get(source_symbol, [])
    symbol_defs = state["symbol_definitions"].get(source_symbol, [])
    rename_safety = _rename_safety_summary(state, symbol=source_symbol, changed_paths=changed_paths)
    return {
        "symbol": source_symbol,
        "new_symbol": target_symbol,
        "operation_count": len(operations),
        "changed_paths": changed_paths,
        "operations": operations,
        "definition_count": len(symbol_defs),
        "reference_count": sum(int(item.get("count") or 0) for item in symbol_refs),
        "defined_in": symbol_defs[: max(1, limit)],
        "referenced_by_files": symbol_refs[: max(1, limit)],
        "rename_safety": rename_safety,
        "review_required": True,
    }


def is_architecture_question(text: str) -> bool:
    lower = (text or "").lower()
    return any(hint in lower for hint in _ARCH_QUESTION_HINTS)
