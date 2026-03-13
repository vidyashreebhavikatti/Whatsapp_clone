"""
WebSocket Connection Manager
============================
Central hub for all real-time communication.

Key responsibilities:
- Track active WebSocket connections per user
- Route messages to connected clients on this instance
- Integrate with Redis Pub/Sub to route across instances
- Manage chat room subscriptions (which users are "watching" which chats)

Architecture note:
  This manager is INSTANCE-LOCAL. Cross-instance delivery is handled
  by publishing events to Redis channels, which all instances subscribe to.
  See: start_redis_subscriber() below.
"""
import asyncio
import json
from typing import Optional
from fastapi import WebSocket
from app.db.redis import get_redis, publish_event, get_pubsub
from app.core.logging import get_logger

logger = get_logger(__name__)


class ConnectionManager:
    def __init__(self):
        # user_id → WebSocket (one active connection per user; latest wins)
        self._connections: dict[str, WebSocket] = {}
        # user_id → set of chat_ids the user currently has open
        self._user_rooms: dict[str, set[str]] = {}
        # chat_id → set of user_ids currently watching this chat
        self._room_users: dict[str, set[str]] = {}
        # Lock to safely modify shared dicts from coroutines
        self._lock = asyncio.Lock()

    # ──────────────────────────────────────────────────────────────
    # Connection lifecycle
    # ──────────────────────────────────────────────────────────────

    async def connect(self, user_id: str, websocket: WebSocket) -> None:
        """Register a new WebSocket connection for a user."""
        await websocket.accept()
        async with self._lock:
            # If user has existing connection (e.g. tab re-opened), close old one
            if user_id in self._connections:
                try:
                    await self._connections[user_id].close(code=4001)
                except Exception:
                    pass
            self._connections[user_id] = websocket
            self._user_rooms.setdefault(user_id, set())
        logger.debug(f"WS connected: user={user_id} total={len(self._connections)}")

    async def disconnect(self, user_id: str) -> None:
        """Remove a user's WebSocket connection and clean up room memberships."""
        async with self._lock:
            self._connections.pop(user_id, None)
            # Remove user from all rooms
            rooms = self._user_rooms.pop(user_id, set())
            for chat_id in rooms:
                if chat_id in self._room_users:
                    self._room_users[chat_id].discard(user_id)
                    if not self._room_users[chat_id]:
                        del self._room_users[chat_id]
        logger.debug(f"WS disconnected: user={user_id}")

    def is_connected(self, user_id: str) -> bool:
        return user_id in self._connections

    # ──────────────────────────────────────────────────────────────
    # Room management (which chats a user has open)
    # ──────────────────────────────────────────────────────────────

    async def join_room(self, user_id: str, chat_id: str) -> None:
        """Track that user has a specific chat open."""
        async with self._lock:
            self._user_rooms.setdefault(user_id, set()).add(chat_id)
            self._room_users.setdefault(chat_id, set()).add(user_id)

    async def leave_room(self, user_id: str, chat_id: str) -> None:
        """User closed/navigated away from a chat."""
        async with self._lock:
            self._user_rooms.get(user_id, set()).discard(chat_id)
            self._room_users.get(chat_id, set()).discard(user_id)

    def get_room_users(self, chat_id: str) -> set[str]:
        """Who is currently viewing this chat (locally, on this instance)."""
        return self._room_users.get(chat_id, set()).copy()

    def get_user_rooms(self, user_id: str) -> set[str]:
        """Which chats this user has open."""
        return self._user_rooms.get(user_id, set()).copy()

    # ──────────────────────────────────────────────────────────────
    # Message sending
    # ──────────────────────────────────────────────────────────────

    async def send_to_user(self, user_id: str, event: dict) -> bool:
        """
        Send an event to a specific user if they're connected to THIS instance.
        Returns True if sent, False if user not connected locally.
        """
        ws = self._connections.get(user_id)
        if ws is None:
            return False
        try:
            await ws.send_text(json.dumps(event))
            return True
        except Exception as e:
            logger.warning(f"Failed to send to user={user_id}: {e}")
            await self.disconnect(user_id)
            return False

    async def broadcast_to_room(
        self,
        chat_id: str,
        event: dict,
        exclude_user: Optional[str] = None,
    ) -> None:
        """
        Send event to all users currently viewing this chat ON THIS INSTANCE.
        For cross-instance delivery, use publish_to_chat() instead.
        """
        room_users = self.get_room_users(chat_id)
        tasks = [
            self.send_to_user(uid, event)
            for uid in room_users
            if uid != exclude_user
        ]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    # ──────────────────────────────────────────────────────────────
    # Redis Pub/Sub integration
    # ──────────────────────────────────────────────────────────────

    async def publish_to_chat(self, chat_id: str, event: dict) -> None:
        """
        Publish event to Redis so ALL instances can deliver it to their
        connected users in this chat.
        """
        await publish_event(f"chat:{chat_id}", event)

    async def publish_to_user(self, user_id: str, event: dict) -> None:
        """
        Publish a targeted event to a specific user via Redis.
        Used for personal notifications (e.g., message_seen from another chat).
        """
        await publish_event(f"user:{user_id}", event)

    async def start_redis_subscriber(self) -> None:
        """
        Long-running coroutine that subscribes to Redis Pub/Sub.
        Listens to all channels matching patterns and routes incoming
        events to locally connected WebSocket clients.

        This runs as a background task for the lifetime of the server.
        """
        pubsub = await get_pubsub()

        # Subscribe to pattern-based channels
        await pubsub.psubscribe("chat:*", "user:*")

        logger.info("Redis subscriber started — listening for cross-instance events")

        try:
            async for raw_message in pubsub.listen():
                if raw_message["type"] not in ("pmessage", "message"):
                    continue

                channel: str = raw_message.get("channel", "")
                data_str: str = raw_message.get("data", "{}")

                try:
                    event = json.loads(data_str)
                except json.JSONDecodeError:
                    continue

                # Route based on channel type
                if channel.startswith("chat:"):
                    chat_id = channel.split(":", 1)[1]
                    await self.broadcast_to_room(
                        chat_id,
                        event,
                        exclude_user=event.get("_exclude"),
                    )
                elif channel.startswith("user:"):
                    user_id = channel.split(":", 1)[1]
                    await self.send_to_user(user_id, event)

        except asyncio.CancelledError:
            logger.info("Redis subscriber cancelled — shutting down")
            await pubsub.punsubscribe("chat:*", "user:*")
            await pubsub.aclose()


# Singleton — imported by WebSocket route handlers
manager = ConnectionManager()