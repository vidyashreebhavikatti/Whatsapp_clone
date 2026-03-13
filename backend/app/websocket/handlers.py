"""
WebSocket Event Handlers
========================
Processes all incoming WebSocket events from clients.

Event protocol (JSON):
  Client → Server: {"event": "send_message", "payload": {...}, "event_id": "uuid"}
  Server → Client: {"event": "message_ack", "payload": {...}}

All handlers follow the pattern:
  1. Parse and validate payload
  2. Perform DB operation (if needed)
  3. Publish to Redis (for cross-instance delivery)
  4. Return ack to sender
"""
import uuid
from datetime import datetime, timezone
from bson import ObjectId
from app.websocket.manager import manager
from app.db.database import get_database
from app.db.redis import (
    set_user_online, set_user_offline, refresh_presence,
    is_user_online, mark_processed,
)
from app.core.logging import get_logger

logger = get_logger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _new_oid() -> ObjectId:
    return ObjectId()


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

async def _get_chat_participants(chat_id: str) -> list[str]:
    """Fetch participant user_ids for a chat from MongoDB."""
    db = get_database()
    chat = await db.chats.find_one(
        {"_id": ObjectId(chat_id)},
        {"participants": 1},
    )
    if not chat:
        return []
    return [str(uid) for uid in chat["participants"]]


# ──────────────────────────────────────────────────────────────────────────────
# Event: join_chat
# ──────────────────────────────────────────────────────────────────────────────

async def handle_join_chat(user_id: str, payload: dict) -> dict:
    """
    User opens a chat window.
    - Register them in the room (for typing indicators etc.)
    - Auto-mark unread messages as "seen"
    """
    chat_id = payload.get("chat_id")
    if not chat_id:
        return {"event": "error", "payload": {"message": "chat_id required"}}

    await manager.join_room(user_id, chat_id)

    # Mark all delivered messages in this chat as "seen"
    await handle_mark_seen_batch(user_id, chat_id)

    return {"event": "joined_chat", "payload": {"chat_id": chat_id}}


# ──────────────────────────────────────────────────────────────────────────────
# Event: leave_chat
# ──────────────────────────────────────────────────────────────────────────────

async def handle_leave_chat(user_id: str, payload: dict) -> None:
    """User closed/navigated away from a chat."""
    chat_id = payload.get("chat_id")
    if chat_id:
        await manager.leave_room(user_id, chat_id)


# ──────────────────────────────────────────────────────────────────────────────
# Event: send_message
# ──────────────────────────────────────────────────────────────────────────────

async def handle_send_message(user_id: str, payload: dict, event_id: str) -> dict:
    """
    Core message send flow:
    1. Idempotency check (deduplicate retries)
    2. Persist to MongoDB
    3. Update chat.last_message
    4. Publish to Redis for all participants
    5. Return ack to sender
    """
    # Idempotency: if we've seen this event_id before, skip processing
    is_new = await mark_processed(event_id)
    if not is_new:
        logger.debug(f"Duplicate event_id={event_id}, skipping")
        # Still return ack so client stops retrying
        return {
            "event": "message_ack",
            "payload": {
                "temp_id": payload.get("temp_id"),
                "status": "sent",
                "duplicate": True,
            },
        }

    chat_id = payload.get("chat_id")
    content = payload.get("content", "")
    content_type = payload.get("content_type", "text")
    media_url = payload.get("media_url")
    thumbnail_url = payload.get("thumbnail_url")
    reply_to_id = payload.get("reply_to_id")
    temp_id = payload.get("temp_id")

    if not chat_id:
        return {"event": "error", "payload": {"message": "chat_id required"}}

    db = get_database()
    now = _now()
    message_oid = _new_oid()

    # Fetch reply preview if replying
    reply_preview = None
    if reply_to_id:
        original = await db.messages.find_one(
            {"_id": ObjectId(reply_to_id)},
            {"content": 1, "sender_id": 1, "content_type": 1},
        )
        if original:
            reply_preview = {
                "id": str(original["_id"]),
                "sender_id": str(original["sender_id"]),
                "content": original["content"][:100],
                "content_type": original["content_type"],
            }

    # Persist message
    message_doc = {
        "_id": message_oid,
        "chat_id": ObjectId(chat_id),
        "sender_id": ObjectId(user_id),
        "content": content,
        "content_type": content_type,
        "media_url": media_url,
        "thumbnail_url": thumbnail_url,
        "reply_to": reply_preview,
        "status": "sent",
        "is_deleted": False,
        "created_at": now,
        "updated_at": now,
    }
    await db.messages.insert_one(message_doc)

    # Update chat's last_message and updated_at
    await db.chats.update_one(
        {"_id": ObjectId(chat_id)},
        {
            "$set": {
                "last_message": {
                    "id": str(message_oid),
                    "content": content if content_type == "text" else f"[{content_type}]",
                    "sender_id": user_id,
                    "created_at": now,
                },
                "updated_at": now,
            }
        },
    )

    # Build the event payload to broadcast
    message_payload = {
        "id": str(message_oid),
        "chat_id": chat_id,
        "sender_id": user_id,
        "content": content,
        "content_type": content_type,
        "media_url": media_url,
        "thumbnail_url": thumbnail_url,
        "reply_to": reply_preview,
        "status": "sent",
        "created_at": now.isoformat(),
        "temp_id": temp_id,
    }

    # Get all chat participants to notify them
    participants = await _get_chat_participants(chat_id)

    # Deliver to each participant via their personal Redis channel
    # (works across instances since each server subscribes to user:* channels)
    for participant_id in participants:
        if participant_id == user_id:
            continue   # don't send to self via broadcast

        online = await is_user_online(participant_id)
        delivery_event = {
            "event": "receive_message",
            "payload": {
                **message_payload,
                "status": "delivered" if online else "sent",
            },
        }
        await manager.publish_to_user(participant_id, delivery_event)

        # Update status to delivered if recipient is online
        if online:
            await db.messages.update_one(
                {"_id": message_oid},
                {"$set": {"status": "delivered", "updated_at": _now()}},
            )

    return {
        "event": "message_ack",
        "payload": {
            "temp_id": temp_id,
            "real_id": str(message_oid),
            "chat_id": chat_id,
            "status": "sent",
            "created_at": now.isoformat(),
        },
    }


