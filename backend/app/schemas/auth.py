from pydantic import BaseModel, EmailStr


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    full_name: str
    org_name: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshTokenRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str


class UserResponse(BaseModel):
    user_id: str
    email: EmailStr
    full_name: str
    org_id: str
    role: str


class ApiKeyCreateRequest(BaseModel):
    org_id: str
    app_id: str
    name: str


class ApiKeyResponse(BaseModel):
    key_id: str
    name: str
    app_id: str
    api_key: str


class MeResponse(BaseModel):
    user_id: str
    email: str | None = None
    org_id: str
    role: str


class AppCreateRequest(BaseModel):
    app_id: str
    name: str


class AppResponse(BaseModel):
    app_id: str
    org_id: str
    name: str


class OrgUserResponse(BaseModel):
    user_id: str
    email: EmailStr
    full_name: str
    org_id: str
    role: str


class UserRoleUpdateRequest(BaseModel):
    role: str
