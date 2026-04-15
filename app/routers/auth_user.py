from fastapi import APIRouter, HTTPException, status, Depends, UploadFile, File
from app.models.user import (
    UserCreate, UserOut, Token, LoginRequest,
    UserUpdate, UserUpdateResponse, VerifyOTPRequest, ResendOTPRequest,
    ForgotPasswordRequest, ResetPasswordRequest,
    get_user_by_email, get_user_by_id, create_user, update_user, convert_dates
)
from app.utils.password import hash_password, verify_password
from app.utils.tokens import create_access_token
from app.utils.auth_middleware import require_auth, get_current_user_id
from app.utils.cloudinary_helper import upload_profile_picture, delete_profile_picture, extract_public_id_from_url
from app.utils.email_service import email_service
from app.db.database import db
from datetime import datetime, timedelta
import logging, secrets

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/auth", tags=["User Auth"])


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def register(user: UserCreate):
    """Register a new user account — sends OTP, stores in temp_users."""
    existing = await get_user_by_email(user.email)
    if existing:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered")

    otp_code = str(secrets.randbelow(900000) + 100000)
    otp_expires_at = datetime.utcnow() + timedelta(minutes=10)

    user_dict = user.dict()
    user_dict = convert_dates(user_dict)
    user_dict["password"] = hash_password(user.password)
    user_dict["status"] = "pending"
    user_dict["role"] = "user"
    user_dict["otp_code"] = otp_code
    user_dict["otp_expires_at"] = otp_expires_at
    user_dict["last_sent_at"] = datetime.utcnow()
    user_dict["resend_count"] = 0
    user_dict["created_at"] = datetime.utcnow()
    user_dict = {k: v for k, v in user_dict.items() if v is not None}

    await db.temp_users.update_one({"email": user.email.lower()}, {"$set": user_dict}, upsert=True)
    await email_service.send_otp(user.email, otp_code)

    return UserOut(id="pending", email=user.email, username=user.username, role="user",
                   status="pending", created_at=user_dict["created_at"])


@router.post("/verify-otp")
async def verify_otp(request: VerifyOTPRequest):
    """Verify registration OTP and activate the account."""
    pending_user = await db.temp_users.find_one({"email": request.email.lower()})
    if not pending_user:
        existing = await get_user_by_email(request.email)
        if existing:
            return {"message": "Account is already active and verified", "status": "active"}
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Verification request not found. Please register again.")

    if pending_user.get("otp_code") != request.otp_code:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid verification code")
    if datetime.utcnow() > pending_user.get("otp_expires_at"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Verification code expired. Request a new one.")

    user_data = pending_user.copy()
    user_data.pop("_id", None)
    user_data.pop("otp_code", None)
    user_data.pop("otp_expires_at", None)
    user_data["status"] = "active"
    user_data["updated_at"] = datetime.utcnow()

    result = await create_user(user_data)
    await db.temp_users.delete_one({"email": request.email.lower()})
    return {"message": "Account verified and activated successfully", "user_id": str(result["_id"])}


@router.post("/resend-otp")
async def resend_otp(request: ResendOTPRequest):
    """Resend a new OTP code for a pending registration."""
    pending_user = await db.temp_users.find_one({"email": request.email.lower()})
    if not pending_user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Registration not found.")

    last_sent = pending_user.get("last_sent_at")
    if last_sent and (datetime.utcnow() - last_sent) < timedelta(seconds=60):
        seconds_left = 60 - int((datetime.utcnow() - last_sent).total_seconds())
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                            detail=f"Please wait {seconds_left} seconds before requesting a new code.")
    if pending_user.get("resend_count", 0) >= 3:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Maximum resend attempts reached.")

    otp_code = str(secrets.randbelow(900000) + 100000)
    otp_expires_at = datetime.utcnow() + timedelta(minutes=10)

    await db.temp_users.update_one({"email": request.email.lower()}, {
        "$set": {"otp_code": otp_code, "otp_expires_at": otp_expires_at, "last_sent_at": datetime.utcnow()},
        "$inc": {"resend_count": 1}
    })

    email_sent = await email_service.send_otp(request.email, otp_code)
    if not email_sent:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to send verification email.")
    return {"message": "New verification code sent successfully"}


@router.post("/forgot-password")
async def forgot_password(request: ForgotPasswordRequest):
    """Send OTP for password reset."""
    user = await get_user_by_email(request.email)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    otp_code = str(secrets.randbelow(900000) + 100000)
    otp_expires_at = datetime.utcnow() + timedelta(hours=1)

    await db.users.update_one({"email": request.email.lower()}, {
        "$set": {"reset_otp_code": otp_code, "reset_otp_expires_at": otp_expires_at}
    })
    email_sent = await email_service.send_password_reset_otp(request.email, otp_code)
    if not email_sent:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to send password reset email.")
    return {"message": "Password reset code sent to your email."}


