import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from app.models.user import auto_reactivate_users

logger = logging.getLogger(__name__)


def start_scheduler():
    """Start background scheduler for auto-reactivation of temporarily deactivated users."""
    try:
        scheduler = AsyncIOScheduler()
        scheduler.add_job(
            auto_reactivate_users,
            trigger=IntervalTrigger(hours=1),
            id='auto_reactivate_users',
            replace_existing=True
        )
        scheduler.start()
        logger.info("✅ Auto-reactivation scheduler started — runs every hour")
    except Exception as e:
        logger.error(f"❌ Failed to start scheduler: {str(e)}")
