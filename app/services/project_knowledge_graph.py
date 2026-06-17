from __future__ import annotations

"""
Project Knowledge Graph - Unified interface for project intelligence.

Why this module exists:
- Consolidate all project introspection into a single API
- Wrap project_introspection.py with caching and smart defaults
- Enable unified context retrieval for all agent tools

Integration:
- Used by context_aggregator.py for project context
- Used by project tools (manifest, excerpt, symbols, files)
- Used by validation_layer.py for framework detection
"""

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.services.project_introspection import (
    build_architecture_profile,
    build_project_intelligence_summary,
    build_project_impact_report,
    detect_frontend_type,
    fuzzy_search_project_files,
    infer_architecture,
    is_architecture_question,
    scan_project_symbols,
    summarize_project_architecture_deep,
    summarize_project_folders,
)
from app.services.tool_cache import get_tool_cache


class ProjectKnowledgeGraph:
    """
    Unified Knowledge Graph interface for project analysis.
    
    Provides:
    - Cached architecture profiles
    - Symbol and file search
    - Impact analysis
    - Frontend type detection
    - Relation graphs
    """
    
    def __init__(self, project_id: str, root_path: str, manifest: Dict[str, Any] | None = None):
        self.project_id = project_id
        self.root_path = root_path
        self._root = Path(root_path) if root_path else None
        self._manifest = manifest
        self._cache = get_tool_cache()
    
    @property
    def root(self) -> Path | None:
        return self._root
    
    @property
    def manifest(self) -> Dict[str, Any] | None:
        return self._manifest
    
    def _ensure_manifest(self) -> Dict[str, Any] | None:
        if self._manifest is not None:
            return self._manifest
        # Lazy load could be added here
        return None
    
    # ============================================================
    # Architecture & Profile
    # ============================================================
    
    def get_architecture_profile(self, force_refresh: bool = False) -> Dict[str, Any]:
        """Get cached or fresh architecture profile."""
        if not force_refresh:
            cached = self._cache.get_architecture_profile(self.project_id)
            if cached:
                return cached
        
        manifest = self._ensure_manifest()
        if not manifest:
            return {}
        
        profile = build_architecture_profile(manifest)
        
        # Cache it
        self._cache.set_architecture_profile(self.project_id, profile)
        return profile
    
    def get_frontend_type(self) -> str | None:
        """Detect frontend framework."""
        manifest = self._ensure_manifest()
        if not manifest:
            return None
        return detect_frontend_type(manifest)
    
    def summarize_architecture(self, *, lang: str = "es") -> str:
        """Human-readable architecture summary."""
        manifest = self._ensure_manifest()
        if not manifest:
            return ""
        return infer_architecture(manifest, lang=lang)
    
    def summarize_deep(self, *, lang: str = "es", limit: int = 4) -> str:
        """Deep architecture analysis with relations."""
        if not self._root:
            return ""
        manifest = self._ensure_manifest()
        if not manifest:
            return ""
        return summarize_project_architecture_deep(
            self._root, manifest, lang=lang, limit=limit
        )
    
    def summarize_folders(self, *, lang: str = "es", limit: int = 6) -> str:
        """Folder breakdown."""
        manifest = self._ensure_manifest()
        if not manifest:
            return ""
        return summarize_project_folders(manifest, lang=lang, limit=limit)
    
    # ============================================================
    # Search & Discovery
    # ============================================================
    
    def search_files(self, q: str, *, limit: int = 80) -> List[Dict[str, Any]]:
        """Fuzzy search project files."""
        manifest = self._ensure_manifest()
        if not manifest:
            return []
        return fuzzy_search_project_files(manifest, q=q, limit=limit)
    
    def search_symbols(self, q: str, *, limit: int = 80) -> List[Dict[str, Any]]:
        """Search project symbols (functions, classes)."""
        if not self._root:
            return []
        manifest = self._ensure_manifest()
        return scan_project_symbols(self._root, manifest=manifest, q=q, limit=limit)
    
    def is_architecture_query(self, text: str) -> bool:
        """Check if query is about architecture."""
        return is_architecture_question(text)
    
    # ============================================================
    # Impact Analysis
    # ============================================================
    
    def analyze_impact(self, q: str, *, limit: int = 8) -> Dict[str, Any]:
        """Full impact analysis for a query."""
        if not self._root:
            return {}
        manifest = self._ensure_manifest()
        return build_project_impact_report(
            self._root, manifest=manifest, q=q, limit=limit
        )
    
    def get_intelligence_summary(self, *, limit: int = 8) -> Dict[str, Any]:
        """Get project intelligence summary."""
        if not self._root:
            return {}
        manifest = self._ensure_manifest()
        return build_project_intelligence_summary(
            self._root, manifest=manifest, limit=limit
        )
    
    # ============================================================
    # Cache Management
    # ============================================================
    
    def invalidate_cache(self) -> int:
        """Invalidate all cached data for this project."""
        return self._cache.invalidate_all(self.project_id)
    
    def refresh_all(self) -> Dict[str, Any]:
        """Force refresh all cached data."""
        self.invalidate_cache()
        
        manifest = self._ensure_manifest()
        if not manifest:
            return {}
        
        results = {
            "architecture_profile": self.get_architecture_profile(force_refresh=True),
            "frontend_type": self.get_frontend_type(),
        }
        return results


# ============================================================
# Factory & Helpers
# ============================================================

def create_project_graph(
    project_id: str,
    root_path: str,
    manifest: Dict[str, Any] | None = None,
) -> ProjectKnowledgeGraph:
    """Factory to create a KnowledgeGraph instance."""
    return ProjectKnowledgeGraph(project_id, root_path, manifest)
