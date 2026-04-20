from fastapi import APIRouter, Query, HTTPException, Depends, BackgroundTasks
from typing import List, Optional
from pydantic import BaseModel
from bson import ObjectId
from datetime import datetime, timedelta
from app.db.database import db
from app.utils.auth_middleware import require_admin_auth, get_current_user_id
from app.models.user import DeactivateRequest, auto_reactivate_users
from app.utils.email_admin import send_deactivation_email, send_activation_email
import logging

router = APIRouter(prefix="/api/admin", tags=["Admin Users"])
logger = logging.getLogger(__name__)


class UserOut(BaseModel):
    id: str
    email: str
    username: Optional[str] = None
    role: str
    profile_pic: Optional[str] = None
    birthdate: Optional[str] = None
    gender: Optional[str] = None
    status: str
    deactivation_reason: Optional[str] = None
    deactivation_type: Optional[str] = None
    deactivation_end_date: Optional[str] = None
    created_at: Optional[str] = None

    class Config:
        from_attributes = True


class UserListOut(BaseModel):
    users: List[UserOut]
    total: int


def fmt_dt(dt):
    if dt is None:
        return None
    if hasattr(dt, 'isoformat'):
        return dt.isoformat()
    return str(dt)


def user_to_dict(user: dict) -> dict:
    return {
        "id": str(user["_id"]),
        "email": user.get("email", ""),
        "username": user.get("username"),
        "role": user.get("role", "user"),
        "profile_pic": user.get("profile_pic"),
        "birthdate": fmt_dt(user.get("birthdate")),
        "gender": user.get("gender"),
        "status": user.get("status", "active"),
        "deactivation_reason": user.get("deactivation_reason"),
        "deactivation_type": user.get("deactivation_type"),
        "deactivation_end_date": fmt_dt(user.get("deactivation_end_date")),
        "created_at": fmt_dt(user.get("created_at")),
    }


# ── GET /api/admin/users/ ───────────────────────────────────────────────────
@router.get("/users/", response_model=UserListOut, dependencies=[Depends(require_admin_auth)])
async def get_all_users(
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=1000),
    role: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    search: Optional[str] = Query(None)
):
    await auto_reactivate_users()
    query = {}
    if role:
        query["role"] = role
    if status:
        query["status"] = status
    if search:
        search_q = {"$or": [
            {"username": {"$regex": search, "$options": "i"}},
            {"email": {"$regex": search, "$options": "i"}}
        ]}
        query = {"$and": [query, search_q]} if query else search_q

    total_count = await db.users.count_documents(query)
    cursor = db.users.find(query).skip(skip).limit(limit)
    users_list = await cursor.to_list(length=limit)
    return {"users": [user_to_dict(u) for u in users_list], "total": total_count}


# ── GET /api/admin/users/stats/count ───────────────────────────────────────
@router.get("/users/stats/count", dependencies=[Depends(require_admin_auth)])
async def get_user_stats():
    await auto_reactivate_users()
    return {
        "total_users": await db.users.count_documents({}),
        "by_role": {
            "admin": await db.users.count_documents({"role": "admin"}),
            "user": await db.users.count_documents({"role": "user"})
        },
        "by_status": {
            "active": await db.users.count_documents({"status": "active"}),
            "inactive": await db.users.count_documents({"status": "inactive"}),
            "pending": await db.users.count_documents({"status": "pending"})
        },
        "by_deactivation_type": {
            "temporary": await db.users.count_documents({"status": "inactive", "deactivation_type": "temporary"}),
            "permanent": await db.users.count_documents({"status": "inactive", "deactivation_type": "permanent"})
        }
    }


