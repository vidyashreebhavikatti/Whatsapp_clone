from fastapi import APIRouter, Depends, HTTPException, Query
from motor.motor_asyncio import AsyncIOMotorDatabase
from bson import ObjectId
from app.api.dependencies import get_db, get_current_user_id
from app.schemas.schemas import MessagePage, MessageResponse
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/messages", tags=["Messages"])


@router.get("/{chat_id}", response_model=MessagePage)
async def get_messages(
    chat_id: str,
    before: str | None = Query(None, description="Cursor: message _id to fetch before (exclusive)"),
    limit: int = Query(settings.DEFAULT_PAGE_SIZE, le=settings.MAX_PAGE_SIZE),
    user_id: str = Depends(get_current_user_id),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """
    Fetch paginated messages for a chat.
    
    Uses cursor-based pagination for efficiency:
    - First page: no `before` param → returns latest N messages
    - Subsequent pages: `before=<last_message_id>` → returns messages older than that
    
    This avoids MongoDB's skip() which degrades with large collections.
    """
    # Verify user is participant
    chat = await db.chats.find_one({
        "_id": ObjectId(chat_id),
        "participants": ObjectId(user_id),
    })
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found or access denied")

    # Build query — cursor-based: fetch messages with _id < before_id
    query: dict = {"chat_id": ObjectId(chat_id)}
    if before:
        try:
            query["_id"] = {"$lt": ObjectId(before)}
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid cursor value")

    # Fetch limit+1 to determine if there are more pages
    raw_messages = await db.messages.find(query).sort("_id", -1).limit(limit + 1).to_list(length=limit + 1)

    has_more = len(raw_messages) > limit
    messages = raw_messages[:limit]  # trim the extra one

    # Reverse to return chronological order (oldest first in batch)
    messages.reverse()

    serialized = [_serialize_message(m) for m in messages]

    # Next cursor = the oldest message in this batch (for loading even older messages)
    next_cursor = str(messages[0]["_id"]) if has_more and messages else None

    return MessagePage(
        messages=serialized,
        next_cursor=next_cursor,
        has_more=has_more,
    )


@router.delete("/{chat_id}/{message_id}", status_code=204)
async def delete_message(
    chat_id: str,
    message_id: str,
    user_id: str = Depends(get_current_user_id),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """
    Soft-delete a message (sender only).
    Sets is_deleted=True, clears content. Never hard-deletes.
    """
    result = await db.messages.update_one(
        {
            "_id": ObjectId(message_id),
            "chat_id": ObjectId(chat_id),
            "sender_id": ObjectId(user_id),   # only sender can delete
        },
        {"$set": {"is_deleted": True, "content": "", "media_url": None}},
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Message not found or permission denied")
    return None


def _serialize_message(msg: dict) -> dict:
    """Convert MongoDB message document to API response dict."""
    return {
        "_id": str(msg["_id"]),
        "chat_id": str(msg["chat_id"]),
        "sender_id": str(msg["sender_id"]),
        "content": msg.get("content", ""),
        "content_type": msg.get("content_type", "text"),
        "media_url": msg.get("media_url"),
        "thumbnail_url": msg.get("thumbnail_url"),
        "reply_to": msg.get("reply_to"),
        "status": msg.get("status", "sent"),
        "is_deleted": msg.get("is_deleted", False),
        "created_at": msg["created_at"],
        "updated_at": msg["updated_at"],
    }