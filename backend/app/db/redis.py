import json
import redis.asyncio as aioredis
from typing import Optional, AsyncIterator
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# Module-level Redis pool — reused across requests
_redis: aioredis.Redis | None = None


async def connect_redis() -> None:
    """Initialize Redis connection pool."""
    global _redis
    _redis = aioredis.from_url(
        settings.REDIS_URL,
        encoding="utf-8",
        decode_responses=True,
        max_connections=100,
    )
    # Verify connection
    await _redis.ping()
    logger.info(f"Connected to Redis: {settings.REDIS_URL}")


async def close_redis() -> None:
    """Close Redis connection pool."""
    global _redis
    if _redis:
        await _redis.aclose()
        logger.info("Redis connection closed")


def get_redis() -> aioredis.Redis:
    """Return the Redis client. Call after connect_redis()."""
    if _redis is None:
        raise RuntimeError("Redis not initialized. Call connect_redis() first.")
    return _redis


# ──────────────────────────────────────────────────────────────────────────────
# Presence helpers
# ──────────────────────────────────────────────────────────────────────────────

async def set_user_online(user_id: str) -> None:
    """Mark user as online with TTL-based expiry."""
    r = get_redis()
    key = f"presence:{user_id}"
    await r.setex(key, settings.REDIS_PRESENCE_TTL, "1")


async def refresh_presence(user_id: str) -> None:
    """Extend online TTL — called on each heartbeat."""
    await set_user_online(user_id)


async def set_user_offline(user_id: str) -> None:
    """Explicitly mark user as offline."""
    r = get_redis()
    await r.delete(f"presence:{user_id}")


async def is_user_online(user_id: str) -> bool:
    """Check if a user's presence key exists in Redis."""
    r = get_redis()
    return bool(await r.exists(f"presence:{user_id}"))


async def get_online_users(user_ids: list[str]) -> set[str]:
    """Batch-check which users from a list are online."""
    r = get_redis()
    pipeline = r.pipeline()
    for uid in user_ids:
        pipeline.exists(f"presence:{uid}")
    results = await pipeline.execute()
    return {uid for uid, online in zip(user_ids, results) if online}


# ──────────────────────────────────────────────────────────────────────────────
# Pub/Sub helpers
# ──────────────────────────────────────────────────────────────────────────────

async def publish_event(channel: str, event: dict) -> None:
    """Publish a JSON event to a Redis Pub/Sub channel."""
    r = get_redis()
    await r.publish(channel, json.dumps(event))


async def get_pubsub() -> aioredis.client.PubSub:
    """Get a new Pub/Sub handle. Caller is responsible for cleanup."""
    # Must create fresh connection for subscribe — cannot use shared pool
    r = aioredis.from_url(
        settings.REDIS_URL,
        encoding="utf-8",
        decode_responses=True,
    )
    return r.pubsub()


# ──────────────────────────────────────────────────────────────────────────────
# Idempotency helpers (for WS message deduplication)
# ──────────────────────────────────────────────────────────────────────────────

async def mark_processed(event_id: str, ttl: int = 300) -> bool:
    """
    Atomically set event_id in Redis (NX = only if not exists).
    Returns True if this is the first time we're processing this event_id.
    Used to deduplicate retried WebSocket events.
    """
    r = get_redis()
    result = await r.set(f"processed:{event_id}", "1", nx=True, ex=ttl)
    return result is True