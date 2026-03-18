from __future__ import annotations

from typing import Optional

from sqlalchemy import Column, DateTime, Float, Integer, String, UniqueConstraint
from sqlalchemy.orm import declarative_base
from app.utils.runtime_helpers import utcnow_db as _utcnow_db

Base = declarative_base()

class KBNews(Base):
    __tablename__ = "kb_news"

    id = Column(Integer, primary_key=True)
    symbol = Column(String(20), index=True, nullable=False)
    ts_pub = Column(DateTime, nullable=True)
    ts_ingest = Column(DateTime, default=_utcnow_db, nullable=False)
    title = Column(String(512), nullable=False)
    summary = Column(String(1024), nullable=True)
    url = Column(String(512), nullable=True)
    source = Column(String(128), nullable=True)
    lang = Column(String(8), nullable=True)
    sentiment = Column(Float, nullable=True)
    hash = Column(String(128), nullable=False)

    __table_args__ = (
        UniqueConstraint("hash", name="uq_kb_news_hash"),
    )
