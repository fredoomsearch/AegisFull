from __future__ import annotations

"""
Low-level CRUD helpers for Conversation and Message.
Single, consistent implementation (UUID conversations, autoincrement message ids).
"""

import logging
from datetime import datetime
from typing import List, Optional
from uuid import uuid4

from sqlalchemy import asc, delete, desc, func, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db import models

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Conversation helpers
# ---------------------------------------------------------------------------
def create_conversation(db: Session, user_id: Optional[str] = None) -> str:
    """
    Create a conversation and return its UUID string.
    """
    conv = models.Conversation(
        id=str(uuid4()),
        user_id=user_id,
        summary="",
        archived=False,
    )
    try:
        db.add(conv)
        db.commit()
        db.refresh(conv)
        return conv.id
    except SQLAlchemyError as exc:
        db.rollback()
        logger.exception(
            "create_conversation: failed to create conversation (user_id=%s): %s",
            user_id,
            exc,
        )
        raise


def get_conversation(db: Session, conv_id: str) -> Optional[models.Conversation]:
    """
    Return a Conversation by id or None if not found.
    """
    try:
        stmt = select(models.Conversation).where(models.Conversation.id == conv_id)
        return db.execute(stmt).scalars().first()
    except SQLAlchemyError as exc:
        logger.exception("get_conversation: error fetching conv_id=%s: %s", conv_id, exc)
        return None


def list_conversations(
    db: Session,
    limit: int = 20,
    include_archived: bool = False,
) -> List[models.Conversation]:
    """
    Return most recent conversations ordered by updated_at desc.
    """
    try:
        stmt = (
            select(models.Conversation)
            .order_by(desc(models.Conversation.updated_at))
            .limit(limit)
        )
        if not include_archived:
            stmt = stmt.where(models.Conversation.archived.is_(False))
        return list(db.execute(stmt).scalars().all())
    except SQLAlchemyError as exc:
        logger.exception("list_conversations failed: %s", exc)
        return []


def set_conversation_archived(
    db: Session,
    conv_id: str,
    archived: bool = True,
) -> bool:
    """
    Toggle archived flag for a conversation.
    """
    try:
        stmt = (
            update(models.Conversation)
            .where(models.Conversation.id == conv_id)
            .values(archived=archived, updated_at=datetime.utcnow())
        )
        res = db.execute(stmt)
        db.commit()
        return bool(res.rowcount)
    except SQLAlchemyError as exc:
        db.rollback()
        logger.exception("set_conversation_archived failed conv_id=%s: %s", conv_id, exc)
        return False


def delete_conversation(db: Session, conv_id: str) -> bool:
    """
    Permanently delete a conversation (and cascade messages/embeddings).
    """
    try:
        stmt = delete(models.Conversation).where(models.Conversation.id == conv_id)
        res = db.execute(stmt)
        db.commit()
        return bool(res.rowcount)
    except SQLAlchemyError as exc:
        db.rollback()
        logger.exception("delete_conversation failed conv_id=%s: %s", conv_id, exc)
        return False


# ---------------------------------------------------------------------------
# Message helpers
# ---------------------------------------------------------------------------
def append_message(
    db: Session,
    conv_id: str,
    role: str,
    content: str,
) -> models.Message:
    """
    Append a message to the conversation, creating the conversation if needed.
    """
    try:
        conv = get_conversation(db, conv_id)
        if conv is None:
            conv = models.Conversation(id=conv_id, summary="", archived=False)
            db.add(conv)
            db.commit()
            db.refresh(conv)
        else:
            conv.updated_at = datetime.utcnow()

        msg = models.Message(
            conversation_id=conv.id,
            role=role,
            content=content,
        )
        db.add(msg)
        db.commit()
        db.refresh(msg)
        return msg
    except SQLAlchemyError as exc:
        db.rollback()
        logger.exception(
            "append_message: failed for conv_id=%s role=%s: %s",
            conv_id,
            role,
            exc,
        )
        raise


def get_recent_messages(
    db: Session,
    conv_id: str,
    limit: int = 20,
) -> List[models.Message]:
    """
    Return the most recent messages (chronological ascending).
    """
    try:
        stmt = (
            select(models.Message)
            .where(models.Message.conversation_id == conv_id)
            .order_by(desc(models.Message.created_at))
            .limit(limit)
        )
        newest_first = list(db.execute(stmt).scalars().all())
        return list(reversed(newest_first))
    except SQLAlchemyError as exc:
        logger.exception(
            "get_recent_messages: error fetching conv_id=%s: %s",
            conv_id,
            exc,
        )
        return []


# ---------------------------------------------------------------------------
# Bulk / archival helpers
# ---------------------------------------------------------------------------
def count_messages_for_conversation(db: Session, conv_id: str) -> int:
    """
    Total messages for the given conversation.
    """
    try:
        stmt = (
            select(func.count())
            .select_from(models.Message)
            .where(models.Message.conversation_id == conv_id)
        )
        return int(db.execute(stmt).scalar() or 0)
    except SQLAlchemyError as exc:
        logger.exception(
            "count_messages_for_conversation: error conv_id=%s: %s", conv_id, exc
        )
        return 0


def fetch_messages_older_than(
    db: Session,
    conv_id: str,
    *,
    keep_recent: int = 200,
    limit: int = 200,
    offset: int = 0,
) -> List[models.Message]:
    """
    Fetch messages older than the newest `keep_recent`, newest-first inside the batch.
    """
    try:
        stmt = (
            select(models.Message)
            .where(models.Message.conversation_id == conv_id)
            .order_by(desc(models.Message.created_at))
            .offset(keep_recent + offset)
            .limit(limit)
        )
        return list(db.execute(stmt).scalars().all())
    except SQLAlchemyError as exc:
        logger.exception(
            "fetch_messages_older_than: error conv_id=%s: %s",
            conv_id,
            exc,
        )
        return []


def delete_old_messages(
    db: Session,
    conv_id: str,
    *,
    keep_recent: int = 200,
) -> int:
    """
    Delete all messages older than the newest `keep_recent`.
    Returns the number of rows deleted.
    """
    try:
        cutoff_stmt = (
            select(models.Message.created_at)
            .where(models.Message.conversation_id == conv_id)
            .order_by(desc(models.Message.created_at))
            .offset(keep_recent)
            .limit(1)
        )
        cutoff = db.execute(cutoff_stmt).scalar()
        if cutoff is None:
            return 0

        del_stmt = delete(models.Message).where(
            models.Message.conversation_id == conv_id,
            models.Message.created_at <= cutoff,
        )
        res = db.execute(del_stmt)
        db.commit()
        return int(res.rowcount or 0)
    except SQLAlchemyError as exc:
        db.rollback()
        logger.exception("delete_old_messages failed for conv_id=%s: %s", conv_id, exc)
        return 0


def fetch_all_messages_in_batches(
    db: Session,
    conv_id: str,
    *,
    limit: int = 500,
    offset: int = 0,
) -> List[models.Message]:
    """
    Retrieve messages in ascending chronological order, paginated.
    """
    try:
        stmt = (
            select(models.Message)
            .where(models.Message.conversation_id == conv_id)
            .order_by(asc(models.Message.created_at))
            .offset(offset)
            .limit(limit)
        )
        return list(db.execute(stmt).scalars().all())
    except SQLAlchemyError as exc:
        logger.exception(
            "fetch_all_messages_in_batches failed conv_id=%s: %s", conv_id, exc
        )
        return []
