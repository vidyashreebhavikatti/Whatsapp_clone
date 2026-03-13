from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    # Application
    APP_NAME: str = "WhatsApp Clone"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    SECRET_KEY: str = "CHANGE_ME_IN_PRODUCTION_USE_OPENSSL_RAND_HEX_32"
    
    # JWT
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24        # 24 hours
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30

    # MongoDB
    MONGODB_URL: str = "mongodb://localhost:27017"
    MONGODB_DB_NAME: str = "whatsapp_clone"

    # Redis
    REDIS_URL: str = "redis://localhost:6379"
    REDIS_PRESENCE_TTL: int = 35          # seconds — slightly > heartbeat interval
    REDIS_HEARTBEAT_INTERVAL: int = 15    # client sends ping every 15s

    # CORS
    ALLOWED_ORIGINS: list[str] = ["http://localhost:3000", "http://localhost:5173"]

    # Media Storage (S3-compatible)
    AWS_ACCESS_KEY_ID: Optional[str] = None
    AWS_SECRET_ACCESS_KEY: Optional[str] = None
    AWS_REGION: str = "us-east-1"
    S3_BUCKET_NAME: str = "whatsapp-clone-media"
    S3_ENDPOINT_URL: Optional[str] = None   # Set for MinIO local dev

    # Media limits
    MAX_MEDIA_SIZE_MB: int = 64
    ALLOWED_IMAGE_TYPES: list[str] = ["image/jpeg", "image/png", "image/webp", "image/gif"]
    ALLOWED_VIDEO_TYPES: list[str] = ["video/mp4", "video/webm"]
    ALLOWED_DOC_TYPES: list[str] = ["application/pdf", "text/plain"]

    # Pagination
    DEFAULT_PAGE_SIZE: int = 50
    MAX_PAGE_SIZE: int = 100

    # Rate Limiting
    RATE_LIMIT_PER_MINUTE: int = 60

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()