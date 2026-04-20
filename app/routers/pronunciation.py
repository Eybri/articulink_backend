from fastapi import APIRouter, HTTPException, Depends, Query
from typing import List, Optional
from pydantic import BaseModel
from bson import ObjectId
from datetime import datetime
from app.db.database import db
from app.utils.auth_middleware import require_admin_auth, get_current_user_id
import logging

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/pronunciation", tags=["Pronunciation"])


class UserInfo(BaseModel):
    username: Optional[str] = None
    email: Optional[str] = None
    profile_pic: Optional[str] = None

class AudioClipResponse(BaseModel):
    id: str
    user_id: str
    audio_url: str
    transcript: Optional[str] = None
    corrected_transcript: Optional[str] = None
    speech_type: Optional[str] = None
    duration_seconds: Optional[float] = None
    processing_status: str
    device_type: Optional[str] = None
    language: Optional[str] = None
    created_at: Optional[str] = None
    user_info: Optional[UserInfo] = None

    class Config:
        from_attributes = True


def _fmt(clip: dict) -> dict:
    res = {
        "id": str(clip["_id"]),
        "user_id": str(clip.get("user_id", "")),
        "audio_url": clip.get("audio_url", ""),
        "transcript": clip.get("transcript"),
        "corrected_transcript": clip.get("corrected_transcript"),
        "speech_type": clip.get("speech_type"),
        "duration_seconds": clip.get("duration_seconds"),
        "processing_status": clip.get("processing_status", "unknown"),
        "device_type": clip.get("device_type"),
        "language": clip.get("language"),
        "created_at": clip.get("created_at").isoformat() if clip.get("created_at") else None
    }
    
    # Handle user_info from aggregation
    if "user_info" in clip and clip["user_info"]:
        user = clip["user_info"]
        res["user_info"] = {
            "username": user.get("username"),
            "email": user.get("email"),
            "profile_pic": user.get("profile_pic")
        }
    elif "user_details" in clip and clip["user_details"]:
        # Handle cases where $lookup returns a list
        user = clip["user_details"][0] if clip["user_details"] else {}
        res["user_info"] = {
            "username": user.get("username"),
            "email": user.get("email"),
            "profile_pic": user.get("profile_pic")
        }
        
    return res


@router.get("/audio-clips", response_model=List[AudioClipResponse], dependencies=[Depends(require_admin_auth)])
async def get_audio_clips(
    skip: int = 0,
    limit: int = 100,
    status: Optional[str] = None,
    language: Optional[str] = None
):
    match_stage = {}
    if status:
        match_stage["processing_status"] = status
    if language:
        match_stage["language"] = language

    pipeline = [
        {"$match": match_stage},
        {"$sort": {"created_at": -1}},
        {"$skip": skip},
        {"$limit": limit},
        {
            "$addFields": {
                "user_obj_id": {
                    "$cond": {
                        "if": {"$eq": [{"$type": "$user_id"}, "string"]},
                        "then": {"$toObjectId": "$user_id"},
                        "else": "$user_id"
                    }
                }
            }
        },
        {
            "$lookup": {
                "from": "users",
                "localField": "user_obj_id",
                "foreignField": "_id",
                "as": "user_details"
            }
        },
        {
            "$project": {
                "user_obj_id": 0
            }
        }
    ]
    
    cursor = db.audio_clips.aggregate(pipeline)
    clips = await cursor.to_list(length=limit)
    return [_fmt(c) for c in clips]


@router.get("/audio-clips/{clip_id}", response_model=AudioClipResponse, dependencies=[Depends(require_admin_auth)])
async def get_audio_clip(clip_id: str):
    clip = await db.audio_clips.find_one({"_id": ObjectId(clip_id)})
    if not clip:
        raise HTTPException(status_code=404, detail="Audio clip not found")
    return _fmt(clip)


@router.delete("/audio-clips/{clip_id}", dependencies=[Depends(require_admin_auth)])
async def delete_audio_clip_admin(clip_id: str):
    result = await db.audio_clips.delete_one({"_id": ObjectId(clip_id)})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Audio clip not found")
    return {"message": "Audio clip deleted successfully"}