# ── PUT /api/admin/users/{id}/deactivate ────────────────────────────────────
@router.put("/users/{user_id}/deactivate", dependencies=[Depends(require_admin_auth)])
async def deactivate_user(user_id: str, deactivate_request: DeactivateRequest, background_tasks: BackgroundTasks):
    if deactivate_request.deactivation_type not in ["permanent", "temporary"]:
        raise HTTPException(status_code=400, detail="Deactivation type must be 'permanent' or 'temporary'")

    user = await db.users.find_one({"_id": ObjectId(user_id)})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    update_data = {
        "status": "inactive",
        "deactivation_type": deactivate_request.deactivation_type,
        "deactivation_reason": deactivate_request.deactivation_reason
    }
    end_date = None

    if deactivate_request.deactivation_type == "temporary":
        if not deactivate_request.duration or deactivate_request.duration not in ["1day", "1week", "1month", "1year"]:
            raise HTTPException(status_code=400, detail="Duration must be: 1day, 1week, 1month, or 1year")
        now = datetime.now()
        durations = {"1day": timedelta(days=1), "1week": timedelta(weeks=1),
                     "1month": timedelta(days=30), "1year": timedelta(days=365)}
        end_date = now + durations[deactivate_request.duration]
        update_data["deactivation_end_date"] = end_date

    await db.users.update_one({"_id": ObjectId(user_id)}, {"$set": update_data})
    updated_user = await db.users.find_one({"_id": ObjectId(user_id)})

    if updated_user and updated_user.get("email"):
        background_tasks.add_task(
            send_deactivation_email,
            email=updated_user["email"],
            username=updated_user.get("username", "User"),
            deactivation_type=deactivate_request.deactivation_type,
            reason=deactivate_request.deactivation_reason,
            end_date=end_date
        )

    msg = "User deactivated successfully"
    if deactivate_request.deactivation_type == "temporary":
        msg += f" until {end_date.strftime('%Y-%m-%d %H:%M:%S')}"
    return {"message": msg, "user_id": user_id, "user": user_to_dict(updated_user)}


# ── PUT /api/admin/users/{id}/activate ──────────────────────────────────────
@router.put("/users/{user_id}/activate", dependencies=[Depends(require_admin_auth)])
async def activate_user(user_id: str, background_tasks: BackgroundTasks):
    user = await db.users.find_one({"_id": ObjectId(user_id)})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    await db.users.update_one({"_id": ObjectId(user_id)}, {"$set": {
        "status": "active", "deactivation_type": None,
        "deactivation_reason": None, "deactivation_end_date": None
    }})
    updated_user = await db.users.find_one({"_id": ObjectId(user_id)})

    if updated_user and updated_user.get("email"):
        background_tasks.add_task(
            send_activation_email,
            email=updated_user["email"],
            username=updated_user.get("username", "User")
        )

    return {"message": "User activated successfully", "user_id": user_id, "user": user_to_dict(updated_user)}


# ── POST /api/admin/users/auto-reactivate ───────────────────────────────────
@router.post("/users/auto-reactivate", dependencies=[Depends(require_admin_auth)])
async def trigger_auto_reactivate():
    count = await auto_reactivate_users()
    return {"message": "Auto-reactivation completed", "reactivated_count": count}


# ── PUT /api/admin/users/{id}/status (legacy) ───────────────────────────────
@router.put("/users/{user_id}/status", dependencies=[Depends(require_admin_auth)])
async def update_user_status(
    user_id: str,
    status: str = Query(...),
    deactivation_reason: Optional[str] = Query(None)
):
    if status not in ["active", "inactive"]:
        raise HTTPException(status_code=400, detail="Status must be 'active' or 'inactive'")
    user = await db.users.find_one({"_id": ObjectId(user_id)})
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    update_data = {"status": status}
    if status == "inactive":
        update_data["deactivation_reason"] = deactivation_reason
        update_data["deactivation_type"] = "permanent"
    else:
        update_data.update({"deactivation_reason": None, "deactivation_type": None, "deactivation_end_date": None})

    await db.users.update_one({"_id": ObjectId(user_id)}, {"$set": update_data})
    updated_user = await db.users.find_one({"_id": ObjectId(user_id)})
    return {"message": f"User status updated to {status}", "user": user_to_dict(updated_user)}


