from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
import os
import logging
import cloudinary
import cloudinary.uploader
import cloudinary.api

from app.db.database import create_indexes
from app.scheduler import start_scheduler

# Routers
from app.routers.auth_user import router as auth_user_router
from app.routers.auth_admin import router as auth_admin_router
from app.routers.users import router as users_router
from app.routers.transcribe import router as transcribe_router
from app.routers.chat import router as chat_router
from app.routers.pronunciation import router as pronunciation_router
from app.routers.analysis import router as analysis_router
from app.routers.speech_stats import router as speech_stats_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="ArticuLink API",
    description="Unified backend for ArticuLink mobile app and admin dashboard",
    version="2.0.0"
)

# ── Cloudinary ────────────────────────────────────────────────────────────────
cloudinary.config(
    cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
    api_key=os.getenv("CLOUDINARY_API_KEY"),
    api_secret=os.getenv("CLOUDINARY_API_SECRET")
)

# ── CORS ──────────────────────────────────────────────────────────────────────
# Prioritize ALLOWED_ORIGINS from env, fallback to "*" for dev if missing
raw_origins = os.getenv("ALLOWED_ORIGINS", "")
if raw_origins:
    allowed_origins = [o.strip() for o in raw_origins.split(",") if o.strip()]
else:
    allowed_origins = ["*"] 

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── GZip compression ──────────────────────────────────────────────────────────
app.add_middleware(GZipMiddleware, minimum_size=1000)

# ── Routers ───────────────────────────────────────────────────────────────────
# Mobile user routes
app.include_router(auth_user_router)    # /api/auth/*
app.include_router(transcribe_router)   # /api/v1/transcribe, /api/v1/history
app.include_router(chat_router)         # /api/v1/chatbot/*
app.include_router(analysis_router)     # /analysis/*
app.include_router(speech_stats_router)  # /stats/speech

# Admin web routes
app.include_router(auth_admin_router)   # /api/admin/auth/*
app.include_router(users_router)        # /api/admin/users/*, /api/admin/dashboard/*
app.include_router(pronunciation_router) # /api/pronunciation/*

# ── Startup / Shutdown ────────────────────────────────────────────────────────
@app.on_event("startup")
async def startup_event():
    logger.info("🚀 Starting ArticuLink unified backend...")
    await create_indexes()
    start_scheduler()
    logger.info("✅ ArticuLink API is ready")


@app.on_event("shutdown")
async def shutdown_event():
    logger.info("🛑 ArticuLink API shutting down...")


# ── Health check ──────────────────────────────────────────────────────────────
@app.get("/")
async def root():
    return {"message": "ArticuLink API is running!", "version": "2.0.0"}


@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "ArticuLink Unified API"}


# ── Global Exception Handler ──────────────────────────────────────────────
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"❌ Global Error: {str(exc)}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal Server Error", "message": str(exc)}
    )
