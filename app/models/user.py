from pydantic import BaseModel, EmailStr, Field
from typing import List, Optional, Any
from datetime import datetime, timedelta
from bson import ObjectId
from app.db.database import db
import logging

logger = logging.getLogger(__name__)

# --- Pydantic Models ---

class LoginRequest(BaseModel):
    email: str
    password: str

class Token(BaseModel):
    access_token: str
    token_type: str
    user: Optional[dict] = None
    refresh_token: Optional[str] = ""

class UserCreate(BaseModel):
    email: str
    username: str
    password: str
    birthdate: Optional[str] = None
    gender: Optional[str] = None

class UserOut(BaseModel):
    id: str
    email: str
    username: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    role: str
    status: str
    profile_pic: Optional[str] = None
    birthdate: Optional[Any] = None
    gender: Optional[str] = None
    privacy_accepted: Optional[bool] = False
    created_at: Optional[Any] = None
    updated_at: Optional[Any] = None

    class Config:
        from_attributes = True

class UserUpdate(BaseModel):
    username: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    profile_pic: Optional[str] = None
    birthdate: Optional[str] = None
    gender: Optional[str] = None
    privacy_accepted: Optional[bool] = None

class UserUpdateResponse(BaseModel):
    id: str
    email: str
    username: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    role: str
    profile_pic: Optional[str] = None
    birthdate: Optional[Any] = None
    gender: Optional[str] = None
    privacy_accepted: Optional[bool] = False
    message: str

class VerifyOTPRequest(BaseModel):
    email: str
    otp_code: str

class ResendOTPRequest(BaseModel):
    email: str

class ForgotPasswordRequest(BaseModel):
    email: str

class ResetPasswordRequest(BaseModel):
    email: str
    otp_code: str
    new_password: str

class DeactivateRequest(BaseModel):
    deactivation_type: str  # "permanent" or "temporary"
    deactivation_reason: Optional[str] = None
    duration: Optional[str] = None # "1day", "1week", "1month", "1year"

# --- DB Helper Functions ---

async def get_user_by_email(email: str) -> Optional[dict]:
    return await db.users.find_one({"email": email.lower()})

async def get_user_by_id(user_id: str) -> Optional[dict]:
    try:
        return await db.users.find_one({"_id": ObjectId(user_id)})
    except Exception:
        return None

async def create_user(user_data: dict) -> dict:
    if "created_at" not in user_data:
        user_data["created_at"] = datetime.utcnow()
    result = await db.users.insert_one(user_data)
    user_data["_id"] = result.inserted_id
    return user_data

async def update_user(user_id: str, update_data: dict) -> Optional[dict]:
    try:
        update_data["updated_at"] = datetime.utcnow()
        await db.users.update_one({"_id": ObjectId(user_id)}, {"$set": update_data})
        return await db.users.find_one({"_id": ObjectId(user_id)})
    except Exception:
        return None

def convert_dates(user_dict: dict) -> dict:
    """Helper to convert date strings to datetime objects if needed."""
    if user_dict.get("birthdate") and isinstance(user_dict["birthdate"], str):
        try:
            user_dict["birthdate"] = datetime.fromisoformat(user_dict["birthdate"].replace('Z', '+00:00'))
        except ValueError:
            pass
    return user_dict

async def auto_reactivate_users() -> int:
    """
    Checks for temporarily deactivated users whose deactivation period has ended
    and reactivates them. Returns count of reactivated users.
    """
    now = datetime.now()
    query = {
        "status": "inactive",
        "deactivation_type": "temporary",
        "deactivation_end_date": {"$lte": now}
    }
    
    cursor = db.users.find(query)
    expired_users = await cursor.to_list(length=1000)
    
    if not expired_users:
        return 0
        
    user_ids = [u["_id"] for u in expired_users]
    result = await db.users.update_many(
        {"_id": {"$in": user_ids}},
        {"$set": {
            "status": "active",
            "deactivation_type": None,
            "deactivation_reason": None,
            "deactivation_end_date": None
        }}
    )
    
    if result.modified_count > 0:
        logger.info(f"🔄 Auto-reactivated {result.modified_count} users")
        
    return result.modified_count