# ── PUT /api/admin/users/bulk/status ────────────────────────────────────────
@router.put("/users/bulk/status", dependencies=[Depends(require_admin_auth)])
async def bulk_update_user_status(
    user_ids: List[str],
    status: str = Query(...),
    deactivation_reason: Optional[str] = Query(None)
):
    if status not in ["active", "inactive"]:
        raise HTTPException(status_code=400, detail="Status must be 'active' or 'inactive'")
    object_ids = [ObjectId(uid) for uid in user_ids]
    update_data = {"status": status}
    if status == "inactive":
        update_data["deactivation_reason"] = deactivation_reason
        update_data["deactivation_type"] = "permanent"
    else:
        update_data.update({"deactivation_reason": None, "deactivation_type": None, "deactivation_end_date": None})

    result = await db.users.update_many({"_id": {"$in": object_ids}}, {"$set": update_data})
    return {"message": f"Updated {result.modified_count} users to {status}", "modified_count": result.modified_count}


# ── Dashboard endpoints ──────────────────────────────────────────────────────
@router.get("/dashboard/gender-demographics", dependencies=[Depends(require_admin_auth)])
async def get_gender_demographics():
    await auto_reactivate_users()
    pipeline = [
        {"$group": {"_id": "$gender", "count": {"$sum": 1}}},
        {"$project": {"gender": {"$ifNull": ["$_id", "Not Specified"]}, "count": 1, "_id": 0}},
        {"$sort": {"count": -1}}
    ]
    gender_data = await db.users.aggregate(pipeline).to_list(length=100)
    total_users = await db.users.count_documents({})
    for item in gender_data:
        item["percentage"] = round((item["count"] / total_users) * 100, 2) if total_users > 0 else 0
    return {"total_users": total_users, "gender_distribution": gender_data}


@router.get("/dashboard/user-growth", dependencies=[Depends(require_admin_auth)])
async def get_user_growth(timeframe: str = Query("monthly")):
    date_format = {"daily": "%Y-%m-%d", "weekly": "%Y-%U"}.get(timeframe, "%Y-%m")
    pipeline = [
        {"$group": {"_id": {"$dateToString": {"format": date_format, "date": "$created_at"}},
                    "count": {"$sum": 1}, "date": {"$first": "$created_at"}}},
        {"$project": {"period": "$_id", "count": 1, "date": 1, "_id": 0}},
        {"$sort": {"date": 1}}
    ]
    growth_data = await db.users.aggregate(pipeline).to_list(length=1000)
    cumulative = 0
    for item in growth_data:
        cumulative += item["count"]
        item["cumulative"] = cumulative
    return {"timeframe": timeframe, "growth_data": growth_data, "total_periods": len(growth_data)}


@router.get("/dashboard/age-distribution", dependencies=[Depends(require_admin_auth)])
async def get_age_distribution():
    await auto_reactivate_users()
    users_with_birthdate = await db.users.find({"birthdate": {"$exists": True, "$ne": None}}).to_list(length=10000)
    age_ranges = {"Under 18": 0, "18-25": 0, "26-35": 0, "36-45": 0, "46-55": 0, "56-65": 0, "Over 65": 0}
    current_date = datetime.now()

    for user in users_with_birthdate:
        try:
            bd = user.get("birthdate")
            if isinstance(bd, str):
                bd = datetime.fromisoformat(bd.replace('Z', '+00:00'))
            age = current_date.year - bd.year
            if (current_date.month, current_date.day) < (bd.month, bd.day):
                age -= 1
            if age < 18: age_ranges["Under 18"] += 1
            elif age <= 25: age_ranges["18-25"] += 1
            elif age <= 35: age_ranges["26-35"] += 1
            elif age <= 45: age_ranges["36-45"] += 1
            elif age <= 55: age_ranges["46-55"] += 1
            elif age <= 65: age_ranges["56-65"] += 1
            else: age_ranges["Over 65"] += 1
        except Exception:
            continue

    total_with_bd = sum(age_ranges.values())
    distribution = [{"age_range": k, "count": v,
                     "percentage": round((v / total_with_bd) * 100, 2) if total_with_bd > 0 else 0}
                    for k, v in age_ranges.items()]
    return {
        "age_distribution": distribution,
        "total_users_with_birthdate": total_with_bd,
        "total_users": await db.users.count_documents({})
    }


