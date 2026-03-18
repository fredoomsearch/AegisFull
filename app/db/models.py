from __future__ import annotations

"""
Canonical SQLAlchemy persistence schema.

Why this module exists:
- Define the single source of truth for conversation/message/embedding storage.
- Keep ORM entities stable for chat runtime, retrieval, and strict validation paths.
"""

import uuid

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
)
from sqlalchemy.orm import declarative_base, relationship
from app.utils.runtime_helpers import utcnow_db as _utcnow_db

Base = declarative_base()

__all__ = ["Base", "Conversation", "Message", "Embedding"]

class Conversation(Base):
    """
    What it does:
    - Stores conversation-level metadata and planner session state.

    Why it exists:
    - Root entity for all chat persistence and turn linkage.

    Called from ->
    - `db/crud_conversation.py` conversation/state operations

    Calls ->
    - Related `Message` rows via ORM relationship.
    """
    __tablename__ = "conversations"

    id = Column(
        String(36),
        primary_key=True,
        index=True,
        default=lambda: str(uuid.uuid4()),
    )
    user_id = Column(String, index=True, nullable=True)
    summary = Column(Text, nullable=True)
    session_state_json = Column(Text, nullable=False, default="{}")
    created_at = Column(DateTime, nullable=False, default=_utcnow_db)
    updated_at = Column(
        DateTime,
        nullable=False,
        default=_utcnow_db,
        onupdate=_utcnow_db,
    )
    archived = Column(Boolean, nullable=False, default=False)

    messages = relationship(
        "Message",
        back_populates="conversation",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Conversation id={self.id!r} user_id={self.user_id!r}>"


class Message(Base):
    """
    What it does:
    - Stores individual turn messages (user/assistant/system).

    Why it exists:
    - Canonical turn log for history reconstruction and tool/agent traces.

    Called from ->
    - `db/crud_conversation.py::append_message`

    Calls ->
    - Links to parent `Conversation` and child `Embedding` rows.
    """
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    conversation_id = Column(
        String(36),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    role = Column(String(20), nullable=False)
    content = Column(Text, nullable=False)
    token_count = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime, nullable=False, default=_utcnow_db)

    __table_args__ = (
        CheckConstraint("role in ('user','assistant','system')", name="ck_messages_role"),
    )

    conversation = relationship(
        "Conversation",
        back_populates="messages",
        lazy="joined",
    )
    embeddings = relationship(
        "Embedding",
        back_populates="message",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Message id={self.id} conv_id={self.conversation_id!r} role={self.role!r}>"


class Embedding(Base):
    """
    What it does:
    - Stores vectorized message embeddings and optional score metadata.

    Why it exists:
    - Supports retrieval and semantic context features from persisted turns.

    Called from ->
    - embedding/retrieval pipelines operating on message content

    Calls ->
    - Links to parent `Message` row.
    """
    __tablename__ = "embeddings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    message_id = Column(
        Integer,
        ForeignKey("messages.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    vector = Column(LargeBinary, nullable=False)
    dim = Column(Integer, nullable=False)
    score = Column(Float, nullable=True)
    created_at = Column(DateTime, nullable=False, default=_utcnow_db)

    message = relationship(
        "Message",
        back_populates="embeddings",
        lazy="joined",
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Embedding id={self.id} msg_id={self.message_id}>"


# Composite index for efficient chronological fetches
Index("ix_messages_conv_created", Message.conversation_id, Message.created_at)
Index("ix_conversations_updated", Conversation.updated_at)
