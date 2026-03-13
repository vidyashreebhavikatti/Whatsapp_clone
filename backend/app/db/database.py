from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo import ASCENDING, DESCENDING, TEXT
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# Module-level client — created once, reused across requests
_client: AsyncIOMotorClient | None = None


async def connect_db() -> None:
    """Initialize MongoDB connection and create indexes."""
    global _client
    _client = AsyncIOMotorClient(
        settings.MONGODB_URL,
        maxPoolSize=50,           # connection pool
        minPoolSize=10,
        serverSelectionTimeoutMS=5000,
    )
    db = get_database()
    await _create_indexes(db)
    logger.info(f"Connected to MongoDB: {settings.MONGODB_DB_NAME}")


async def close_db() -> None:
    """Close MongoDB connection pool."""
    global _client
    if _client:
        _client.close()
        logger.info("MongoDB connection closed")


def get_database() -> AsyncIOMotorDatabase:
    """Return the application database. Call after connect_db()."""
    if _client is None:
        raise RuntimeError("Database not initialized. Call connect_db() first.")
    return _client[settings.MONGODB_DB_NAME]


async def _create_indexes(db: AsyncIOMotorDatabase) -> None:
    """
    Create all required MongoDB indexes.
    Idempotent — safe to run on every startup.
    """
    # ── Users ──────────────────────────────────────────────────────────
    await db.users.create_index([("phone", ASCENDING)], unique=True)
    await db.users.create_index([("username", ASCENDING)])
    await db.users.create_index([("username", TEXT)])  # full-text search

    # ── Chats ──────────────────────────────────────────────────────────
    await db.chats.create_index([("participants", ASCENDING)])
    await db.chats.create_index([("updated_at", DESCENDING)])  # recent chats

    # ── Messages ───────────────────────────────────────────────────────
    # Primary query pattern: fetch messages for a chat, newest first
    await db.messages.create_index(
        [("chat_id", ASCENDING), ("created_at", DESCENDING)]
    )
    # Cursor-based pagination uses _id
    await db.messages.create_index(
        [("chat_id", ASCENDING), ("_id", DESCENDING)]
    )
    await db.messages.create_index([("sender_id", ASCENDING)])
    # For counting unread messages
    await db.messages.create_index(
        [("chat_id", ASCENDING), ("status", ASCENDING)]
    )

    # ── Message Status ──────────────────────────────────────────────────
    await db.message_status.create_index(
        [("message_id", ASCENDING), ("user_id", ASCENDING)], unique=True
    )
    await db.message_status.create_index([("user_id", ASCENDING)])

    logger.info("MongoDB indexes created/verified")