@router.get("/dashboard/health", dependencies=[Depends(require_admin_auth)])
async def get_system_health():
    """
    Check health of core services and AI models.
    Returns status: 'optimal', 'degraded', or 'down'.
    """
    import os
    import httpx
    import asyncio

    health_results = {}
    overall_status = "optimal"

    # 1. MongoDB Health
    try:
        await db.command("ping")
        health_results["database"] = {"status": "connected", "latency": "low"}
    except Exception as e:
        health_results["database"] = {"status": "error", "detail": str(e)}
        overall_status = "down"

    # 2. Gemini Model Health
    gemini_key = os.getenv("GEMINI_API_KEY")
    if gemini_key and len(gemini_key) > 5:
        # We assume it's working if key is present to avoid API costs on health check
        health_results["gemini"] = {"status": "configured", "model": "gemini-2.5-flash"}
    else:
        health_results["gemini"] = {"status": "missing_config", "detail": "API Key not found"}
        if overall_status == "optimal": overall_status = "degraded"

    # 3. Whisper / Hugging Face Health
    hf_url = os.getenv("HF_SPACE_URL")
    if hf_url:
        try:
            # Quick HEAD request to check if space is up
            async with httpx.AsyncClient() as client:
                resp = await client.get(hf_url, timeout=5.0)
                if resp.status_code in [200, 405, 401]: # 405/401 might mean it's there but rejects empty GET
                    health_results["whisper"] = {"status": "online", "mode": "remote"}
                else:
                    health_results["whisper"] = {"status": "degraded", "detail": f"Status {resp.status_code}"}
                    if overall_status == "optimal": overall_status = "degraded"
        except Exception as e:
            health_results["whisper"] = {"status": "offline", "detail": str(e), "mode": "fallback_local"}
            if overall_status == "optimal": overall_status = "degraded"
    else:
        health_results["whisper"] = {"status": "local_only", "mode": "local"}

    # 4. Supabase Storage Health
    sb_url = os.getenv("SUPABASE_URL")
    sb_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if sb_url and sb_key:
        health_results["storage"] = {"status": "configured", "provider": "supabase"}
    else:
        health_results["storage"] = {"status": "missing_config"}
        if overall_status == "optimal": overall_status = "degraded"

    return {
        "status": overall_status,
        "timestamp": datetime.utcnow().isoformat(),
        "services": health_results
    }

@router.get("/dashboard/chat-activity", dependencies=[Depends(require_admin_auth)])
async def get_chat_activity(timeframe: str = Query("daily")):
    date_format = {"daily": "%Y-%m-%d", "weekly": "%Y-%U"}.get(timeframe, "%Y-%m")
    pipeline = [
        {"$match": {"timestamp": {"$exists": True, "$type": "string"}}},
        {"$project": {
            "date": {"$dateFromString": {"dateString": "$timestamp", "onError": datetime.utcnow()}}
        }},
        {"$group": {
            "_id": {"$dateToString": {"format": date_format, "date": "$date"}},
            "count": {"$sum": 1},
            "raw_date": {"$first": "$date"}
        }},
        {"$project": {"period": "$_id", "count": 1, "raw_date": 1, "_id": 0}},
        {"$sort": {"raw_date": 1}}
    ]
    activity_data = await db.chat_history.aggregate(pipeline).to_list(length=1000)
    return {"timeframe": timeframe, "activity": activity_data}


