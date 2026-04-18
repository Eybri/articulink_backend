from bson import ObjectId
from datetime import datetime
from app.db.database import db
from typing import List, Optional

async def save_chat_message(user_id: str, role: str, content: str) -> dict:
    msg = {
        "user_id": user_id,
        "role": role,
        "content": content,
        "timestamp": datetime.utcnow().isoformat()
    }
    await db.chat_history.insert_one(msg)
    return msg

async def get_chat_history(user_id: str, limit: int = 50) -> List[dict]:
    cursor = db.chat_history.find({"user_id": user_id}).sort("timestamp", -1).limit(limit)
    messages = await cursor.to_list(length=limit)
    # Reverse to get chronological order for the UI
    messages.reverse()
    for msg in messages:
        if "_id" in msg:
            msg.pop("_id")
    return messages

async def delete_chat_history(user_id: str) -> int:
    result = await db.chat_history.delete_many({"user_id": user_id})
    return result.deleted_count

async def delete_specific_message(user_id: str, timestamp: str) -> bool:
    result = await db.chat_history.delete_one({"user_id": user_id, "timestamp": timestamp})
    return result.deleted_count > 0
