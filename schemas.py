from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field, field_validator


class TicketStatus(str, Enum):
    open = "Open"
    in_progress = "In Progress"
    resolved = "Resolved"
    closed = "Closed"


class TicketPriority(str, Enum):
    low = "Low"
    medium = "Medium"
    high = "High"
    critical = "Critical"


class UserRole(str, Enum):
    admin = "admin"
    developer = "developer"
    customer = "customer"


class SignupRequest(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    password: str = Field(min_length=6)
    email: Optional[str] = None

    @field_validator("username")
    @classmethod
    def strip_username(cls, v):
        return v.strip()

    @field_validator("email")
    @classmethod
    def strip_email(cls, v):
        if v is None:
            return v
        v = v.strip()
        return v or None


class LoginRequest(BaseModel):
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)


class ChangePasswordRequest(BaseModel):
    password: str


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)


class FeedbackRequest(BaseModel):
    query: str = ""
    response: str = ""
    is_positive: bool = True


class TicketCreateRequest(BaseModel):
    issue: str = Field(min_length=1)
    priority: TicketPriority = TicketPriority.medium


class TicketUpdateRequest(BaseModel):
    status: Optional[TicketStatus] = None
    priority: Optional[TicketPriority] = None
    developer_response: Optional[str] = None
    ai_response: Optional[str] = None


class TicketFeedbackRequest(BaseModel):
    rating: Optional[int] = Field(default=None, ge=1, le=5)
    feedback: Optional[str] = None


class RoleUpdateRequest(BaseModel):
    role: UserRole


class VoiceRequest(BaseModel):
    transcript: str = Field(min_length=1)
