from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from typing import List, Optional, Sequence

from sqlalchemy import select, delete
from sqlalchemy.orm import Session

from app.db.kb_news import KBNews
from app.db.base import SessionLocal
POS_WORDS = {
    "rise",
    "surge",
    "bull",
    "gain",
    "positive",
    "beat",
    "record",
    "upgrade",
    "approve",
    "strong",
    "growth",
}

NEG_WORDS = {
    "fall",
    "drop",
    "bear",
    "loss",
    "negative",
    "miss",
    "hack",
    "ban",
    "lawsuit",
    "fine",
    "weak",
    "decline",
}


def _sentiment_score(text: str | None) -> float:
    if not text:
        return 0.0
    t = text.lower()
    pos = sum(w in t for w in POS_WORDS)
    neg = sum(w in t for w in NEG_WORDS)
    if pos == 0 and neg == 0:
        return 0.0
    score = (pos - neg) / max(1, pos + neg)
    return max(-0.25, min(0.25, score))


def _make_hash(title: str, source: str | None) -> str:
    h = hashlib.sha256()
    h.update((title or "").strip().lower().encode())
    if source:
        h.update(source.strip().lower().encode())
    return h.hexdigest()


def upsert_news_items(symbol: str, items: Sequence[dict], window_minutes: int = 120) -> int:
    if not items:
        return 0
    db: Session = SessionLocal()
    inserted = 0
    cutoff = datetime.utcnow() - timedelta(minutes=window_minutes)
    try:
        for it in items:
            title = (it.get("title") or "").strip()
            if not title:
                continue
            source = (it.get("source") or "").strip() or None
            news_hash = _make_hash(title, source)

            # dedupe recent
            exists = db.execute(select(KBNews.id).where(KBNews.hash == news_hash)).scalar()
            if exists:
                continue

            summary = (it.get("summary") or it.get("snippet") or "").strip() or None
            sent = _sentiment_score(f"{title} {summary or ''}")
            ts_pub = None
            if it.get("published"):
                try:
                    ts_pub = datetime.fromtimestamp(int(it["published"]))
                except Exception:
                    ts_pub = None

            row = KBNews(
                symbol=symbol.upper(),
                ts_pub=ts_pub,
                ts_ingest=datetime.utcnow(),
                title=title,
                summary=summary,
                url=it.get("url") or it.get("link"),
                source=source,
                lang=it.get("lang") or None,
                sentiment=sent,
                hash=news_hash,
            )
            db.add(row)
            inserted += 1

        # optional cleanup of very old news to keep table small
        db.execute(delete(KBNews).where(KBNews.ts_ingest < cutoff - timedelta(days=2)))
        db.commit()
    finally:
        db.close()
    return inserted


def fetch_recent_news(symbol: str, minutes: int = 90, limit: int = 12) -> List[dict]:
    db: Session = SessionLocal()
    try:
        since = datetime.utcnow() - timedelta(minutes=minutes)
        rows = (
            db.query(KBNews)
            .filter(KBNews.symbol == symbol.upper(), KBNews.ts_ingest >= since)
            .order_by(KBNews.ts_ingest.desc())
            .limit(limit)
            .all()
        )
        return [
            {
                "title": r.title,
                "summary": r.summary,
                "sentiment": r.sentiment,
                "source": r.source,
                "url": r.url,
                "ts_ingest": r.ts_ingest.timestamp(),
                "ts_pub": r.ts_pub.timestamp() if r.ts_pub else None,
            }
            for r in rows
        ]
    finally:
        db.close()
