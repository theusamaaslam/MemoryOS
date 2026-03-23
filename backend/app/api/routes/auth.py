from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import require_admin, require_auth
from app.schemas.auth import (
    ApiKeyCreateRequest,
    ApiKeyResponse,
    AppCreateRequest,
    AppResponse,
    OrgUserResponse,
    LoginRequest,
    LogoutRequest,
    MeResponse,
    RefreshTokenRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
    UserRoleUpdateRequest,
)
from app.services.auth import auth_service


router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest) -> UserResponse:
    try:
        user = auth_service.register(payload.email, payload.password, payload.full_name, payload.org_name)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return UserResponse(user_id=user.user_id, email=user.email, full_name=user.full_name, org_id=user.org_id, role=user.role)


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest) -> TokenResponse:
    try:
        access_token, refresh_token = auth_service.login(payload.email, payload.password)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


@router.post("/refresh", response_model=TokenResponse)
def refresh(payload: RefreshTokenRequest) -> TokenResponse:
    try:
        access_token, refresh_token = auth_service.refresh_access_token(payload.refresh_token)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(payload: LogoutRequest) -> None:
    try:
        auth_service.revoke_refresh_token(payload.refresh_token)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc


@router.post("/api-keys", response_model=ApiKeyResponse)
def create_api_key(payload: ApiKeyCreateRequest, identity: dict = Depends(require_admin)) -> ApiKeyResponse:
    if payload.org_id != identity["org_id"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot create API keys for another organization")
    key_id, api_key = auth_service.create_api_key(payload.org_id, payload.app_id, payload.name)
    return ApiKeyResponse(key_id=key_id, name=payload.name, app_id=payload.app_id, api_key=api_key)


@router.get("/me", response_model=MeResponse)
def me(identity: dict = Depends(require_auth)) -> MeResponse:
    return MeResponse(
        user_id=identity.get("sub") or identity.get("key_id", ""),
        email=identity.get("email"),
        org_id=identity["org_id"],
        role=identity.get("role", "service"),
    )


@router.post("/apps", response_model=AppResponse)
def create_app(payload: AppCreateRequest, identity: dict = Depends(require_admin)) -> AppResponse:
    app = auth_service.create_app(identity["org_id"], payload.app_id, payload.name)
    return AppResponse(app_id=app.app_id, org_id=app.org_id, name=app.name)


@router.get("/apps", response_model=list[AppResponse])
def list_apps(identity: dict = Depends(require_admin)) -> list[AppResponse]:
    return [AppResponse(app_id=app.app_id, org_id=app.org_id, name=app.name) for app in auth_service.list_apps(identity["org_id"])]


@router.get("/users", response_model=list[OrgUserResponse])
def list_users(identity: dict = Depends(require_admin)) -> list[OrgUserResponse]:
    return [
        OrgUserResponse(user_id=user.user_id, email=user.email, full_name=user.full_name, org_id=user.org_id, role=user.role)
        for user in auth_service.list_org_users(identity["org_id"])
    ]


@router.post("/users/{user_id}/role", response_model=OrgUserResponse)
def update_user_role(user_id: str, payload: UserRoleUpdateRequest, identity: dict = Depends(require_admin)) -> OrgUserResponse:
    user = auth_service.update_user_role(identity["org_id"], user_id, payload.role)
    return OrgUserResponse(user_id=user.user_id, email=user.email, full_name=user.full_name, org_id=user.org_id, role=user.role)
