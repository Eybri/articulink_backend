import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
import httpx
import os
from app.models.user import auto_reactivate_users

logger = logging.getLogger(__name__)


async def keep_alive():
    """Pings the backend and HF Space to prevent spin-down on free tiers."""
    backend_url = os.getenv("RENDER_EXTERNAL_URL") or os.getenv("APP_URL")
    hf_space_url = os.getenv("HF_SPACE_URL")
    
    async with httpx.AsyncClient() as client:
        # Ping Backend
        if backend_url:
            try:
                # Ensure it's just the base URL for health check
                url = backend_url.rstrip("/") + "/health"
                response = await client.get(url, timeout=10.0)
                logger.info(f"Pinged Backend ({url}): {response.status_code}")
            except Exception as e:
                logger.warning(f"Failed to ping Backend: {str(e)}")
        
        # Ping HF Space
        if hf_space_url:
            try:
                # Ping the health check on HF Space
                url = hf_space_url.replace("/transcribe", "/health")
                response = await client.get(url, timeout=10.0)
                logger.info(f"Pinged HF Space ({url}): {response.status_code}")
            except Exception as e:
                logger.warning(f"Failed to ping HF Space: {str(e)}")

def start_scheduler():
    """Start background scheduler for automation tasks."""
    try:
        scheduler = AsyncIOScheduler()
        
        # Job 1: Auto-reactivate users (Every hour)
        scheduler.add_job(
            auto_reactivate_users,
            trigger=IntervalTrigger(hours=1),
            id='auto_reactivate_users',
            replace_existing=True
        )
        
        # Job 2: Keep Alive (Every 10 minutes)
        # We use 10m to stay safely within Render's 15m idle window
        scheduler.add_job(
            keep_alive,
            trigger=IntervalTrigger(minutes=10),
            id='keep_alive_bot',
            replace_existing=True
        )
        
        scheduler.start()
        logger.info("✅ Background scheduler started (Auto-reactivate: 1h, Keep-Alive: 10m)")
    except Exception as e:
        logger.error(f"❌ Failed to start scheduler: {str(e)}")
