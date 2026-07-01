from __future__ import annotations

"""
Context scoring for ranking sources by freshness and quality.

Used in _build_response_context() to rank web vs local evidence.
"""

import re
from datetime import datetime, UTC
from typing import Any, Dict, List, Optional

# Freshness weight for recency scoring
FRESINESS_WEIGHT = 0.3


def _parse_timestamp(ts: Any) -> Optional[float]:
    """Parse various timestamp formats."""
    if isinstance(ts, (int, float)):
        return float(ts)
    if isinstance(ts, str):
        try:
            return float(ts)
        except Exception:
            pass
        # Try ISO format
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            return dt.timestamp()
        except Exception:
            pass
    return None


def compute_freshness_score(
    *,
    ts: Any,
    max_age_seconds: float = 3600.0,
    now: Optional[float] = None,
) -> float:
    """
    Compute freshness score (0-1) based on age.
    1 = very fresh, 0 = stale.
    """
    if now is None:
        now = datetime.now(UTC).timestamp()
    
    ts_val = _parse_timestamp(ts)
    if ts_val is None:
        return 0.5  # Unknown age
    
    age = now - ts_val
    if age < 0:
        return 1.0  # Future timestamp = very fresh
    
    if age >= max_age_seconds:
        return 0.0
    
    return 1.0 - (age / max_age_seconds)


def rank_sources(
    sources: List[Dict[str, Any]],
    *,
    prefer_web_for_facts: bool = True,
) -> List[Dict[str, Any]]:
    """
    Rank sources by freshness and quality.
    
    Args:
        sources: List of source dicts with 'origin', 'timestamp', etc.
        prefer_web_for_facts: Web sources get slight boost for factual queries
    
    Returns:
        Sorted list with 'score' field added
    """
    if not sources:
        return []
    
    now = datetime.now(UTC).timestamp()
    scored = []
    
    for src in sources:
        origin = str(src.get("origin") or src.get("source") or "unknown").lower()
        
        # Base score from origin quality
        origin_score = {
            "web": 0.9 if prefer_web_for_facts else 0.8,
            "local": 0.7,
            "manifest": 0.8,
            "model": 0.5,
        }.get(origin, 0.5)
        
        # Freshness boost
        ts = src.get("timestamp") or src.get("ts")
        freshness = compute_freshness_score(ts=ts, now=now)
        
        # Combined score
        total_score = (1 - FRESINESS_WEIGHT) * origin_score + FRESINESS_WEIGHT * freshness
        
        scored.append({**src, "score": total_score, "freshness": freshness})
    
    # Sort by score descending
    scored.sort(key=lambda x: x.get("score", 0), reverse=True)
    return scored


def detect_conflicts(
    web_sources: List[Dict[str, Any]],
    local_sources: List[Dict[str, Any]],
    *,
    threshold: float = 0.3,
) -> List[Dict[str, Any]]:
    """
    Detect conflicts between web and local evidence.
    
    Returns list of conflicts with 'conflict' field.
    """
    conflicts = []
    
    for web in web_sources:
        web_text = str(web.get("text") or web.get("snippet") or "").lower()
        if not web_text:
            continue
            
        for local in local_sources:
            local_text = str(local.get("text") or local.get("snippet") or "").lower()
            if not local_text:
                continue
            
            # Simple keyword-based conflict detection
            web_keywords = set(re.findall(r'\b[a-z]{4,}\b', web_text))
            local_keywords = set(re.findall(r'\b[a-z]{4,}\b', local_text))
            
            common = web_keywords & local_keywords
            if len(common) >= 3:
                # Check for negation patterns
                neg_patterns = (r'\bnot\b', r'\bno\b', r'\bnever\b', r'\bdeny', r'\bfals')
                has_neg_web = any(re.search(p, web_text) for p in neg_patterns)
                has_neg_local = any(re.search(p, local_text) for p in neg_patterns)
                
                if has_neg_web != has_neg_local:
                    conflicts.append({
                        "type": "contradiction",
                        "web": web,
                        "local": local,
                        "keywords": list(common),
                    })
    
    return conflicts
