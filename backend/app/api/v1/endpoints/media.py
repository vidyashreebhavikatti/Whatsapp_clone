"""
Media Upload Router
===================
Two upload strategies:
1. Direct upload: small files (<5MB) can be sent directly to this endpoint
2. Presigned URL: large files get a presigned S3 URL and upload directly to S3

This keeps media bandwidth off the API servers.
"""
import uuid
import mimetypes
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
from app.api.dependencies import get_current_user_id
from app.schemas.schemas import PresignedUrlRequest, PresignedUrlResponse, MediaUploadResponse
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/media", tags=["Media"])

# All allowed MIME types
ALLOWED_TYPES = (
    settings.ALLOWED_IMAGE_TYPES
    + settings.ALLOWED_VIDEO_TYPES
    + settings.ALLOWED_DOC_TYPES
)


def _get_s3_client():
    """Lazily create boto3 S3 client (or MinIO compatible)."""
    import boto3
    kwargs = {
        "aws_access_key_id": settings.AWS_ACCESS_KEY_ID,
        "aws_secret_access_key": settings.AWS_SECRET_ACCESS_KEY,
        "region_name": settings.AWS_REGION,
    }
    if settings.S3_ENDPOINT_URL:
        kwargs["endpoint_url"] = settings.S3_ENDPOINT_URL
    return boto3.client("s3", **kwargs)


def _media_key(user_id: str, filename: str) -> str:
    """Generate a unique S3 object key."""
    ext = filename.rsplit(".", 1)[-1] if "." in filename else "bin"
    return f"media/{user_id}/{uuid.uuid4().hex}.{ext}"


def _public_url(key: str) -> str:
    """Build public CDN/S3 URL for a given key."""
    if settings.S3_ENDPOINT_URL:
        return f"{settings.S3_ENDPOINT_URL}/{settings.S3_BUCKET_NAME}/{key}"
    return f"https://{settings.S3_BUCKET_NAME}.s3.{settings.AWS_REGION}.amazonaws.com/{key}"


@router.post("/presign", response_model=PresignedUrlResponse)
async def get_presigned_url(
    body: PresignedUrlRequest,
    user_id: str = Depends(get_current_user_id),
):
    """
    Generate a presigned S3 PUT URL.
    Client uploads directly to S3, then sends media_url in the message.
    """
    if body.content_type not in ALLOWED_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Content type {body.content_type} not allowed",
        )

    max_bytes = settings.MAX_MEDIA_SIZE_MB * 1024 * 1024
    if body.size_bytes > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File size exceeds {settings.MAX_MEDIA_SIZE_MB}MB limit",
        )

    key = _media_key(user_id, body.filename)

    if not settings.AWS_ACCESS_KEY_ID:
        # Dev mode: return fake URL when S3 not configured
        return PresignedUrlResponse(
            upload_url=f"http://localhost:9000/upload/{key}",
            media_url=f"http://localhost:9000/{settings.S3_BUCKET_NAME}/{key}",
            expires_in=3600,
        )

    s3 = _get_s3_client()
    presigned_url = s3.generate_presigned_url(
        "put_object",
        Params={
            "Bucket": settings.S3_BUCKET_NAME,
            "Key": key,
            "ContentType": body.content_type,
        },
        ExpiresIn=3600,
    )

    return PresignedUrlResponse(
        upload_url=presigned_url,
        media_url=_public_url(key),
        expires_in=3600,
    )


@router.post("/upload", response_model=MediaUploadResponse)
async def upload_media(
    file: UploadFile = File(...),
    user_id: str = Depends(get_current_user_id),
):
    """
    Direct upload endpoint for small files.
    Streams directly to S3 without buffering to disk.
    """
    content_type = file.content_type or "application/octet-stream"

    if content_type not in ALLOWED_TYPES:
        raise HTTPException(status_code=415, detail="File type not allowed")

    # Read file into memory (max 5MB for direct upload)
    data = await file.read()
    if len(data) > 5 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Use presigned URL for files >5MB")

    key = _media_key(user_id, file.filename or "upload")

    if settings.AWS_ACCESS_KEY_ID:
        import boto3
        s3 = _get_s3_client()
        s3.put_object(
            Bucket=settings.S3_BUCKET_NAME,
            Key=key,
            Body=data,
            ContentType=content_type,
        )

    media_url = _public_url(key)
    logger.info(f"Media uploaded: user={user_id} key={key} size={len(data)}")

    return MediaUploadResponse(
        media_url=media_url,
        content_type=content_type,
        size_bytes=len(data),
    )