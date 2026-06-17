from __future__ import annotations

import time
from typing import Any, Dict, Optional


class ToolCache:
    """
    Tool result persistence for project introspection.
    
    Why this module exists:
    - Cache expensive project analysis results to avoid re-computation
    - Store framework detection results with TTL-based expiration
    - Enable incremental updates via invalidation
    
    Integration:
    - Used by project_introspection.py for caching architecture analysis
    - Used by validation_layer.py for caching framework detection
    """
    
    def __init__(self, default_ttl: int = 3600):
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._default_ttl = default_ttl
    
    def _make_key(self, project_id: str, key: str) -> str:
        return f"{project_id}:{key}"
    
    def _is_expired(self, entry: Dict[str, Any]) -> bool:
        if not entry.get("ttl"):
            return False
        expires_at = entry.get("expires_at", 0)
        return time.time() > expires_at
    
    def get(self, project_id: str, key: str) -> Optional[Dict[str, Any]]:
        full_key = self._make_key(project_id, key)
        entry = self._cache.get(full_key)
        if not entry:
            return None
        if self._is_expired(entry):
            del self._cache[full_key]
            return None
        return entry.get("data")
    
    def set(
        self,
        project_id: str,
        key: str,
        data: Dict[str, Any],
        ttl: Optional[int] = None,
    ) -> None:
        full_key = self._make_key(project_id, key)
        self._cache[full_key] = {
            "data": data,
            "ttl": ttl or self._default_ttl,
            "expires_at": time.time() + (ttl or self._default_ttl),
            "created_at": time.time(),
        }
    
    def invalidate(self, project_id: str, key: Optional[str] = None) -> int:
        """Invalidate cache entries. Returns count of invalidated entries."""
        prefix = f"{project_id}:"
        if key:
            prefix = f"{prefix}{key}"
        
        to_delete = [
            k for k in self._cache.keys()
            if k.startswith(prefix)
        ]
        
        for k in to_delete:
            del self._cache[k]
        
        return len(to_delete)
    
    def invalidate_all(self, project_id: str) -> int:
        """Invalidate all cache entries for a project."""
        return self.invalidate(project_id, key=None)
    
    def get_project_analysis(
        self,
        project_id: str,
    ) -> Optional[Dict[str, Any]]:
        return self.get(project_id, "analysis")
    
    def set_project_analysis(
        self,
        project_id: str,
        analysis: Dict[str, Any],
        ttl: int = 3600,
    ) -> None:
        self.set(project_id, "analysis", analysis, ttl=ttl)
    
    def get_framework_detection(
        self,
        project_id: str,
    ) -> Optional[list[str]]:
        return self.get(project_id, "frameworks")
    
    def set_framework_detection(
        self,
        project_id: str,
        frameworks: list[str],
        ttl: int = 7200,
    ) -> None:
        self.set(project_id, "frameworks", {"frameworks": frameworks}, ttl=ttl)
    
    def get_architecture_profile(
        self,
        project_id: str,
    ) -> Optional[Dict[str, Any]]:
        return self.get(project_id, "architecture_profile")
    
    def set_architecture_profile(
        self,
        project_id: str,
        profile: Dict[str, Any],
        ttl: int = 3600,
    ) -> None:
        self.set(project_id, "architecture_profile", profile, ttl=ttl)
    
    def clear_expired(self) -> int:
        """Remove all expired entries. Returns count of cleared entries."""
        expired_keys = [
            k for k, v in self._cache.items()
            if self._is_expired(v)
        ]
        for k in expired_keys:
            del self._cache[k]
        return len(expired_keys)


# Global singleton instance
_tool_cache: Optional[ToolCache] = None


def get_tool_cache() -> ToolCache:
    global _tool_cache
    if _tool_cache is None:
        _tool_cache = ToolCache()
    return _tool_cache
