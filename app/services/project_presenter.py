"""
Conversational project presenter.

Transforms raw manifest data into natural, conversational responses
when users ask about the active project.

Why this module exists:
- Raw manifest data feels robotic and technical
- Users expect humanized explanations in project mode
- Keep same data structure for UI, add conversational text
"""

from typing import Any, Dict


def _extract_summary(manifest: Dict[str, Any], lang: str) -> str:
    """Extract project summary from manifest."""
    summary = manifest.get("readme_summary") or ""
    if summary:
        return summary
    # Try to infer from architecture/layers
    arch = manifest.get("architecture", {})
    if isinstance(arch, dict):
        layers = arch.get("layers", [])
        if layers:
            return f"Project with {len(layers)} architectural layers"
    return ""


def _detect_project_type(manifest: Dict[str, Any]) -> Dict[str, str]:
    """Detect project type from file patterns."""
    py_files = manifest.get("languages", [])
    has_fastapi = False
    has_flask = False
    has_django = False
    has_react = False
    has_angular = False
    
    # Check top-level files
    key_files = manifest.get("key_files", [])
    file_tree = manifest.get("file_tree", [])[:50]  # Limit check
    
    all_files = set(key_files + list(file_tree))
    
    for f in all_files:
        f_lower = str(f).lower()
        if "fastapi" in f_lower:
            has_fastapi = True
        if "flask" in f_lower:
            has_flask = True
        if "django" in f_lower:
            has_django = True
        if "react" in f_lower:
            has_react = True
        if "angular" in f_lower:
            has_angular = True
    
    if has_fastapi:
        return {"type": "fastapi", "name": "FastAPI", "es": "proyecto FastAPI", "en": "FastAPI project"}
    if has_flask:
        return {"type": "flask", "name": "Flask", "es": "proyecto Flask", "en": "Flask project"}
    if has_django:
        return {"type": "django", "name": "Django", "es": "proyecto Django", "en": "Django project"}
    if has_angular:
        return {"type": "angular", "name": "Angular", "es": "aplicación Angular", "en": "Angular application"}
    if has_react:
        return {"type": "react", "name": "React", "es": "aplicación React", "en": "React application"}
    
    return {"type": "generic", "name": "Python", "es": "proyecto Python", "en": "Python project"}


def _format_file_count(files: int, lang: str) -> str:
    """Format file count in natural language."""
    if lang.startswith("es"):
        if files == 1:
            return "1 archivo"
        if files < 100:
            return f"alrededor de {files} archivos"
        if files < 1000:
            return f"más de {files} archivos"
        return f"más de {files} archivos"
    else:
        if files == 1:
            return "1 file"
        if files < 100:
            return f"around {files} files"
        if files < 1000:
            return f"{files} files"
        return f"{files}+ files"


def _format_layer_description(layers: list, lang: str) -> str:
    """Convert architectural layers to natural description."""
    if not layers:
        return ""
    
    # Filter common layers
    meaningful = [l for l in layers if l not in {"security", "serverless", "ci", "monitoring"}]
    
    if lang.startswith("es"):
        if not meaningful:
            return ""
        if len(meaningful) == 1:
            return f"Cuenta con {meaningful[0]}"
        return f"Cuenta con {', '.join(meaningful[:-1])} y {meaningful[-1]}"
    else:
        if not meaningful:
            return ""
        if len(meaningful) == 1:
            return f"It has {meaningful[0]}"
        return f"It has {', '.join(meaningful[:-1])} and {meaningful[-1]}"


def _format_directories(top_dirs: list, lang: str) -> str:
    """Format top directories in natural language."""
    if not top_dirs:
        return ""
    
    # Map to readable names
    dir_map = {
        "app": "app/" if lang.startswith("es") else "app/",
        "data": "data/" if lang.startswith("es") else "data/",
        "models": "models/" if lang.startswith("es") else "models/",
        "tests": "tests/" if lang.startswith("es") else "tests/",
        "ui": "ui/" if lang.startswith("es") else "ui/",
        "docs": "docs/" if lang.startswith("es") else "docs/",
    }
    
    rows = []
    for d in top_dirs[:6]:
        if isinstance(d, dict):
            name = d.get("name", "")
            count = d.get("count", 0)
        else:
            name = str(d)
            count = 0
        
        readable_name = dir_map.get(name, name)
        if count > 0:
            rows.append(f"{readable_name} ({count})")
        else:
            rows.append(readable_name)
    
    if lang.startswith("es"):
        return "Los directorios principales son: " + ", ".join(rows)
    return "Main directories: " + ", ".join(rows)


