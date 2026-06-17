from __future__ import annotations

"""
Project Intelligence - High-level integration for project analysis.

Why this module exists:
- Integrate ToolCache with project introspection
- Provide single entry point for all project analysis
- Enable smart caching and invalidation

Integration:
- Used by project tools for cached analysis
- Used by validation_layer.py for framework detection
- Used by context_aggregator.py for project context
"""

from pathlib import Path
from typing import Any, Dict, List, Optional

from app.services.project_introspection import (
    build_architecture_profile,
    build_project_impact_report,
    build_project_intelligence_summary,
    detect_frontend_type,
    infer_architecture,
)
from app.services.project_knowledge_graph import ProjectKnowledgeGraph
from app.services.tool_cache import get_tool_cache


class ProjectIntelligence:
    """
    High-level project analysis with caching.
    
    This class provides the complete project analysis workflow:
    - Architecture analysis (cached)
    - Symbol/File search
    - Impact analysis
    - Frontend detection
    - Smart cache management
    """
    
    def __init__(self, project_id: str, root_path: str, manifest: Dict[str, Any] | None = None):
        self.project_id = project_id
        self.root_path = root_path
        self._root = Path(root_path) if root_path else None
        self._manifest = manifest
        self._cache = get_tool_cache()
        self._graph = ProjectKnowledgeGraph(project_id, root_path, manifest)
    
    @property
    def root(self) -> Path | None:
        return self._root
    
    @property
    def manifest(self) -> Dict[str, Any] | None:
        return self._manifest
    
    def _ensure_manifest(self) -> Dict[str, Any] | None:
        return self._manifest
    
    # ============================================================
    # Cached Analysis (using ToolCache)
    # ============================================================
    
    def get_architecture_profile(self, force_refresh: bool = False) -> Dict[str, Any]:
        """Get cached architecture profile."""
        if not force_refresh:
            cached = self._cache.get_architecture_profile(self.project_id)
            if cached:
                return cached
        
        manifest = self._ensure_manifest()
        if not manifest:
            return {}
        
        profile = build_architecture_profile(manifest)
        self._cache.set_architecture_profile(self.project_id, profile)
        return profile
    
    def get_frameworks(self, force_refresh: bool = False) -> List[str]:
        """Get cached framework list."""
        if not force_refresh:
            cached = self._cache.get_framework_detection(self.project_id)
            if cached:
                return cached.get("frameworks", [])
        
        manifest = self._ensure_manifest()
        if not manifest:
            return []
        
        # Extract frameworks from manifest
        frameworks = list(manifest.get("frameworks") or [])
        
        # Also detect from file tree
        file_tree = [str(f).lower() for f in (manifest.get("file_tree") or [])]
        
        detected = set(frameworks)
        for fw in ["fastapi", "flask", "django", "express", "react", "vue", "angular"]:
            if any(fw in f for f in file_tree):
                detected.add(fw)
        
        result = list(detected)
        self._cache.set_framework_detection(self.project_id, result)
        return result
    
    def get_frontend_type(self) -> str | None:
        """Detect frontend framework type."""
        manifest = self._ensure_manifest()
        if not manifest:
            return None
        return detect_frontend_type(manifest)
    
    def analyze_impact(self, q: str, *, limit: int = 8) -> Dict[str, Any]:
        """Full impact analysis."""
        if not self._root:
            return {}
        manifest = self._ensure_manifest()
        return build_project_impact_report(self._root, manifest=manifest, q=q, limit=limit)
    
    def get_intelligence_summary(self, *, limit: int = 8) -> Dict[str, Any]:
        """Project intelligence summary."""
        if not self._root:
            return {}
        manifest = self._ensure_manifest()
        return build_project_intelligence_summary(self._root, manifest=manifest, limit=limit)
    
    # ============================================================
    # Using the Knowledge Graph
    # ============================================================
    
    def search_files(self, q: str, *, limit: int = 80) -> List[Dict[str, Any]]:
        """Search project files."""
        return self._graph.search_files(q, limit=limit)
    
    def search_symbols(self, q: str, *, limit: int = 80) -> List[Dict[str, Any]]:
        """Search project symbols."""
        return self._graph.search_symbols(q, limit=limit)
    
    def summarize_architecture(self, *, lang: str = "es") -> str:
        """Architecture summary."""
        return self._graph.summarize_architecture(lang=lang)
    
    def summarize_deep(self, *, lang: str = "es", limit: int = 4) -> str:
        """Deep architecture analysis."""
        return self._graph.summarize_deep(lang=lang, limit=limit)
    
    # ============================================================
    # Cache Management
    # ============================================================
    
    def invalidate_cache(self) -> int:
        """Invalidate all cached data."""
        return self._cache.invalidate_all(self.project_id)
    
    def refresh_all(self) -> Dict[str, Any]:
        """Force refresh all cached data."""
        self.invalidate_cache()
        
        results = {
            "architecture_profile": self.get_architecture_profile(force_refresh=True),
            "frameworks": self.get_frameworks(force_refresh=True),
            "frontend_type": self.get_frontend_type(),
        }
        return results
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        # Tool cache is global, so we can't get per-project stats easily
        # This is a simplified version
        return {
            "project_id": self.project_id,
            "cached": True,
        }


# ============================================================
# Factory Helpers
# ============================================================

def create_project_intelligence(
    project_id: str,
    root_path: str,
    manifest: Dict[str, Any] | None = None,
) -> ProjectIntelligence:
    """Factory to create a ProjectIntelligence instance."""
    return ProjectIntelligence(project_id, root_path, manifest)


def get_cached_architecture(
    project_id: str,
    manifest: Dict[str, Any],
) -> Dict[str, Any]:
    """Convenience function for cached architecture."""
    cache = get_tool_cache()
    
    # Try cache first
    cached = cache.get_architecture_profile(project_id)
    if cached:
        return cached
    
    # Build and cache
    profile = build_architecture_profile(manifest)
    cache.set_architecture_profile(project_id, profile)
    return profile


def get_cached_frameworks(
    project_id: str,
    manifest: Dict[str, Any],
) -> List[str]:
    """Convenience function for cached frameworks."""
    cache = get_tool_cache()
    
    # Try cache first
    cached = cache.get_framework_detection(project_id)
    if cached:
        return cached.get("frameworks", [])
    
    # Extract and cache
    frameworks = list(manifest.get("frameworks") or [])
    file_tree = [str(f).lower() for f in (manifest.get("file_tree") or [])]
    
    detected = set(frameworks)
    for fw in ["fastapi", "flask", "django", "express", "react", "vue", "angular"]:
        if any(fw in f for f in file_tree):
            detected.add(fw)
    
    result = list(detected)
    cache.set_framework_detection(project_id, result)
    return result
