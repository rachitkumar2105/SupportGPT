from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

Role = Literal["customer", "agent", "admin"]
TicketStatus = Literal["open", "pending", "resolved"]
Priority = Literal["low", "medium", "high", "urgent"]
Category = Literal["billing", "account", "technical", "data", "other"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


# ------------------------------------------------------------------ auth


class SignupIn(Strict):
    name: str = Field(min_length=1, max_length=80)
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        if any(c in v for c in "<>{}\\"):
            raise ValueError("Name contains characters that aren't allowed.")
        return v


class LoginIn(Strict):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class ChangePasswordIn(Strict):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=1, max_length=128)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    email: str
    name: str
    role: Role
    is_demo: bool
    is_active: bool
    created_at: datetime


class SessionOut(BaseModel):
    user: UserOut
    csrf_token: str


# ------------------------------------------------------------------ chat


class MessageIn(Strict):
    content: str = Field(min_length=1, max_length=2000)


class FeedbackIn(Strict):
    value: Literal[-1, 0, 1]


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    role: str
    content: str
    sources: list | None = None
    confidence: float | None = None
    abstained: bool = False
    latency_ms: int | None = None
    model: str | None = None
    feedback: int = 0
    created_at: datetime


class ConversationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    title: str
    status: str
    created_at: datetime
    updated_at: datetime


class ConversationDetail(ConversationOut):
    messages: list[MessageOut]
    ticket_id: int | None = None


class EscalateIn(Strict):
    note: str | None = Field(default=None, max_length=1000)


# ---------------------------------------------------------------- tickets


class PersonOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    email: str


class TicketMessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    kind: str
    body: str
    ai_assisted: bool
    created_at: datetime
    author_name: str | None = None


class TicketOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    subject: str
    summary: str
    category: Category
    priority: Priority
    sentiment: str
    triage_source: str
    status: TicketStatus
    sla_due_at: datetime
    first_response_at: datetime | None
    resolved_at: datetime | None
    csat: int | None
    created_at: datetime
    updated_at: datetime
    customer: PersonOut
    assignee: PersonOut | None = None
    conversation_id: int | None = None


class TicketDetail(TicketOut):
    messages: list[TicketMessageOut]
    transcript: list[MessageOut] = []
    csat_comment: str | None = None


class TicketCreateIn(Strict):
    subject: str = Field(min_length=3, max_length=150)
    body: str = Field(min_length=5, max_length=4000)


class TicketReplyIn(Strict):
    body: str = Field(min_length=1, max_length=4000)
    internal: bool = False
    ai_assisted: bool = False


class TicketPatchIn(Strict):
    status: TicketStatus | None = None
    priority: Priority | None = None
    category: Category | None = None
    assignee_id: int | None = Field(default=None, ge=0)


class CsatIn(Strict):
    score: int = Field(ge=1, le=5)
    comment: str | None = Field(default=None, max_length=500)


class DraftOut(BaseModel):
    text: str
    sources: list
    model: str | None


# --------------------------------------------------------------------- kb


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    title: str
    slug: str
    source: str
    mime: str
    size_bytes: int
    chunk_count: int
    created_at: datetime


class ChunkOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    ord: int
    heading: str | None
    page: int | None
    content: str


class DocumentDetail(DocumentOut):
    chunks: list[ChunkOut]


class SearchIn(Strict):
    query: str = Field(min_length=1, max_length=500)
    k: int = Field(default=5, ge=1, le=10)


# ------------------------------------------------------------------ admin


class UserPatchIn(Strict):
    role: Role | None = None
    is_active: bool | None = None
