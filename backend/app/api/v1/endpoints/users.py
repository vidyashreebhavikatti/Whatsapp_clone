from fastapi import APIRouter, Depends, HTTPException, Query, status
from motor.motor_asyncio import AsyncIOMotorDatabase
from bson import ObjectId
from app.api.dependencies import get_db, get_current_user_id, get_current_user
from app.schemas.schemas import UserPublic, UserUpdate
from app.db.redis import is_user_online, get_online_users
from app.core.logging import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/users", tags=["Users"])


def _serialize_user(user: dict, online: bool = False) -> dict:
    """Convert MongoDB user document to API response dict."""
    return {
        "_id": str(user["_id"]),
        "phone": user["phone"],
        "username": user["username"],
        "status": user.get("status", ""),
        "avatar_url": user.get("avatar_url"),
        "is_online": online,
        "last_seen": user.get("last_seen"),
        "created_at": user["created_at"],
    }


@router.get("/me", response_model=UserPublic)
async def get_me(
    current_user: dict = Depends(get_current_user),
):
    """Return the authenticated user's own profile."""
    return _serialize_user(current_user, online=True)


@router.patch("/me", response_model=UserPublic)
async def update_me(
    body: UserUpdate,
    user_id: str = Depends(get_current_user_id),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Update username, status message, or avatar."""
    updates = body.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    from datetime import datetime, timezone
    updates["updated_at"] = datetime.now(timezone.utc)

    result = await db.users.find_one_and_update(
        {"_id": ObjectId(user_id)},
        {"$set": updates},
        return_document=True,
    )
    return _serialize_user(result, online=True)


@router.get("/search")
async def search_users(
    q: str = Query(..., min_length=2, description="Search by username or phone"),
    limit: int = Query(20, le=50),
    user_id: str = Depends(get_current_user_id),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """
    Search users by username (prefix match) or phone (exact).
    Excludes the current user from results.
    """
    # Try exact phone match first
    query = {
        "$or": [
            {"phone": q},
            {"username": {"$regex": f"^{q}", "$options": "i"}},
        ],
        "_id": {"$ne": ObjectId(user_id)},  # exclude self
    }

    users = await db.users.find(
        query,
        {"password_hash": 0},  # never return password hash
    ).limit(limit).to_list(length=limit)

    user_ids = [str(u["_id"]) for u in users]
    online_set = await get_online_users(user_ids)

    return [_serialize_user(u, online=str(u["_id"]) in online_set) for u in users]


@router.get("/{target_user_id}", response_model=UserPublic)
async def get_user_profile(
    target_user_id: str,
    _: str = Depends(get_current_user_id),
    db: AsyncIOMotorDatabase = Depends(get_db),
):
    """Get a specific user's public profile."""
    user = await db.users.find_one(
        {"_id": ObjectId(target_user_id)},
        {"password_hash": 0},
    )
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    online = await is_user_online(target_user_id)
    return _serialize_user(user, online=online)