from __future__ import annotations

"""
Higher-level CRUD helpers that compose lower-level conversation operations.
"""

import logging
from typing import Optional

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db import crud_conversation, models

logger = logging.getLogger(__name__)


def get_conversation(db: Session, conv_id: str) -> Optional[models.Conversation]:
    """
    Thin wrapper around crud_conversation.get_conversation.
    Returns the Conversation instance or None if not found.
    """
    return crud_conversation.get_conversation(db, conv_id)


def create_conversation(db: Session, user_id: str | None = None) -> models.Conversation:
    """
    Create a new conversation and return the Conversation instance.
    """
    conv_id = crud_conversation.create_conversation(db, user_id=user_id)
    conv = crud_conversation.get_conversation(db, conv_id)

    if conv is None:
        logger.error("create_conversation: created conv_id=%s but could not reload from DB", conv_id)
        raise RuntimeError(f"Conversation created but not found when reloading (id={conv_id})")

    logger.debug("create_conversation: created conv_id=%s user_id=%s", conv_id, user_id)
    return conv


def append_messages(
    db: Session,
    conv_id: str,
    user_msg: str,
    assistant_msg: str,
) -> models.Conversation:
    """
    Append a user + assistant message pair to a conversation.

    - If the conversation with conv_id does not exist, creates it using THAT conv_id.
    - Returns the Conversation instance for convenience.
    """
    try:
        conv = get_conversation(db, conv_id)
        if conv is None:
            logger.debug("append_messages: conv_id=%s not found, creating conversation with same id", conv_id)
            conv = models.Conversation(id=conv_id, summary="", archived=False)
            db.add(conv)
            db.commit()
            db.refresh(conv)

        db_msg_u = models.Message(conversation_id=conv.id, role="user", content=user_msg)
        db_msg_a = models.Message(conversation_id=conv.id, role="assistant", content=assistant_msg)

        db.add_all([db_msg_u, db_msg_a])
        db.commit()
        return conv

    except SQLAlchemyError as e:
        db.rollback()
        logger.exception("append_messages: DB error for conv_id=%s: %s", conv_id, e)
        raise
