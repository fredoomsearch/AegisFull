from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator

Role = Literal["system", "user", "assistant", "tool"]


class ChatTurn(BaseModel):
    role: Role
    content: str
    tool_name: Optional[str] = None  # used when role="tool"

    @field_validator("role")
    @classmethod
    def _validate_role(cls, v: str) -> str:
        if v not in {"system", "user", "assistant", "tool"}:
            raise ValueError("Invalid role")
        return v


class WebSearchResult(BaseModel):
    title: str = ""
    snippet: str = ""
    link: str = ""

    def to_dict(self) -> dict:
        return self.model_dump()


class ToolCall(BaseModel):
    name: str
    args: dict[str, Any] = Field(default_factory=dict)


class ToolResult(BaseModel):
    name: str
    success: bool = True
    data: Any = None
    error_message: Optional[str] = None


class ChatRequest(BaseModel):
    """
    HTTP-level request model for a simple /chat endpoint
    (separado del ChatRequest de app.schemas).
    """

    message: str
    history: list[ChatTurn] = Field(default_factory=list)
    use_web_search: bool = False


class ChatMessageChunk(BaseModel):
    token: str
    is_final: bool = False


class ChatResponse(BaseModel):
    reply: str
    used_tools: list[ToolResult] = Field(default_factory=list)
    web_search_results: list[WebSearchResult] = Field(default_factory=list)
    updated_history: list[ChatTurn] = Field(default_factory=list)

    model_config = {"from_attributes": True}
