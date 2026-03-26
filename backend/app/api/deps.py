from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from app.core.config import settings
from app.services.auth import auth_service


bearer = HTTPBearer(auto_error=False)


def require_auth(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> dict:
    if x_api_key:
        api_key = auth_service.validate_api_key(x_api_key)
        if api_key:
            return api_key
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    try:
        payload = jwt.decode(credentials.credentials, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        if payload.get("type") not in (None, "access"):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token type")
        return payload
    except JWTError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from exc


def require_admin(identity: dict = Depends(require_auth)) -> dict:
    if identity.get("role") not in {"owner", "admin"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required")
    return identity


def identity_user_id(identity: dict) -> str:
    return str(identity.get("sub") or identity.get("user_id") or identity.get("key_id") or "")


def resolve_app_id(identity: dict, requested_app_id: str | None) -> str:
    requested = (requested_app_id or "").strip()
    if identity.get("key_id"):
        scoped_app = str(identity.get("app_id") or "").strip()
        if requested and requested != scoped_app:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="API key is scoped to a different app")
        if not scoped_app:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="API key is missing an app scope")
        return scoped_app
    if not requested:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="app_id is required")
    return requested


def resolve_end_user_id(identity: dict, requested_user_id: str | None) -> str:
    requested = (requested_user_id or "").strip()
    if identity.get("key_id"):
        return requested or f"service:{identity['key_id']}"
    actor_user_id = identity_user_id(identity)
    if requested and requested != actor_user_id and identity.get("role") not in {"owner", "admin"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot act on behalf of another user")
    return requested or actor_user_id


def ensure_org_access(identity: dict, org_id: str) -> None:
    if str(identity.get("org_id")) != str(org_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot access another organization")
