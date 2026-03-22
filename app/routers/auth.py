"""Authentication router — login, logout, session management."""

import logging
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel
from sqlmodel import Session, select

from app.database import engine
from app.models import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    success: bool
    username: str
    message: str = ""


@router.post("/login", response_model=LoginResponse)
async def login(req: Request, body: LoginRequest):
    """Authenticate user and create session cookie."""
    with Session(engine) as session:
        user = session.exec(
            select(User).where(User.username == body.username)
        ).first()

    # Verify credentials
    if not user or not _verify_password(body.password, user.password):
        logger.warning(f"❌ Failed login attempt for user: {body.username}")
        raise HTTPException(status_code=401, detail="Sai tên đăng nhập hoặc mật khẩu")

    # Create session
    req.session["user_id"] = user.id
    req.session["username"] = user.username

    logger.info(f"✅ User '{user.username}' logged in successfully")
    return LoginResponse(success=True, username=user.username)


@router.post("/logout")
async def logout(req: Request):
    """Clear session and redirect to login."""
    username = req.session.get("username", "unknown")
    req.session.clear()
    logger.info(f"👋 User '{username}' logged out")
    return {"success": True}


@router.get("/me")
async def get_me(req: Request):
    """Return current authenticated user info."""
    user_id = req.session.get("user_id")
    username = req.session.get("username")
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return {"user_id": user_id, "username": username}


def _verify_password(plain: str, stored: str) -> bool:
    """Verify password — supports both plain text (legacy) and bcrypt hash."""
    # Try bcrypt first (forward-compatible)
    try:
        import bcrypt  # type: ignore
        if stored.startswith("$2b$") or stored.startswith("$2a$"):
            return bcrypt.checkpw(plain.encode(), stored.encode())
    except ImportError:
        pass
    # Fallback: plain text comparison (legacy)
    return plain == stored
