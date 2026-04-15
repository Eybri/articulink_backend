import cloudinary
import cloudinary.uploader
from fastapi import UploadFile, HTTPException, status
from typing import Optional, Dict
import logging

logger = logging.getLogger(__name__)

ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "gif", "webp"}
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB


async def validate_image(file: UploadFile, contents: bytes) -> None:
    if file.filename:
        extension = file.filename.split(".")[-1].lower()
        if extension not in ALLOWED_EXTENSIONS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid file type. Allowed: {', '.join(ALLOWED_EXTENSIONS)}"
            )
    if len(contents) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File size exceeds 5MB limit"
        )


async def upload_profile_picture(
    file: UploadFile,
    user_id: str,
    old_public_id: Optional[str] = None
) -> Dict[str, str]:
    try:
        contents = await file.read()
        await validate_image(file, contents)

        if old_public_id:
            try:
                cloudinary.uploader.destroy(old_public_id)
            except Exception as e:
                logger.warning(f"Failed to delete old image: {e}")

        upload_result = cloudinary.uploader.upload(
            contents,
            folder=f"articuLink/profiles/{user_id}",
            transformation=[
                {"width": 500, "height": 500, "crop": "fill", "gravity": "face"},
                {"quality": "auto:good"},
                {"fetch_format": "auto"}
            ],
            resource_type="image"
        )
        return {
            "secure_url": upload_result["secure_url"],
            "public_id": upload_result["public_id"]
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Cloudinary upload error: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to upload image: {str(e)}"
        )


async def delete_profile_picture(public_id: str) -> bool:
    try:
        result = cloudinary.uploader.destroy(public_id)
        return result.get("result") == "ok"
    except Exception as e:
        logger.error(f"Failed to delete image: {e}")
        return False


def extract_public_id_from_url(url: str) -> Optional[str]:
    try:
        url_parts = url.split("/upload/")
        if len(url_parts) > 1:
            path_parts = url_parts[1].split("/", 1)
            if len(path_parts) > 1:
                return path_parts[1].rsplit(".", 1)[0]
    except Exception as e:
        logger.error(f"Failed to extract public_id: {str(e)}")
    return None
