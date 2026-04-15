from jose import JWTError, jwt
from datetime import datetime, timedelta
import os
from typing import Optional
import logging

logger = logging.getLogger(__name__)

SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY:
    raise ValueError("SECRET_KEY environment variable must be set")

ACCESS_TOKEN_EXPIRE_HOURS = int(os.getenv("ACCESS_TOKEN_EXPIRE_HOURS", 24))


def create_access_token(user_id: str, role: str = "user", expires_delta: Optional[timedelta] = None) -> str:
    """Create JWT access token. Role is embedded so guards don't need extra DB calls."""
    if expires_delta is None:
        expires_delta = timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)
    expire = datetime.utcnow() + expires_delta
    to_encode = {
        "sub": user_id,
        "role": role,
        "exp": expire,
        "iat": datetime.utcnow(),
        "type": "access"
    }
    return jwt.encode(to_encode, SECRET_KEY, algorithm="HS256")


def decode_access_token(token: str) -> dict:
    """Decode and verify JWT access token. Raises ValueError on any failure."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        if payload.get("type") != "access":
            raise ValueError("Invalid token type")
        if "sub" not in payload:
            raise ValueError("Token missing user ID")
        exp_timestamp = payload.get("exp")
        if exp_timestamp and datetime.utcnow() > datetime.utcfromtimestamp(exp_timestamp):
            raise ValueError("Token expired")
        return payload
    except JWTError as e:
        raise ValueError(f"Invalid token: {str(e)}")


def get_user_id_from_token(token: str) -> Optional[str]:
    try:
        return decode_access_token(token).get("sub")
    except ValueError:
        return None
