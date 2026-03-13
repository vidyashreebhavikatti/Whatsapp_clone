from fastapi import APIRouter, Depends, HTTPException, status
from motor.motor_asyncio import AsyncIOMotorDatabase
from bson import ObjectId
from datetime import datetime, timezone
from app.api.dependencies import get_db, get_current_user_id
from app.core.security import hash_password, verify_password, create_access_token, create_refresh_token, decode_token
from app.schemas.schemas import RegisterRequest, LoginRequest, TokenResponse, RefreshRequest
from app.core.logging import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(body: RegisterRequest, db: AsyncIOMotorDatabase = Depends(get_db)):
    """
    Register a new user.
    - Phone must be unique (E.164 format: +1234567890)
    - Password is bcrypt-hashed before storage
    """
    # Check phone uniqueness
    existing = await db.users.find_one({"phone": body.phone})
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Phone number already registered",
        )

    now = datetime.now(timezone.utc)
    user_doc = {
        "phone": body.phone,
        "username": body.username,
        "password_hash": hash_password(body.password),
        "status": "Hey there! I am using WhatsApp.",
        "avatar_url": None,
        "is_online": False,
        "last_seen": now,
        "created_at": now,
        "updated_at": now,
    }

    result = await db.users.insert_one(user_doc)
    user_id = str(result.inserted_id)

    logger.info(f"New user registered: phone={body.phone} id={user_id}")

    return TokenResponse(
        access_token=create_access_token(user_id),
        refresh_token=create_refresh_token(user_id),
        user_id=user_id,
    )


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, db: AsyncIOMotorDatabase = Depends(get_db)):
    """Authenticate user and return JWT tokens."""
    user = await db.users.find_one({"phone": body.phone})
    if not user or not verify_password(body.password, user["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid phone or password",
        )

    user_id = str(user["_id"])
    logger.info(f"User logged in: id={user_id}")

    return TokenResponse(
        access_token=create_access_token(user_id),
        refresh_token=create_refresh_token(user_id),
        user_id=user_id,
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(body: RefreshRequest):
    """Exchange a refresh token for a new access token."""
    payload = decode_token(body.refresh_token, token_type="refresh")
    user_id = payload["sub"]

    return TokenResponse(
        access_token=create_access_token(user_id),
        refresh_token=create_refresh_token(user_id),  # rotate refresh token
        user_id=user_id,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(user_id: str = Depends(get_current_user_id)):
    """
    Logout endpoint.
    JWTs are stateless — true invalidation requires a token blacklist in Redis.
    For simplicity, clients delete tokens locally. Production: add Redis blacklist.
    """
    logger.info(f"User logged out: id={user_id}")
    return None