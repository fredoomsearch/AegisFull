from __future__ import annotations

"""
SQLAlchemy ORM models: Conversation, Message, Embedding.
The module now exposes a single, consistent schema (UUID conversations,
integer autoincrement message ids, DateTime timestamps).
"""

import uuid
from datetime import datetime

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

Base = declarative_base()

__all__ = ["Base", "Conversation", "Message", "Embedding"]


class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(
        String(36),
        primary_key=True,
        index=True,
        default=lambda: str(uuid.uuid4()),
    )
    user_id = Column(String, index=True, nullable=True)
    summary = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
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
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

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
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

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
