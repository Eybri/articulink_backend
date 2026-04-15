from fastapi import Request, HTTPException, status, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.utils import tokens
from app.models.user import get_user_by_id
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class JWTBearer(HTTPBearer):
    def __init__(self, auto_error: bool = True, optional: bool = False, require_admin: bool = False):
        super().__init__(auto_error=auto_error)
        self.optional = optional
        self.require_admin = require_admin

    async def __call__(self, request: Request):
        try:
            credentials: HTTPAuthorizationCredentials = await super().__call__(request)
            if credentials:
                if credentials.scheme != "Bearer":
                    if self.optional:
                        request.state.user_id = None
                        return None
                    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid authentication scheme.")

                payload = tokens.decode_access_token(credentials.credentials)
                if payload.get("type") != "access":
                    if self.optional:
                        request.state.user_id = None
                        return None
                    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid token type")

                user_id = payload.get("sub")
                user = await get_user_by_id(user_id)
                if not user:
                    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

                # Admin role check
                if self.require_admin and user.get("role") != "admin":
                    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")

                # Deactivation check
                if user.get("status") == "inactive":
                    deactivation_type = user.get("deactivation_type")
                    deactivation_end_date = user.get("deactivation_end_date")
                    if deactivation_type == "temporary" and deactivation_end_date:
                        if datetime.now() > deactivation_end_date:
                            from app.models.user import update_user
                            await update_user(user_id, {
                                "status": "active",
                                "deactivation_type": None,
                                "deactivation_reason": None,
                                "deactivation_end_date": None
                            })
                            logger.info(f"Auto-reactivated user {user_id}")
                        else:
                            remaining = deactivation_end_date - datetime.now()
                            days = remaining.days
                            raise HTTPException(
                                status_code=status.HTTP_403_FORBIDDEN,
                                detail=f"Account temporarily deactivated. {'Available in ' + str(days) + ' days' if days > 0 else 'Available soon'}."
                            )
                    else:
                        reason = user.get("deactivation_reason", "No reason provided")
                        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"Account deactivated: {reason}")

                request.state.user_id = user_id
                request.state.user_role = user.get("role", "user")
                return user_id
            else:
                if self.optional:
                    request.state.user_id = None
                    return None
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")

        except HTTPException as e:
            if self.optional:
                request.state.user_id = None
                return None
            raise e
        except Exception as e:
            logger.error(f"Auth error: {str(e)}")
            if self.optional:
                request.state.user_id = None
                return None
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Could not validate credentials")


def get_current_user_id(request: Request) -> str:
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return user_id


def get_current_user_role(request: Request) -> str:
    return getattr(request.state, "user_role", "user")


# Dependency instances
require_auth = JWTBearer()
require_admin_auth = JWTBearer(require_admin=True)
optional_auth = JWTBearer(auto_error=False, optional=True)
