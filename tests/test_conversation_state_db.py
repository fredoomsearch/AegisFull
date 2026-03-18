from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import chat as chat_api
from app.db import crud_conversation
from app.db.models import Base
from app.memory import delete_conversation as delete_memory_conversation
from app.memory import get_conversation_state as get_memory_conversation_state


def test_conversation_state_roundtrip_in_db():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine, future=True, autocommit=False, autoflush=False, expire_on_commit=False)
    db = SessionLocal()
    try:
        conv_id = crud_conversation.create_conversation(db, None)
        state = crud_conversation.set_conversation_state_fields(
            db,
            conv_id,
            active_project_id="proj_123",
            current_task="build login flow",
            current_symbol_focus="AuthService",
        )
        loaded = crud_conversation.get_conversation_state(db, conv_id)
        assert state["active_project_id"] == "proj_123"
        assert loaded["active_project_id"] == "proj_123"
        assert loaded["current_task"] == "build login flow"
        assert loaded["current_symbol_focus"] == "AuthService"
    finally:
        db.close()


def test_chat_db_state_updates_warm_memory_fallback():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine, future=True, autocommit=False, autoflush=False, expire_on_commit=False)
    db = SessionLocal()
    conv_id = ""
    try:
        conv_id = crud_conversation.create_conversation(db, None)
        state = chat_api._set_conversation_state(
            db,
            crud_conversation,
            conv_id,
            True,
            active_project_id="proj_db",
            current_task="inspect auth flow",
        )
        mirror = get_memory_conversation_state(conv_id)
        assert state["active_project_id"] == "proj_db"
        assert mirror["active_project_id"] == "proj_db"
        assert mirror["current_task"] == "inspect auth flow"
    finally:
        if conv_id:
            delete_memory_conversation(conv_id)
        db.close()
