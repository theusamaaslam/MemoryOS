from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import hashlib
from uuid import uuid4

from jose import jwt
from passlib.context import CryptContext
from sqlalchemy import select

from app.core.config import settings
from app.core.db import session_scope
from app.models.persistence import ApiKeyModel, AppModel, OrganizationModel, RefreshTokenModel, UserModel


pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


@dataclass(slots=True)
class User:
    user_id: str
    email: str
    full_name: str
    org_id: str
    role: str
    password_hash: str


class AuthService:
    def _create_access_token(self, user: User) -> str:
        expires_at = datetime.now(UTC) + timedelta(minutes=settings.access_token_expiry_minutes)
        return jwt.encode(
            {"sub": user.user_id, "email": user.email, "org_id": user.org_id, "role": user.role, "type": "access", "exp": expires_at},
            settings.jwt_secret,
            algorithm=settings.jwt_algorithm,
        )

    def register(self, email: str, password: str, full_name: str, org_name: str) -> User:
        with session_scope() as session:
            existing = session.scalar(select(UserModel).where(UserModel.email == email))
            if existing:
                raise ValueError("User already exists")
            org_id = org_name.lower().replace(" ", "-")
            organization = session.get(OrganizationModel, org_id)
            if organization is None:
                session.add(OrganizationModel(org_id=org_id, name=org_name, created_at=datetime.now(UTC)))
            model = UserModel(
                user_id=str(uuid4()),
                email=email,
                full_name=full_name,
                org_id=org_id,
                role="owner",
                password_hash=pwd_context.hash(password),
                created_at=datetime.now(UTC),
            )
            session.add(model)
            return User(
                user_id=model.user_id,
                email=model.email,
                full_name=model.full_name,
                org_id=model.org_id,
                role=model.role,
                password_hash=model.password_hash,
            )

    def login(self, email: str, password: str) -> tuple[str, str]:
        user = self.get_user_by_email(email)
        if user is None or not pwd_context.verify(password, user.password_hash):
            raise ValueError("Invalid credentials")
        return self._create_access_token(user), self._issue_refresh_token(user)

    def get_user_by_email(self, email: str) -> User | None:
        with session_scope() as session:
            model = session.scalar(select(UserModel).where(UserModel.email == email))
            if model is None:
                return None
            return User(
                user_id=model.user_id,
                email=model.email,
                full_name=model.full_name,
                org_id=model.org_id,
                role=model.role,
                password_hash=model.password_hash,
            )

    def create_api_key(self, org_id: str, app_id: str, name: str) -> tuple[str, str]:
        raw_key = f"mos_{uuid4().hex}{uuid4().hex}"
        with session_scope() as session:
            model = ApiKeyModel(
                key_id=str(uuid4()),
                org_id=org_id,
                app_id=app_id,
                hashed_key=pwd_context.hash(raw_key),
                name=name,
                created_at=datetime.now(UTC),
            )
            session.add(model)
            return model.key_id, raw_key

    def validate_api_key(self, raw_key: str) -> dict | None:
        with session_scope() as session:
            keys = session.scalars(select(ApiKeyModel)).all()
            for key in keys:
                if pwd_context.verify(raw_key, key.hashed_key):
                    return {"org_id": key.org_id, "app_id": key.app_id, "key_id": key.key_id}
        return None

    def _issue_refresh_token(self, user: User) -> str:
        token_id = str(uuid4())
        raw_token = f"mrt_{uuid4().hex}{uuid4().hex}"
        now = datetime.now(UTC)
        expires_at = now + timedelta(days=settings.refresh_token_expiry_days)
        with session_scope() as session:
            session.add(
                RefreshTokenModel(
                    token_id=token_id,
                    user_id=user.user_id,
                    org_id=user.org_id,
                    token_hash=self._hash_token(raw_token),
                    expires_at=expires_at,
                    revoked_at=None,
                    created_at=now,
                )
            )
        return jwt.encode(
            {"sub": user.user_id, "org_id": user.org_id, "type": "refresh", "jti": token_id, "secret": raw_token, "exp": expires_at},
            settings.jwt_secret,
            algorithm=settings.jwt_algorithm,
        )

    def refresh_access_token(self, refresh_token: str) -> tuple[str, str]:
        try:
            payload = jwt.decode(refresh_token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        except Exception as exc:
            raise ValueError("Invalid refresh token") from exc
        if payload.get("type") != "refresh":
            raise ValueError("Invalid refresh token")
        token_id = payload.get("jti")
        raw_secret = payload.get("secret")
        if not token_id or not raw_secret:
            raise ValueError("Invalid refresh token")
        with session_scope() as session:
            token_row = session.get(RefreshTokenModel, token_id)
            if token_row is None or token_row.revoked_at is not None or token_row.expires_at < datetime.now(UTC):
                raise ValueError("Refresh token expired or revoked")
            if token_row.token_hash != self._hash_token(raw_secret):
                raise ValueError("Invalid refresh token")
            user_model = session.get(UserModel, token_row.user_id)
            if user_model is None:
                raise ValueError("User not found")
            token_row.revoked_at = datetime.now(UTC)
            user = User(
                user_id=user_model.user_id,
                email=user_model.email,
                full_name=user_model.full_name,
                org_id=user_model.org_id,
                role=user_model.role,
                password_hash=user_model.password_hash,
            )
        return self._create_access_token(user), self._issue_refresh_token(user)

    def revoke_refresh_token(self, refresh_token: str) -> None:
        try:
            payload = jwt.decode(refresh_token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        except Exception as exc:
            raise ValueError("Invalid refresh token") from exc
        token_id = payload.get("jti")
        with session_scope() as session:
            token_row = session.get(RefreshTokenModel, token_id)
            if token_row is None:
                return
            token_row.revoked_at = datetime.now(UTC)

    def _hash_token(self, token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def create_app(self, org_id: str, app_id: str, name: str) -> AppModel:
        with session_scope() as session:
            if session.get(OrganizationModel, org_id) is None:
                raise ValueError("Organization not found")
            if session.get(AppModel, app_id) is not None:
                raise ValueError("App already exists")
            app = AppModel(app_id=app_id, org_id=org_id, name=name, created_at=datetime.now(UTC))
            session.add(app)
            return app

    def list_apps(self, org_id: str) -> list[AppModel]:
        with session_scope() as session:
            return session.scalars(select(AppModel).where(AppModel.org_id == org_id).order_by(AppModel.name.asc())).all()

    def list_org_users(self, org_id: str) -> list[User]:
        with session_scope() as session:
            rows = session.scalars(select(UserModel).where(UserModel.org_id == org_id).order_by(UserModel.created_at.asc())).all()
            return [
                User(
                    user_id=row.user_id,
                    email=row.email,
                    full_name=row.full_name,
                    org_id=row.org_id,
                    role=row.role,
                    password_hash=row.password_hash,
                )
                for row in rows
            ]

    def update_user_role(self, org_id: str, user_id: str, role: str) -> User:
        if role not in {"owner", "admin", "member"}:
            raise ValueError("Invalid role")
        with session_scope() as session:
            row = session.get(UserModel, user_id)
            if row is None or row.org_id != org_id:
                raise ValueError("User not found")
            row.role = role
            return User(
                user_id=row.user_id,
                email=row.email,
                full_name=row.full_name,
                org_id=row.org_id,
                role=row.role,
                password_hash=row.password_hash,
            )


auth_service = AuthService()