def _format_entrypoints(entrypoints: list, lang: str) -> str:
    """Format entry points in natural language."""
    if not entrypoints:
        return ""
    
    items = [str(e) for e in entrypoints[:3]]
    
    if lang.startswith("es"):
        if len(items) == 1:
            return f"El punto de entrada es {items[0]}"
        return f"Los puntos de entrada son: {', '.join(items)}"
    else:
        if len(items) == 1:
            return f"The entry point is {items[0]}"
        return f"Entry points: {', '.join(items)}"


def _format_configs(config_files: list, lang: str) -> str:
    """Format config files in natural language."""
    if not config_files:
        return ""
    
    items = [str(c).split("/")[-1] for c in config_files[:5]]
    unique = list(dict.fromkeys(items))  # Remove dupes
    
    if lang.startswith("es"):
        return f"Configuraciones: {', '.join(unique)}"
    return f"Config files: {', '.join(unique)}"


def _format_symbols(symbols: list, lang: str) -> str:
    """Format public symbols in natural language."""
    if not symbols:
        return ""
    
    items = []
    for s in symbols[:6]:
        if isinstance(s, dict):
            name = str(s.get("name") or s.get("symbol") or "")
            location = str(s.get("location") or "")
        else:
            name = str(s)
            location = ""
        
        if name and name not in items:
            items.append(name)
    
    if lang.startswith("es"):
        if not items:
            return ""
        return f"Componentes clave: {', '.join(items)}"
    else:
        if not items:
            return ""
        return f"Key components: {', '.join(items)}"


def present_project_overview(manifest: Dict[str, Any], lang: str = "es") -> str:
    """
    Generate conversational project overview.
    
    Args:
        manifest: Project manifest dict
        lang: Language code (es/en)
    
    Returns:
        Natural language project overview
    """
    if not manifest:
        return ""
    
    parts: list[str] = []
    
    # Project type detection
    proj_type = _detect_project_type(manifest)
    type_name = proj_type.get(lang, proj_type.get("en", "proyecto"))
    
    # File count
    stats = manifest.get("stats", {}) if isinstance(manifest.get("stats"), dict) else {}
    files = int(stats.get("files", 0))
    file_count = _format_file_count(files, lang)
    
    # Build introduction
    if lang.startswith("es"):
        intro = f"Es un {type_name} con {file_count}."
        parts.append(intro)
    else:
        intro = f"This is a {type_name} with {file_count}."
        parts.append(intro)
    
    # Architecture layers
    arch = manifest.get("architecture", {})
    if isinstance(arch, dict):
        layers = arch.get("layers", [])
        layer_desc = _format_layer_description(layers, lang)
        if layer_desc:
            parts.append(layer_desc)
    
    # Top directories
    top_dirs = []
    if isinstance(arch, dict):
        top_dirs = arch.get("top_dirs", [])
    dirs_desc = _format_directories(top_dirs, lang)
    if dirs_desc:
        parts.append(dirs_desc)
    
    return " ".join(parts)


def present_architecture(manifest: Dict[str, Any], lang: str = "es") -> str:
    """
    Generate conversational architecture description.
    
    Args:
        manifest: Project manifest dict
        lang: Language code (es/en)
    
    Returns:
        Natural language architecture overview
    """
    if not manifest:
        return ""
    
    parts: list[str] = []
    arch = manifest.get("architecture", {})
    
    if not isinstance(arch, dict):
        return ""
    
    # Entry points
    entrypoints = arch.get("entrypoints", [])
    entry_desc = _format_entrypoints(entrypoints, lang)
    if entry_desc:
        parts.append(entry_desc)
    
    # Config files
    config_files = arch.get("config_files", [])
    config_desc = _format_configs(config_files, lang)
    if config_desc:
        parts.append(config_desc)
    
    # Layers description
    layers = arch.get("layers", [])
    layer_desc = _format_layer_description(layers, lang)
    if layer_desc:
        parts.append(layer_desc)
    
    if not parts:
        return ""
    
    return " ".join(parts)