# ──────────────────────────────────────────────────────────────────────────────
# Event: message_seen
# ──────────────────────────────────────────────────────────────────────────────

async def handle_message_seen(user_id: str, payload: dict) -> None:
    """
    User has read a message (or batch of messages).
    - Update message status
    - Notify sender via their personal Redis channel
    """
    message_id = payload.get("message_id")
    chat_id = payload.get("chat_id")

    if not message_id or not chat_id:
        return

    db = get_database()
    now = _now()

    # Fetch message to find sender
    msg = await db.messages.find_one(
        {"_id": ObjectId(message_id)},
        {"sender_id": 1, "status": 1},
    )
    if not msg or str(msg["sender_id"]) == user_id:
        return  # Don't update own messages

    # Update status (only upgrade: sent→delivered→seen, never downgrade)
    await db.messages.update_one(
        {"_id": ObjectId(message_id), "status": {"$ne": "seen"}},
        {"$set": {"status": "seen", "updated_at": now}},
    )

    # Store per-user status for group chats
    await db.message_status.update_one(
        {"message_id": ObjectId(message_id), "user_id": ObjectId(user_id)},
        {"$set": {"status": "seen", "timestamp": now}},
        upsert=True,
    )

    # Notify original sender their message was seen
    sender_id = str(msg["sender_id"])
    seen_event = {
        "event": "message_seen",
        "payload": {
            "message_id": message_id,
            "chat_id": chat_id,
            "seen_by": user_id,
            "timestamp": now.isoformat(),
        },
    }
    await manager.publish_to_user(sender_id, seen_event)


async def handle_mark_seen_batch(user_id: str, chat_id: str) -> None:
    """
    Mark all unread messages in a chat as seen when user opens it.
    Called automatically on join_chat.
    """
    db = get_database()
    now = _now()

    # Find all messages in this chat not sent by user, not yet seen
    unread_msgs = await db.messages.find(
        {
            "chat_id": ObjectId(chat_id),
            "sender_id": {"$ne": ObjectId(user_id)},
            "status": {"$in": ["sent", "delivered"]},
        },
        {"_id": 1, "sender_id": 1},
    ).to_list(length=500)

    if not unread_msgs:
        return

    msg_ids = [m["_id"] for m in unread_msgs]

    # Bulk update to "seen"
    await db.messages.update_many(
        {"_id": {"$in": msg_ids}},
        {"$set": {"status": "seen", "updated_at": now}},
    )

    # Notify each unique sender
    sender_ids = {str(m["sender_id"]) for m in unread_msgs}
    for sender_id in sender_ids:
        if sender_id == user_id:
            continue
        seen_event = {
            "event": "messages_seen_batch",
            "payload": {
                "chat_id": chat_id,
                "seen_by": user_id,
                "timestamp": now.isoformat(),
            },
        }
        await manager.publish_to_user(sender_id, seen_event)


# ──────────────────────────────────────────────────────────────────────────────
# Event: typing / stop_typing
# ──────────────────────────────────────────────────────────────────────────────

async def handle_typing(user_id: str, payload: dict) -> None:
    """
    Broadcast typing indicator to chat participants.
    Pure ephemeral — no DB writes.
    """
    chat_id = payload.get("chat_id")
    if not chat_id:
        return

    typing_event = {
        "event": "typing",
        "payload": {"chat_id": chat_id, "user_id": user_id},
        "_exclude": user_id,  # don't echo back to typer
    }
    await manager.publish_to_chat(chat_id, typing_event)


async def handle_stop_typing(user_id: str, payload: dict) -> None:
    """Broadcast stop-typing to chat participants."""
    chat_id = payload.get("chat_id")
    if not chat_id:
        return

    stop_event = {
        "event": "stop_typing",
        "payload": {"chat_id": chat_id, "user_id": user_id},
        "_exclude": user_id,
    }
    await manager.publish_to_chat(chat_id, stop_event)


# ──────────────────────────────────────────────────────────────────────────────
# Event: heartbeat (ping/pong for presence refresh)
# ──────────────────────────────────────────────────────────────────────────────

async def handle_heartbeat(user_id: str) -> dict:
    """Client pings every 15s to keep presence alive."""
    await refresh_presence(user_id)
    return {"event": "pong", "payload": {"timestamp": _now().isoformat()}}