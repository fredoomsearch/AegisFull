from __future__ import annotations

"""
CRUD helper focused on updating Conversation.summary.
"""

import logging
from typing import Optional

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db import models

logger = logging.getLogger(__name__)


def update_summary(
    db: Session,
    conv_id: str,
    summary: str,
    commit: bool = True,
) -> Optional[models.Conversation]:
    """
    Update the summary for a conversation. Optionally defer commit.
    """
    try:
        conv = (
            db.query(models.Conversation)
            .filter(models.Conversation.id == conv_id)
            .one_or_none()
        )
        if conv is None:
            logger.debug("update_summary: conversation not found conv_id=%s", conv_id)
            return None

        conv.summary = summary
        db.add(conv)

        if commit:
            try:
                db.commit()
                db.refresh(conv)
            except SQLAlchemyError:
                db.rollback()
                raise
        return conv

    except SQLAlchemyError as exc:
        try:
            db.rollback()
        except Exception:
            logger.exception("update_summary: rollback failed after exception for conv_id=%s", conv_id)
        logger.exception("update_summary: error for conv_id=%s: %s", conv_id, exc)
        raise
