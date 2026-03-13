"""
WhatsApp Clone — FastAPI Application
=====================================
Production-grade real-time messaging backend.

Startup sequence:
1. Initialize logging
2. Connect to MongoDB (Motor async driver)
3. Connect to Redis
4. Start Redis Pub/Sub subscriber (background task)
5. Register all routers
6. Configure CORS and middleware
"""
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.logging import setup_logging, get_logger
from app.db.database import connect_db, close_db
from app.db.redis import connect_redis, close_redis
from app.websocket.manager import manager
from app.websocket.router import router as ws_router
from app.api.v1.endpoints.auth import router as auth_router
from app.api.v1.endpoints.users import router as users_router
from app.api.v1.endpoints.chats import router as chats_router
from app.api.v1.endpoints.messages import router as messages_router
from app.api.v1.endpoints.media import router as media_router

setup_logging()
logger = get_logger(__name__)

# Track background tasks so we can cancel on shutdown
_background_tasks: list[asyncio.Task] = []


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Manage application startup and shutdown.
    Using asynccontextmanager pattern (FastAPI v0.93+).
    """
    # ── Startup ──────────────────────────────────────────────────────
    logger.info(f"Starting {settings.APP_NAME} v{settings.APP_VERSION}")

    await connect_db()
    await connect_redis()

    # Start Redis Pub/Sub subscriber as background task
    sub_task = asyncio.create_task(
        manager.start_redis_subscriber(),
        name="redis_subscriber",
    )
    _background_tasks.append(sub_task)

    logger.info("Application started successfully")

    yield  # Application runs here

    # ── Shutdown ─────────────────────────────────────────────────────
    logger.info("Shutting down...")

    for task in _background_tasks:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    await close_redis()
    await close_db()

    logger.info("Application shutdown complete")


# ── Application instance ──────────────────────────────────────────────────────

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="Production-grade WhatsApp Web clone with real-time WebSocket messaging",
    lifespan=lifespan,
    # Disable docs in production
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url="/redoc" if settings.DEBUG else None,
)


# ── Middleware ────────────────────────────────────────────────────────────────

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log all HTTP requests with method, path, and status code."""
    response = await call_next(request)
    logger.info(f"{request.method} {request.url.path} → {response.status_code}")
    return response


# ── Global exception handlers ─────────────────────────────────────────────────

@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Catch-all for unhandled exceptions — never leak stack traces to clients."""
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Internal server error"},
    )


# ── Routers ───────────────────────────────────────────────────────────────────

API_PREFIX = "/api/v1"

app.include_router(auth_router, prefix=API_PREFIX)
app.include_router(users_router, prefix=API_PREFIX)
app.include_router(chats_router, prefix=API_PREFIX)
app.include_router(messages_router, prefix=API_PREFIX)
app.include_router(media_router, prefix=API_PREFIX)

# WebSocket router (no prefix — WS uses /ws/{user_id})
app.include_router(ws_router)


# ── Health check ──────────────────────────────────────────────────────────────

@app.get("/health", tags=["Health"])
async def health_check():
    """
    Health check endpoint.
    Used by load balancers to verify instance is alive.
    """
    return {
        "status": "healthy",
        "version": settings.APP_VERSION,
        "service": settings.APP_NAME,
    }


@app.get("/", tags=["Root"])
async def root():
    return {"message": f"Welcome to {settings.APP_NAME} API"}