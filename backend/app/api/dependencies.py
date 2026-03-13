"""
FastAPI Dependencies
====================
Reusable dependency functions injected via FastAPI's Depends() mechanism.
"""
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from motor.motor_asyncio import AsyncIOMotorDatabase
from bson import ObjectId
from app.core.security import decode_token
from app.db.database import get_database
from app.core.logging import get_logger

logger = get_logger(__name__)

# Bearer token extractor
bearer_scheme = HTTPBearer()


async def get_db() -> AsyncIOMotorDatabase:
    """Dependency: returns the Motor database instance."""
    return get_database()


async def get_current_user_id(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> str:
    """
    Dependency: validates JWT and returns user_id string.
    Raises 401 if token is invalid or expired.
    """
    payload = decode_token(credentials.credentials, token_type="access")
    return payload["sub"]


async def get_current_user(
    user_id: str = Depends(get_current_user_id),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> dict:
    """
    Dependency: returns full user document from MongoDB.
    Raises 401 if user doesn't exist (e.g., deleted after token issued).
    """
    user = await db.users.find_one({"_id": ObjectId(user_id)})
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )
    return user