def present_capabilities(manifest: Dict[str, Any], lang: str = "es") -> str:
    """
    Generate conversational capabilities description.
    
    Args:
        manifest: Project manifest dict
        lang: Language code (es/en)
    
    Returns:
        Natural language capabilities
    """
    if not manifest:
        return ""
    
    parts: list[str] = []
    arch = manifest.get("architecture", {})
    
    if not isinstance(arch, dict):
        return ""
    
    # Detect capabilities from layers
    layers = arch.get("layers", [])
    capabilities = []
    
    layer_capability_map = {
        "auth": ("autenticación", "authentication"),
        "crypto": ("criptomonedas", "crypto trading"),
        "image": ("generación de imágenes", "image generation"),
        "ai_rag": ("búsqueda con IA", "AI-powered search"),
        "database": ("base de datos", "database"),
        "backend": ("API backend", "backend API"),
        "frontend": ("interfaz de usuario", "frontend"),
        "tests": ("pruebas automatizadas", "tests"),
    }
    
    for layer, (es_name, en_name) in layer_capability_map.items():
        if layer in layers:
            capabilities.append((es_name, en_name))
    
    if capabilities:
        if lang.startswith("es"):
            caps = ", ".join([c[0] for c in capabilities[:-1]])
            if len(capabilities) > 1:
                caps += " y " + capabilities[-1][0]
            else:
                caps = capabilities[0][0]
            parts.append(f"Soporta: {caps}")
        else:
            caps = ", ".join([c[1] for c in capabilities[:-1]])
            if len(capabilities) > 1:
                caps += " and " + capabilities[-1][1]
            else:
                caps = capabilities[0][1]
            parts.append(f"Capabilities: {caps}")
    
    # Public symbols
    key_files = manifest.get("key_files", [])
    symbols_desc = _format_symbols(key_files, lang)
    if symbols_desc:
        parts.append(symbols_desc)
    
    if not parts:
        return ""
    
    return " ".join(parts)


def present_full_description(manifest: Dict[str, Any], lang: str = "es") -> str:
    """
    Generate complete conversational project description.
    
    Combines overview, architecture, and capabilities.
    
    Args:
        manifest: Project manifest dict
        lang: Language code (es/en)
    
    Returns:
        Complete natural language description
    """
    if not manifest:
        return ""
    
    sections: list[str] = []
    
    # Overview
    overview = present_project_overview(manifest, lang)
    if overview:
        sections.append(overview)
    
    # Architecture
    architecture = present_architecture(manifest, lang)
    if architecture:
        sections.append(architecture)
    
    # Capabilities
    capabilities = present_capabilities(manifest, lang)
    if capabilities:
        sections.append(capabilities)
    
    return "\n\n".join(sections)


def present_improvements(manifest: Dict[str, Any], lang: str = "es") -> str:
    """
    Suggest areas for project improvement.
    
    Args:
        manifest: Project manifest dict
        lang: Language code (es/en)
    
    Returns:
        Improvement suggestions
    """
    if not manifest:
        return ""
    
    parts: list[str] = []
    suggestions = []
    
    # Check for missing components
    arch = manifest.get("architecture", {})
    if isinstance(arch, dict):
        layers = arch.get("layers", [])
        
        # Check for missing items
        if "tests" not in layers:
            if lang.startswith("es"):
                suggestions.append("Agregar suite de pruebas unitarias")
            else:
                suggestions.append("Add unit test suite")
        
        if "ci" not in layers:
            if lang.startswith("es"):
                suggestions.append("Agregar pipeline de CI/CD")
            else:
                suggestions.append("Add CI/CD pipeline")
        
        if "monitoring" not in layers:
            if lang.startswith("es"):
                suggestions.append("Agregar monitoreo y métricas")
            else:
                suggestions.append("Add monitoring and metrics")
    
    if not suggestions:
        return ""
    
    if lang.startswith("es"):
        header = "Áreas de mejora:"
    else:
        header = "Areas for improvement:"
    
    parts.append(header)
    parts.append("\n- " + "\n- ".join(suggestions))
    
    return "".join(parts)
