"""
Pydantic v2 models for request/response validation and serialization.
MongoDB documents use ObjectId which we serialize as strings.
"""
from datetime import datetime
from typing import Optional, Literal, Any
from pydantic import BaseModel, Field, field_validator
from bson import ObjectId


# ──────────────────────────────────────────────────────────────────────────────
# Base helpers
# ──────────────────────────────────────────────────────────────────────────────

class PyObjectId(str):
    """Custom type to handle MongoDB ObjectId serialization."""

    @classmethod
    def __get_validators__(cls):
        yield cls.validate

    @classmethod
    def validate(cls, v: Any) -> str:
        if isinstance(v, ObjectId):
            return str(v)
        if ObjectId.is_valid(v):
            return str(v)
        raise ValueError(f"Invalid ObjectId: {v}")


# ──────────────────────────────────────────────────────────────────────────────
# Auth schemas
# ──────────────────────────────────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    phone: str = Field(..., min_length=7, max_length=15)
    username: str = Field(..., min_length=3, max_length=30)
    password: str = Field(..., min_length=8)


class LoginRequest(BaseModel):
    phone: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user_id: str


class RefreshRequest(BaseModel):
    refresh_token: str


# ──────────────────────────────────────────────────────────────────────────────
# User schemas
# ──────────────────────────────────────────────────────────────────────────────

class UserBase(BaseModel):
    phone: str
    username: str
    status: str = "Hey there! I am using WhatsApp."
    avatar_url: Optional[str] = None


class UserPublic(UserBase):
    """Safe public projection — no password hash."""
    id: str = Field(alias="_id")
    is_online: bool = False
    last_seen: Optional[datetime] = None
    created_at: datetime

    model_config = {"populate_by_name": True}


class UserUpdate(BaseModel):
    username: Optional[str] = Field(None, min_length=3, max_length=30)
    status: Optional[str] = Field(None, max_length=139)
    avatar_url: Optional[str] = None


# ──────────────────────────────────────────────────────────────────────────────
# Chat schemas
# ──────────────────────────────────────────────────────────────────────────────

class CreateDirectChatRequest(BaseModel):
    participant_id: str    # other user's _id


class CreateGroupChatRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=60)
    member_ids: list[str] = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None


class ChatResponse(BaseModel):
    id: str = Field(alias="_id")
    type: Literal["direct", "group"]
    participants: list[str]
    group_id: Optional[str] = None
    group_name: Optional[str] = None
    group_avatar: Optional[str] = None
    last_message: Optional[dict] = None
    unread_count: int = 0
    created_at: datetime
    updated_at: datetime

    model_config = {"populate_by_name": True}


# ──────────────────────────────────────────────────────────────────────────────
# Message schemas
# ──────────────────────────────────────────────────────────────────────────────

ContentType = Literal["text", "image", "video", "audio", "document", "sticker"]
MessageStatus = Literal["sending", "sent", "delivered", "seen", "failed"]


class SendMessageRequest(BaseModel):
    chat_id: str
    content: str = ""
    content_type: ContentType = "text"
    media_url: Optional[str] = None
    thumbnail_url: Optional[str] = None
    reply_to_id: Optional[str] = None
    temp_id: str    # client-generated UUID for optimistic UI


class MessageResponse(BaseModel):
    id: str = Field(alias="_id")
    chat_id: str
    sender_id: str
    content: str
    content_type: ContentType
    media_url: Optional[str] = None
    thumbnail_url: Optional[str] = None
    reply_to: Optional[dict] = None     # embedded reply preview
    status: MessageStatus
    is_deleted: bool = False
    created_at: datetime
    updated_at: datetime

    model_config = {"populate_by_name": True}


class MessagePage(BaseModel):
    """Paginated message response with cursor for next page."""
    messages: list[MessageResponse]
    next_cursor: Optional[str]       # _id of last message, use as `before` param
    has_more: bool


# ──────────────────────────────────────────────────────────────────────────────
# Group schemas
# ──────────────────────────────────────────────────────────────────────────────

class GroupMember(BaseModel):
    user_id: str
    role: Literal["admin", "member"] = "member"
    joined_at: datetime


class GroupResponse(BaseModel):
    id: str = Field(alias="_id")
    name: str
    description: Optional[str] = None
    avatar_url: Optional[str] = None
    created_by: str
    members: list[GroupMember]
    created_at: datetime

    model_config = {"populate_by_name": True}


class AddMembersRequest(BaseModel):
    user_ids: list[str]


# ──────────────────────────────────────────────────────────────────────────────
# Media schemas
# ──────────────────────────────────────────────────────────────────────────────

class MediaUploadResponse(BaseModel):
    media_url: str
    thumbnail_url: Optional[str] = None
    content_type: str
    size_bytes: int


class PresignedUrlRequest(BaseModel):
    filename: str
    content_type: str
    size_bytes: int


class PresignedUrlResponse(BaseModel):
    upload_url: str     # PUT directly to S3
    media_url: str      # CDN URL to store in message
    expires_in: int     # seconds