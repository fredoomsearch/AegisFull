from __future__ import annotations

"""
FastAPI dependency that yields a DB session per request.
"""

import logging
from typing import Generator

from sqlalchemy.orm import Session

from app.db.base import SessionLocal

logger = logging.getLogger(__name__)


def get_db() -> Generator[Session, None, None]:
    db: Session = SessionLocal()
    logger.debug("get_db: opened session %s", id(db))
    try:
        yield db
        db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception:
            logger.exception("get_db: rollback failed after exception.")
        raise
    finally:
        try:
            db.close()
        except Exception:
            logger.exception("get_db: failed to close DB session.")