@router.post("/reset-password")
async def reset_password(request: ResetPasswordRequest):
    """Reset password using the OTP code."""
    user = await get_user_by_email(request.email)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    stored_otp = user.get("reset_otp_code")
    expires_at = user.get("reset_otp_expires_at")

    if not stored_otp or stored_otp != request.otp_code:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid reset code")
    if not expires_at or datetime.utcnow() > expires_at:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Reset code has expired")

    await db.users.update_one({"email": request.email.lower()}, {
        "$set": {"password": hash_password(request.new_password), "updated_at": datetime.utcnow()},
        "$unset": {"reset_otp_code": "", "reset_otp_expires_at": ""}
    })
    return {"message": "Password has been reset successfully."}


@router.post("/login", response_model=Token)
async def login(login_data: LoginRequest):
    """Authenticate a mobile user and return access token."""
    user = await get_user_by_email(login_data.email)
    invalid = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials",
                            headers={"WWW-Authenticate": "Bearer"})

    if not user or not verify_password(login_data.password, user["password"]):
        raise invalid
    if user.get("role") not in ["user", "admin"]:
        raise invalid
    if user.get("status") == "pending":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Please verify your email before logging in.")
    if user.get("status") == "inactive":
        deactivation_type = user.get("deactivation_type")
        deactivation_end_date = user.get("deactivation_end_date")
        reason = user.get("deactivation_reason", "No reason provided")
        if deactivation_type == "temporary" and deactivation_end_date:
            if datetime.now() > deactivation_end_date:
                await update_user(str(user["_id"]), {"status": "active", "deactivation_type": None,
                                                      "deactivation_reason": None, "deactivation_end_date": None})
            else:
                days = (deactivation_end_date - datetime.now()).days
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                                    detail=f"Account temporarily deactivated. {'Available in ' + str(days) + ' days' if days > 0 else 'Available soon'}. Reason: {reason}")
        else:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Account deactivated: {reason}")

    access_token = create_access_token(str(user["_id"]), role=user.get("role", "user"))
    return Token(
        access_token=access_token,
        refresh_token="",
        token_type="bearer",
        user={
            "_id": str(user["_id"]), "email": user["email"],
            "username": user.get("username"), "role": user.get("role", "user"),
            "profile_pic": user.get("profile_pic"), "birthdate": user.get("birthdate"),
            "gender": user.get("gender"), "status": user.get("status", "active")
        }
    )


@router.post("/logout", dependencies=[Depends(require_auth)])
async def logout(user_id: str = Depends(get_current_user_id)):
    logger.info(f"User {user_id} logged out")
    return {"message": "Logged out successfully"}


@router.get("/me", response_model=UserOut, dependencies=[Depends(require_auth)])
async def get_me(user_id: str = Depends(get_current_user_id)):
    user = await get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return UserOut(id=str(user["_id"]), email=user["email"], username=user.get("username"),
                   role=user.get("role"), profile_pic=user.get("profile_pic"),
                   birthdate=user.get("birthdate"), gender=user.get("gender"),
                   status=user.get("status", "active"), created_at=user.get("created_at"),
                   updated_at=user.get("updated_at"))


@router.put("/profile", response_model=UserUpdateResponse, dependencies=[Depends(require_auth)])
async def update_profile(profile_data: UserUpdate, user_id: str = Depends(get_current_user_id)):
    user = await get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    update_data = profile_data.dict(exclude_unset=True)
    if not update_data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No data provided")
    updated_user = await update_user(user_id, update_data)
    if not updated_user:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to update profile")
    return UserUpdateResponse(id=str(updated_user["_id"]), email=updated_user["email"],
                              username=updated_user.get("username"), role=updated_user.get("role"),
                              profile_pic=updated_user.get("profile_pic"), birthdate=updated_user.get("birthdate"),
                              gender=updated_user.get("gender"), message="Profile updated successfully")


@router.post("/profile/picture", response_model=UserUpdateResponse, dependencies=[Depends(require_auth)])
async def upload_profile_pic(file: UploadFile = File(...), user_id: str = Depends(get_current_user_id)):
    user = await get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    old_public_id = extract_public_id_from_url(user["profile_pic"]) if user.get("profile_pic") else None
    upload_result = await upload_profile_picture(file, user_id, old_public_id)
    updated_user = await update_user(user_id, {"profile_pic": upload_result["secure_url"]})
    return UserUpdateResponse(id=str(updated_user["_id"]), email=updated_user["email"],
                              username=updated_user.get("username"), role=updated_user.get("role"),
                              profile_pic=updated_user.get("profile_pic"), birthdate=updated_user.get("birthdate"),
                              gender=updated_user.get("gender"), message="Profile picture updated successfully")


@router.delete("/profile/picture", dependencies=[Depends(require_auth)])
async def delete_profile_pic(user_id: str = Depends(get_current_user_id)):
    user = await get_user_by_id(user_id)
    if not user or not user.get("profile_pic"):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No profile picture to delete")
    old_public_id = extract_public_id_from_url(user["profile_pic"])
    if old_public_id:
        await delete_profile_picture(old_public_id)
    await update_user(user_id, {"profile_pic": None})
    return {"message": "Profile picture deleted successfully"}
