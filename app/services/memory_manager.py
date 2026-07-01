from __future__ import annotations

"""
Memory management utilities for priority-based retention and cleanup.

Used by app/memory.py for weighted eviction.
"""

import logging
import os
import time
from datetime import datetime, UTC
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Priority weights
PRIORITY_RECENT = 1.0
PRIORITY_FREQUENT = 0.8
PRIORITY_OLD = 0.2
PRIORITY_ARCHIVED = 0.0

# Cleanup thresholds
MAX_IDLE_DAYS = int(os.getenv("AEGIS_MEMORY_MAX_IDLE_DAYS", "30"))
MAX_ARCHIVED_AGE_DAYS = int(os.getenv("AEGIS_MEMORY_MAX_ARCHIVED_AGE_DAYS", "7"))


def compute_priority_score(
    *,
    created_at_ms: int,
    updated_at_ms: int,
    archived: bool = False,
    message_count: int = 0,
) -> float:
    """
    Compute priority score for conversation retention.
    
    Args:
        created_at_ms: Creation timestamp
        updated_at_ms: Last update timestamp
        archived: Whether conversation is archived
        message_count: Number of messages
    
    Returns:
        Priority score (0-1, higher = keep)
    """
    now_ms = int(time.time() * 1000)
    
    if archived:
        age_days = (now_ms - updated_at_ms) / (24 * 60 * 60 * 1000)
        if age_days > MAX_ARCHIVED_AGE_DAYS:
            return PRIORITY_ARCHIVED
    
    # Recency score
    age_days = (now_ms - updated_at_ms) / (24 * 60 * 60 * 1000)
    if age_days <= 1:
        recency = PRIORITY_RECENT
    elif age_days <= 7:
        recency = 0.7
    elif age_days <= MAX_IDLE_DAYS:
        recency = 0.5
    else:
        recency = PRIORITY_OLD
    
# Frequency boost (more messages = higher value)
    freq = min(1.0, message_count / 20.0) * PRIORITY_FREQUENT
    
    return recency + freq * 0.3


def rank_conversations_for_eviction(
    conversations: List[Dict[str, Any]],
    *,
    keep_count: int = 10,
) -> List[str]:
    """
    Rank conversations by priority for eviction.
    
    Returns list of conversation IDs to evict (lowest priority first).
    """
    scored = []
    
    for conv in conversations:
        conv_id = conv.get("id") or conv.get("conversation_id")
        if not conv_id:
            continue
        
        score = compute_priority_score(
            created_at_ms=conv.get("created_at_ms", 0),
            updated_at_ms=conv.get("updated_at_ms", 0),
            archived=conv.get("archived", False),
            message_count=conv.get("message_count", 0),
        )
        
        scored.append((conv_id, score))
    
    # Sort by score ascending (evict lowest priority first)
    scored.sort(key=lambda x: x[1])
    
    # Return IDs to evict
    evict_count = max(0, len(conversations) - keep_count)
    return [cid for cid, _ in scored[:evict_count]]


def find_orphan_conversations(
    conversations: List[Dict[str, Any]],
    *,
    active_subject: Optional[str] = None,
) -> List[str]:
    """
    Find orphan conversations (no recent activity, no active project).
    
    Returns list of conversation IDs to clean up.
    """
    orphans = []
    now_ms = int(time.time() * 1000)
    idle_threshold_ms = MAX_IDLE_DAYS * 24 * 60 * 60 * 1000
    
    for conv in conversations:
        conv_id = conv.get("id") or conv.get("conversation_id")
        if not conv_id:
            continue
        
        updated = conv.get("updated_at_ms", 0)
        archived = conv.get("archived", False)
        
        # Idle too long
        if now_ms - updated > idle_threshold_ms:
            orphans.append(conv_id)
            continue
        
        # Archived and old
        if archived:
            age_days = (now_ms - updated) / (24 * 60 * 60 * 1000)
            if age_days > MAX_ARCHIVED_AGE_DAYS:
                orphans.append(conv_id)
    
    return orphans


def cleanup_conversations(
    conversations: List[Dict[str, Any]],
    *,
    keep_count: int = 20,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """
    Run cleanup on conversations.
    
    Returns dict with 'evicted' and 'orphans' lists.
    """
    # Find orphans first
    orphans = find_orphan_conversations(conversations)
    
    # Rank remaining for eviction
    active_convs = [c for c in conversations if c.get("id") not in orphans]
    to_evict = rank_conversations_for_eviction(active_convs, keep_count=keep_count)
    
    result = {
        "orphans": orphans,
        "to_evict": to_evict,
        "total_evicted": len(orphans) + len(to_evict),
    }
    
    if not dry_run:
        logger.info(f"Cleanup: evicting {result['total_evicted']} conversations")
    
    return result


def verify_integrity(
    data: Dict[str, Any],
    *,
    expected_checksum: Optional[str] = None,
) -> bool:
    """
    Verify memory data integrity.
    
    Returns True if valid.
    """
    if not isinstance(data, dict):
        return False
    
    # Check required fields
    for conv_id, conv in data.items():
        if not isinstance(conv, dict):
            logger.warning(f"Invalid conversation {conv_id}")
            return False
        
        # Validate timestamps
        created = conv.get("created_at_ms", 0)
        updated = conv.get("updated_at_ms", 0)
        if created > datetime.now(UTC).timestamp() * 1000:
            logger.warning(f"Future timestamp in {conv_id}")
            return False
        if updated < created:
            logger.warning(f"Updated before created in {conv_id}")
            return False
    
    return True
