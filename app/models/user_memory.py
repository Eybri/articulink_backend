from datetime import datetime
from app.db.database import db
from typing import Optional

async def get_user_memory(user_id: str) -> Optional[dict]:
    return await db.user_memory.find_one({"user_id": user_id})

async def create_or_update_memory(user_id: str, summary: str) -> dict:
    update_data = {
        "summary": summary,
        "updated_at": datetime.utcnow()
    }
    await db.user_memory.update_one(
        {"user_id": user_id},
        {"$set": update_data},
        upsert=True
    )
    return update_data
