from fastapi import APIRouter, HTTPException, Depends, status, UploadFile, File
from app.models.user import (
    UserOut, Token, LoginRequest, UserUpdate, UserUpdateResponse,
    get_user_by_email, get_user_by_id, update_user
)
from app.utils.password import verify_password, hash_password
from app.utils.tokens import create_access_token
from app.utils.auth_middleware import require_admin_auth, get_current_user_id
from app.utils.cloudinary_helper import upload_profile_picture, delete_profile_picture, extract_public_id_from_url
import logging

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/admin/auth", tags=["Admin Auth"])


@router.post("/login", response_model=Token)
async def admin_login(payload: LoginRequest):
    """Login for admin users only."""
    user = await get_user_by_email(payload.email)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    if user.get("role") != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    if not verify_password(payload.password, user["password"]):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    access_token = create_access_token(str(user["_id"]), role="admin")
    return Token(
        access_token=access_token,
        token_type="bearer",
        user={
            "id": str(user["_id"]), "email": user["email"],
            "username": user.get("username"), "role": "admin",
            "first_name": user.get("first_name"), "last_name": user.get("last_name"),
            "profile_pic": user.get("profile_pic"), "birthdate": user.get("birthdate"),
            "gender": user.get("gender")
        }
    )


@router.get("/me", dependencies=[Depends(require_admin_auth)])
async def get_admin_profile(user_id: str = Depends(get_current_user_id)):
    """Get current admin profile."""
    user = await get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if user.get("role") != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return {
        "id": str(user["_id"]), "email": user["email"],
        "username": user.get("username"), "role": user.get("role"),
        "first_name": user.get("first_name"), "last_name": user.get("last_name"),
        "profile_pic": user.get("profile_pic"), "birthdate": user.get("birthdate"),
        "gender": user.get("gender")
    }


@router.put("/profile", response_model=UserUpdateResponse, dependencies=[Depends(require_admin_auth)])
async def update_admin_profile(profile_data: UserUpdate, user_id: str = Depends(get_current_user_id)):
    """Update admin profile details."""
    user = await get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    update_data = profile_data.dict(exclude_none=True)
    if not update_data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No data provided for update")
    updated_user = await update_user(user_id, update_data)
    if not updated_user:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to update profile")
    return UserUpdateResponse(
        id=str(updated_user["_id"]), email=updated_user["email"],
        username=updated_user.get("username"), role=updated_user.get("role"),
        first_name=updated_user.get("first_name"), last_name=updated_user.get("last_name"),
        profile_pic=updated_user.get("profile_pic"), birthdate=updated_user.get("birthdate"),
        gender=updated_user.get("gender"), message="Profile updated successfully"
    )


@router.post("/profile/picture", response_model=UserUpdateResponse, dependencies=[Depends(require_admin_auth)])
async def upload_admin_profile_pic(file: UploadFile = File(...), user_id: str = Depends(get_current_user_id)):
    """Upload or update admin profile picture."""
    user = await get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    old_public_id = extract_public_id_from_url(user["profile_pic"]) if user.get("profile_pic") else None
    upload_result = await upload_profile_picture(file, user_id, old_public_id)
    updated_user = await update_user(user_id, {"profile_pic": upload_result["secure_url"]})
    return UserUpdateResponse(
        id=str(updated_user["_id"]), email=updated_user["email"],
        username=updated_user.get("username"), role=updated_user.get("role"),
        first_name=updated_user.get("first_name"), last_name=updated_user.get("last_name"),
        profile_pic=updated_user.get("profile_pic"), birthdate=updated_user.get("birthdate"),
        gender=updated_user.get("gender"), message="Profile picture updated successfully"
    )


@router.delete("/profile/picture", dependencies=[Depends(require_admin_auth)])
async def delete_admin_profile_pic(user_id: str = Depends(get_current_user_id)):
    """Delete admin profile picture."""
    user = await get_user_by_id(user_id)
    if not user or not user.get("profile_pic"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No profile picture to delete")
    old_public_id = extract_public_id_from_url(user["profile_pic"])
    if old_public_id:
        await delete_profile_picture(old_public_id)
    await update_user(user_id, {"profile_pic": None})
    return {"message": "Profile picture deleted successfully"}


@router.put("/change-password", dependencies=[Depends(require_admin_auth)])
async def change_password(password_data: dict, user_id: str = Depends(get_current_user_id)):
    """Change admin password."""
    if password_data.get("new_password") != password_data.get("confirm_password"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="New passwords do not match")
    user = await get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if not verify_password(password_data["current_password"], user["password"]):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Current password is incorrect")
    await update_user(user_id, {"password": hash_password(password_data["new_password"])})
    return {"message": "Password changed successfully"}
