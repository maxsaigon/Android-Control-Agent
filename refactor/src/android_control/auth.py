"""Small session authentication layer for the public control plane."""

import hashlib
import hmac
import secrets

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, RedirectResponse

from .database import Repository

PUBLIC_PATHS = {"/login", "/auth/login", "/api/health"}
PUBLIC_PREFIXES = ("/static/",)


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 600_000)
    return f"pbkdf2_sha256$600000${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations, salt_hex, expected_hex = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt_hex), int(iterations)
        )
        return hmac.compare_digest(actual.hex(), expected_hex)
    except (ValueError, TypeError):
        return False


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=256)


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path in PUBLIC_PATHS or path.startswith(PUBLIC_PREFIXES):
            return await call_next(request)
        if request.session.get("username"):
            return await call_next(request)
        if path.startswith("/api/"):
            return JSONResponse({"detail": "Authentication required"}, status_code=401)
        return RedirectResponse(f"/login?next={path}", status_code=303)


def build_auth_router(repository: Repository) -> APIRouter:
    router = APIRouter()

    @router.post("/auth/login")
    def login(request: Request, body: LoginRequest) -> dict[str, str | bool]:
        encoded = repository.get_admin_password_hash(body.username)
        if encoded is None or not verify_password(body.password, encoded):
            raise HTTPException(401, "Sai tên đăng nhập hoặc mật khẩu")
        request.session.clear()
        request.session["username"] = body.username
        return {"success": True, "username": body.username}

    @router.post("/auth/logout")
    def logout(request: Request) -> dict[str, bool]:
        request.session.clear()
        return {"success": True}

    @router.get("/api/auth/me")
    def me(request: Request) -> dict[str, str]:
        return {"username": request.session["username"]}

    return router
