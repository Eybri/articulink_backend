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

    class Config:
        from_attributes = True


def _fmt(clip: dict) -> dict:
    return {
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


@router.get("/audio-clips", response_model=List[AudioClipResponse], dependencies=[Depends(require_admin_auth)])
async def get_audio_clips(
    skip: int = 0,
    limit: int = 100,
    status: Optional[str] = None,
    language: Optional[str] = None
):
    query = {}
    if status:
        query["processing_status"] = status
    if language:
        query["language"] = language
    cursor = db.audio_clips.find(query).sort("created_at", -1).skip(skip).limit(limit)
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
