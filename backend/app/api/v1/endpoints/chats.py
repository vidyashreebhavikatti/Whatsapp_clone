from fastapi import APIRouter, Depends, HTTPException, status
from motor.motor_asyncio import AsyncIOMotorDatabase
from bson import ObjectId
from datetime import datetime, timezone
from app.api.dependencies import get_db, get_current_user_id
from app.schemas.schemas import CreateDirectChatRequest, CreateGroupChatRequest, ChatResponse
from app.core.logging import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/chats", tags=["Chats"])


def _now() -> datetime:
    return datetime.now(timezone.utc)


@router.post("/direct", response_model=ChatResponse, status_code=status.HTTP_201_CREATED)
async def create_or_get_direct_chat(
    body: CreateDirectChatRequest,
    user_id: str = Depends(get_current_user_id),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """
    Create a 1-1 chat or return existing one.
    Participants array is sorted to ensure idempotency:
    same two users always produce the same chat.
    """
    # Validate other user exists
    other = await db.users.find_one({"_id": ObjectId(body.participant_id)})
    if not other:
        raise HTTPException(status_code=404, detail="User not found")

    participants = sorted([ObjectId(user_id), ObjectId(body.participant_id)])

    # Find existing direct chat between these two users
    existing = await db.chats.find_one({
        "type": "direct",
        "participants": {"$all": participants, "$size": 2},
    })
    if existing:
        return _serialize_chat(existing)

    now = _now()
    chat_doc = {
        "type": "direct",
        "participants": participants,
        "group_id": None,
        "last_message": None,
        "created_at": now,
        "updated_at": now,
    }
    result = await db.chats.insert_one(chat_doc)
    chat_doc["_id"] = result.inserted_id

    return _serialize_chat(chat_doc)


@router.post("/group", response_model=ChatResponse, status_code=status.HTTP_201_CREATED)
async def create_group_chat(
    body: CreateGroupChatRequest,
    user_id: str = Depends(get_current_user_id),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Create a new group chat with initial members."""
    now = _now()

    # Build member list (creator is always admin)
    member_ids = list({user_id, *body.member_ids})  # deduplicate
    members = [
        {
            "user_id": ObjectId(uid),
            "role": "admin" if uid == user_id else "member",
            "joined_at": now,
        }
        for uid in member_ids
    ]

    # Create group document
    group_doc = {
        "name": body.name,
        "description": body.description,
        "avatar_url": None,
        "created_by": ObjectId(user_id),
        "members": members,
        "created_at": now,
        "updated_at": now,
    }
    group_result = await db.groups.insert_one(group_doc)
    group_id = group_result.inserted_id

    # Create chat document linked to group
    chat_doc = {
        "type": "group",
        "participants": [ObjectId(uid) for uid in member_ids],
        "group_id": group_id,
        "last_message": None,
        "created_at": now,
        "updated_at": now,
    }
    chat_result = await db.chats.insert_one(chat_doc)
    chat_doc["_id"] = chat_result.inserted_id

    return _serialize_chat(chat_doc, group_name=body.name, group_id=str(group_id))


@router.get("/", response_model=list[ChatResponse])
async def list_my_chats(
    user_id: str = Depends(get_current_user_id),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """
    Return all chats for the current user, sorted by most recent activity.
    Uses compound index on (participants, updated_at).
    """
    chats = await db.chats.find(
        {"participants": ObjectId(user_id)}
    ).sort("updated_at", -1).to_list(length=200)

    # Batch fetch group names
    group_ids = [c["group_id"] for c in chats if c.get("group_id")]
    groups_map = {}
    if group_ids:
        groups = await db.groups.find(
            {"_id": {"$in": group_ids}},
            {"name": 1, "avatar_url": 1},
        ).to_list(length=len(group_ids))
        groups_map = {str(g["_id"]): g for g in groups}

    result = []
    for chat in chats:
        group_info = groups_map.get(str(chat.get("group_id", "")), {})
        result.append(_serialize_chat(
            chat,
            group_name=group_info.get("name"),
            group_avatar=group_info.get("avatar_url"),
            group_id=str(chat["group_id"]) if chat.get("group_id") else None,
        ))

    return result


@router.get("/{chat_id}", response_model=ChatResponse)
async def get_chat(
    chat_id: str,
    user_id: str = Depends(get_current_user_id),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Get details of a specific chat. User must be a participant."""
    chat = await db.chats.find_one({
        "_id": ObjectId(chat_id),
        "participants": ObjectId(user_id),
    })
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")
    return _serialize_chat(chat)


def _serialize_chat(
    chat: dict,
    group_name: str | None = None,
    group_avatar: str | None = None,
    group_id: str | None = None,
) -> dict:
    """Convert MongoDB chat document to API response dict."""
    last_msg = chat.get("last_message")
    return {
        "_id": str(chat["_id"]),
        "type": chat["type"],
        "participants": [str(p) for p in chat["participants"]],
        "group_id": group_id or (str(chat["group_id"]) if chat.get("group_id") else None),
        "group_name": group_name,
        "group_avatar": group_avatar,
        "last_message": last_msg,
        "unread_count": 0,  # Computed per-request if needed; omitted for list perf
        "created_at": chat["created_at"],
        "updated_at": chat["updated_at"],
    }