@router.get("/dashboard/platform-engagement", dependencies=[Depends(require_admin_auth)])
async def get_platform_engagement(timeframe: str = Query("daily")):
    date_format = {"daily": "%Y-%m-%d", "weekly": "%Y-%U"}.get(timeframe, "%Y-%m")
    
    # Aggregate chats
    chat_pipeline = [
        {"$match": {"timestamp": {"$exists": True, "$type": "string"}}},
        {"$project": {"date": {"$dateFromString": {"dateString": "$timestamp", "onError": datetime.utcnow()}}}},
        {"$group": {"_id": {"$dateToString": {"format": date_format, "date": "$date"}}, "chat_count": {"$sum": 1}}}
    ]
    chat_results = await db.chat_history.aggregate(chat_pipeline).to_list(length=1000)
    
    # Aggregate audio
    audio_pipeline = [
        {"$match": {"created_at": {"$exists": True}}},
        {"$project": {
            "date": {
                "$cond": {
                    "if": {"$eq": [{"$type": "$created_at"}, "string"]},
                    "then": {"$dateFromString": {"dateString": "$created_at", "onError": datetime.utcnow()}},
                    "else": "$created_at"
                }
            }
        }},
        {"$group": {"_id": {"$dateToString": {"format": date_format, "date": "$date"}}, "audio_count": {"$sum": 1}}}
    ]
    audio_results = await db.audio_clips.aggregate(audio_pipeline).to_list(length=1000)
    
    # Merge results
    engagement_map = {}
    for r in chat_results:
        engagement_map[r["_id"]] = {"period": r["_id"], "chat_count": r["chat_count"], "audio_count": 0}
    for r in audio_results:
        if r["_id"] in engagement_map:
            engagement_map[r["_id"]]["audio_count"] = r["audio_count"]
        else:
            engagement_map[r["_id"]] = {"period": r["_id"], "chat_count": 0, "audio_count": r["audio_count"]}
            
    sorted_engagement = sorted(engagement_map.values(), key=lambda x: x["period"])
    return {"timeframe": timeframe, "engagement": sorted_engagement}


@router.get("/dashboard/chat-roles", dependencies=[Depends(require_admin_auth)])
async def get_chat_roles():
    pipeline = [
        {"$group": {"_id": "$role", "count": {"$sum": 1}}},
        {"$project": {"role": "$_id", "count": 1, "_id": 0}}
    ]
    data = await db.chat_history.aggregate(pipeline).to_list(length=10)
    return {"roles": data}


@router.get("/dashboard/audio-growth", dependencies=[Depends(require_admin_auth)])
async def get_audio_growth(timeframe: str = Query("daily")):
    date_format = {"daily": "%Y-%m-%d", "weekly": "%Y-%U"}.get(timeframe, "%Y-%m")
    pipeline = [
        {"$match": {"created_at": {"$exists": True}}},
        {"$project": {
            "date": {
                "$cond": {
                    "if": {"$eq": [{"$type": "$created_at"}, "string"]},
                    "then": {"$dateFromString": {"dateString": "$created_at", "onError": datetime.utcnow()}},
                    "else": "$created_at"
                }
            }
        }},
        {"$group": {
            "_id": {"$dateToString": {"format": date_format, "date": "$date"}},
            "count": {"$sum": 1},
            "raw_date": {"$first": "$date"}
        }},
        {"$project": {"period": "$_id", "count": 1, "raw_date": 1, "_id": 0}},
        {"$sort": {"raw_date": 1}}
    ]
    growth_data = await db.audio_clips.aggregate(pipeline).to_list(length=1000)
    return {"timeframe": timeframe, "growth": growth_data}


@router.get("/dashboard/user-status", dependencies=[Depends(require_admin_auth)])
async def get_user_status_dist():
    pipeline = [
        {"$group": {"_id": "$status", "count": {"$sum": 1}}},
        {"$project": {"status": "$_id", "count": 1, "_id": 0}}
    ]
    data = await db.users.aggregate(pipeline).to_list(length=10)
    return {"status_distribution": data}


@router.get("/dashboard/user-roles", dependencies=[Depends(require_admin_auth)])
async def get_user_role_dist():
    pipeline = [
        {"$group": {"_id": "$role", "count": {"$sum": 1}}},
        {"$project": {"role": "$_id", "count": 1, "_id": 0}}
    ]
    data = await db.users.aggregate(pipeline).to_list(length=10)
    return {"role_distribution": data}


@router.get("/dashboard/privacy-acceptance", dependencies=[Depends(require_admin_auth)])
async def get_privacy_acceptance():
    # Example logic: count users who finished onboarding vs those who didn't
    # or if you have a specific privacy_accepted field
    total = await db.users.count_documents({})
    accepted = await db.users.count_documents({"privacy_accepted": True})
    return {
        "total": total,
        "accepted": accepted,
        "pending": total - accepted
    }
