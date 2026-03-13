"""
WebSocket Route: /ws/{user_id}
==============================
Entry point for all client WebSocket connections.

Authentication: JWT passed as query param ?token=<access_token>
(Cannot use headers in browser WebSocket API)

Message format:
  Incoming: {"event": "...", "payload": {...}, "event_id": "uuid"}
  Outgoing: {"event": "...", "payload": {...}}
"""
import json
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query, status
from app.websocket.manager import manager
from app.websocket.handlers import (
    handle_join_chat, handle_leave_chat, handle_send_message,
    handle_message_seen, handle_typing, handle_stop_typing,
    handle_heartbeat,
)
from app.core.security import decode_token
from app.db.redis import set_user_online, set_user_offline, is_user_online
from app.db.database import get_database
from app.core.logging import get_logger
from bson import ObjectId
from datetime import datetime, timezone

logger = get_logger(__name__)
router = APIRouter()


async def _authenticate_ws(token: str) -> str | None:
    """
    Validate JWT from WebSocket query param.
    Returns user_id string or None if invalid.
    """
    try:
        payload = decode_token(token, token_type="access")
        return payload["sub"]
    except Exception:
        return None


@router.websocket("/ws/{path_user_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    path_user_id: str,
    token: str = Query(..., description="JWT access token"),
):
    """
    Main WebSocket handler.
    
    Lifecycle:
    1. Authenticate via JWT
    2. Register connection in manager
    3. Mark user online in Redis
    4. Listen for events in infinite loop
    5. On disconnect: clean up and mark offline
    """
    # ── Auth ──────────────────────────────────────────────────────────
    user_id = await _authenticate_ws(token)
    if not user_id or user_id != path_user_id:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        logger.warning(f"WS auth failed for path_user_id={path_user_id}")
        return

    # ── Connect ───────────────────────────────────────────────────────
    await manager.connect(user_id, websocket)
    await set_user_online(user_id)

    # Notify user's contacts that they're online
    await _broadcast_presence(user_id, online=True)

    # Send initial connection ack
    await websocket.send_text(json.dumps({
        "event": "connection_ack",
        "payload": {
            "user_id": user_id,
            "message": "Connected successfully",
        },
    }))
    logger.info(f"WS connected: user_id={user_id}")

    # ── Main event loop ───────────────────────────────────────────────
    try:
        while True:
            raw = await websocket.receive_text()

            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_text(json.dumps({
                    "event": "error",
                    "payload": {"message": "Invalid JSON"},
                }))
                continue

            event = data.get("event")
            payload = data.get("payload", {})
            event_id = data.get("event_id", "")   # client-generated UUID

            # Dispatch to appropriate handler
            response = await _dispatch(event, user_id, payload, event_id)

            # Send response back to this client (if handler returned one)
            if response:
                await websocket.send_text(json.dumps(response))

    except WebSocketDisconnect:
        logger.info(f"WS disconnected: user_id={user_id}")
    except Exception as e:
        logger.error(f"WS error for user={user_id}: {e}", exc_info=True)
    finally:
        # ── Cleanup ───────────────────────────────────────────────────
        await manager.disconnect(user_id)
        await set_user_offline(user_id)

        # Update last_seen in MongoDB
        db = get_database()
        await db.users.update_one(
            {"_id": ObjectId(user_id)},
            {"$set": {"last_seen": datetime.now(timezone.utc), "is_online": False}},
        )

        # Notify contacts user went offline
        await _broadcast_presence(user_id, online=False)


async def _dispatch(event: str, user_id: str, payload: dict, event_id: str):
    """Route event name to handler function."""
    handlers = {
        "join_chat":    lambda: handle_join_chat(user_id, payload),
        "leave_chat":   lambda: handle_leave_chat(user_id, payload),
        "send_message": lambda: handle_send_message(user_id, payload, event_id),
        "message_seen": lambda: handle_message_seen(user_id, payload),
        "typing":       lambda: handle_typing(user_id, payload),
        "stop_typing":  lambda: handle_stop_typing(user_id, payload),
        "ping":         lambda: handle_heartbeat(user_id),
    }

    handler = handlers.get(event)
    if handler is None:
        return {"event": "error", "payload": {"message": f"Unknown event: {event}"}}

    try:
        return await handler()
    except Exception as e:
        logger.error(f"Handler error event={event} user={user_id}: {e}", exc_info=True)
        return {"event": "error", "payload": {"message": "Internal server error"}}


async def _broadcast_presence(user_id: str, online: bool) -> None:
    """
    Notify all contacts of this user's online/offline status.
    We fetch contacts from DB and publish to each via their personal channel.
    """
    db = get_database()
    # Find all chats where this user participates
    chats = await db.chats.find(
        {"participants": ObjectId(user_id)},
        {"participants": 1},
    ).to_list(length=500)

    # Collect unique contact IDs
    contact_ids: set[str] = set()
    for chat in chats:
        for pid in chat["participants"]:
            sid = str(pid)
            if sid != user_id:
                contact_ids.add(sid)

    presence_event = {
        "event": "user_online" if online else "user_offline",
        "payload": {
            "user_id": user_id,
            "online": online,
        },
    }

    for contact_id in contact_ids:
        await manager.publish_to_user(contact_id, presence_event)