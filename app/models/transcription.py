from bson import ObjectId
from datetime import datetime
from app.db.database import db
from typing import List, Optional

async def create_audio_clip(clip_data: dict) -> dict:
    if "created_at" not in clip_data:
        clip_data["created_at"] = datetime.utcnow()
    
    # Ensure user_id is stored appropriately (sometimes as string, sometimes as ObjectId)
    # Most endpoints seem to use string for user_id in filters, but some might prefer ObjectId.
    # We'll store it as provided.
    
    result = await db.audio_clips.insert_one(clip_data)
    clip_data["id"] = str(result.inserted_id)
    if "_id" in clip_data:
        clip_data.pop("_id")
    return clip_data

async def get_clips_by_user(user_id: str, skip: int = 0, limit: int = 50) -> List[dict]:
    cursor = db.audio_clips.find({"user_id": user_id}).sort("created_at", -1).skip(skip).limit(limit)
    clips = await cursor.to_list(length=limit)
    for clip in clips:
        clip["id"] = str(clip["_id"])
        clip.pop("_id")
        if clip.get("created_at") and hasattr(clip["created_at"], "isoformat"):
            clip["created_at"] = clip["created_at"].isoformat()
    return clips

async def delete_audio_clip(clip_id: str) -> bool:
    try:
        result = await db.audio_clips.delete_one({"_id": ObjectId(clip_id)})
        return result.deleted_count > 0
    except Exception:
        return False
