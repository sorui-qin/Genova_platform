import logging
import secrets
from datetime import timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query, Request, status
from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from backend import schemas
from backend.config import settings
from backend.db import get_db
from backend.deps import get_current_user
from backend.models import AuthRefreshToken, User
from backend.password_reset import mail_enabled, reset_link, send_reset_mail
from backend.realtime import get_sync_redis_client
from backend.security import (
    create_access_token,
    decode_password_reset_token,
    generate_refresh_token,
    hash_password,
    hash_token,
    password_fingerprint,
    verify_password,
)
from backend.utils import utcnow


router = APIRouter(prefix="/auth", tags=["auth"])
logger = logging.getLogger(__name__)


def _client_ip(request: Request) -> str:
    # Uvicorn resolves the proxy address; raw client-supplied headers are not an identity.
    return request.client.host if request.client else "unknown"


def _rate_count(key: str, window: int | None = None) -> int:
    """Read a fixed-window counter, or count this request when window is given."""
    # ponytail: fixed window that fails open, so sign-in keeps working while Redis is down.
    try:
        client = get_sync_redis_client()
        if window is None:
            return int(client.get(key) or 0)
        with client.pipeline() as pipe:
            return pipe.incr(key).expire(key, window, nx=True).execute()[0]
    except Exception:
        logger.warning("Rate limit check skipped", exc_info=True)
        return 0


def _rate_reset(key: str) -> None:
    try:
        get_sync_redis_client().delete(key)
    except Exception:
        logger.warning("Rate limit reset skipped", exc_info=True)


def _too_many(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=detail)


def _build_guest_identity_suffix() -> str:
    return secrets.token_hex(4)


def _generate_unique_guest_identity(db: Session) -> tuple[str, str]:
    for _ in range(20):
        suffix = _build_guest_identity_suffix()
        username = f"guest_{suffix}"
        email = f"guest_{suffix}@guest.genova.example.com"
        exists = db.scalar(select(User).where(or_(User.email == email, User.username == username)))
        if exists is None:
            return username, email
    raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Failed to create guest session")


def _generate_guest_code() -> str:
    return secrets.token_urlsafe(24)


def _issue_token_pair(
    db: Session,
    user: User,
    user_agent: str | None = None,
    ip: str | None = None,
) -> schemas.TokenPair:
    access_token, access_ttl = create_access_token(user.id, user.password_hash)
    refresh_token = generate_refresh_token()
    refresh_hash = hash_token(refresh_token)

    record = AuthRefreshToken(
        user_id=user.id,
        token_hash=refresh_hash,
        user_agent=user_agent,
        ip=ip,
        expires_at=utcnow() + timedelta(days=settings.refresh_token_expire_days),
    )
    db.add(record)
    db.commit()

    return schemas.TokenPair(
        access_token=access_token,
        refresh_token=refresh_token,
        access_token_expires_in=access_ttl,
    )


@router.post("/register", response_model=schemas.UserOut)
def register(payload: schemas.RegisterRequest, request: Request, db: Session = Depends(get_db)):
    # bcrypt ignores bytes after 72, so longer passwords would match on their prefix.
    if len(payload.password.encode("utf-8")) > 72:
        raise HTTPException(status_code=400, detail="PASSWORD_TOO_LONG")
    # ponytail: 100 sign-ups per address per hour leaves room for a classroom behind one NAT.
    if _rate_count(f"genova:rate:register:{_client_ip(request)}", 3600) > 100:
        raise _too_many("Too many sign-ups from this address; try again later")
    exists = db.scalar(
        select(User).where(or_(User.email == payload.email.lower(), User.username == payload.username))
    )
    if exists:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email or username already exists")

    user = User(
        email=payload.email.lower(),
        username=payload.username,
        password_hash=hash_password(payload.password),
        is_active=True,
        is_admin=False,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.post("/guest", response_model=schemas.GuestSessionOut)
def create_guest_session(
    request: Request,
    db: Session = Depends(get_db),
    user_agent: str | None = Header(default=None),
    x_forwarded_for: str | None = Header(default=None),
):
    # A classroom behind one NAT shares an address, so the limit stays generous.
    if _rate_count(f"genova:rate:guest:{_client_ip(request)}", 3600) > 100:
        raise _too_many("Too many guest sessions from this address; try again later")
    username, email = _generate_unique_guest_identity(db)
    guest_code = _generate_guest_code()

    user = User(
        email=email,
        username=username,
        password_hash=hash_password(secrets.token_urlsafe(24)),
        is_active=True,
        is_admin=False,
        is_guest=True,
        guest_code_hash=hash_token(guest_code),
        guest_code_expires_at=utcnow() + timedelta(days=settings.guest_code_expire_days),
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    token_pair = _issue_token_pair(db=db, user=user, user_agent=user_agent, ip=x_forwarded_for)
    return schemas.GuestSessionOut(
        **token_pair.model_dump(),
        guest_code=guest_code,
        username=user.username,
    )


@router.post("/login", response_model=schemas.TokenPair)
def login(
    payload: schemas.LoginRequest,
    request: Request,
    db: Session = Depends(get_db),
    user_agent: str | None = Header(default=None),
    x_forwarded_for: str | None = Header(default=None),
):
    email = payload.email.strip().lower()
    # Failures are counted per address and account, so others cannot lock a user out.
    failures = f"genova:rate:login:{_client_ip(request)}:{email}"
    if _rate_count(failures) >= 10:
        raise _too_many("Too many failed sign-in attempts; try again in 15 minutes")
    user = db.scalar(select(User).where(User.email == email))
    if user is None or not verify_password(payload.password, user.password_hash):
        _rate_count(failures, 900)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User is disabled")
    _rate_reset(failures)
    return _issue_token_pair(db=db, user=user, user_agent=user_agent, ip=x_forwarded_for)


@router.post("/refresh", response_model=schemas.TokenPair)
def refresh(
    payload: schemas.RefreshRequest,
    db: Session = Depends(get_db),
    user_agent: str | None = Header(default=None),
    x_forwarded_for: str | None = Header(default=None),
):
    token_hash = hash_token(payload.refresh_token)
    owner_id = db.scalar(select(AuthRefreshToken.user_id).where(AuthRefreshToken.token_hash == token_hash))
    if owner_id is None:
        raise HTTPException(status_code=401, detail="Invalid refresh token")
    user = db.scalar(select(User).where(User.id == owner_id).with_for_update().execution_options(populate_existing=True))
    token_record = db.scalar(select(AuthRefreshToken).where(AuthRefreshToken.token_hash == token_hash)
                             .with_for_update().execution_options(populate_existing=True))
    if token_record is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")
    if token_record.revoked_at is not None or token_record.expires_at <= utcnow():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token expired or revoked")

    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not active")

    token_record.revoked_at = utcnow()
    return _issue_token_pair(db=db, user=user, user_agent=user_agent, ip=x_forwarded_for)


@router.post("/password", response_model=schemas.TokenPair)
def change_password(
    payload: schemas.ChangePasswordRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    user_agent: str | None = Header(default=None),
    x_forwarded_for: str | None = Header(default=None),
):
    if current_user.is_guest:
        raise HTTPException(status_code=400, detail="PASSWORD_GUEST_ACCOUNT")
    # Lock the account so concurrent changes cannot both verify the old password.
    user = db.scalar(select(User).where(User.id == current_user.id).with_for_update().execution_options(populate_existing=True))
    old_password = payload.current_password.get_secret_value()
    new_password = payload.new_password.get_secret_value()
    if len(new_password.encode("utf-8")) > 72:
        raise HTTPException(status_code=400, detail="PASSWORD_TOO_LONG")
    if not verify_password(old_password, user.password_hash):
        raise HTTPException(status_code=400, detail="PASSWORD_CURRENT_INCORRECT")
    if new_password == old_password:
        raise HTTPException(status_code=400, detail="PASSWORD_UNCHANGED")
    user.password_hash = hash_password(new_password)
    user.updated_at = utcnow()
    db.execute(update(AuthRefreshToken).where(
        AuthRefreshToken.user_id == user.id,
        AuthRefreshToken.revoked_at.is_(None),
    ).values(revoked_at=utcnow()))
    return _issue_token_pair(db=db, user=user, user_agent=user_agent, ip=x_forwarded_for)


def _reset_account(db: Session, token: str, *, lock: bool = False) -> User:
    claims = decode_password_reset_token(token)
    user = None
    if claims:
        stmt = select(User).where(User.id == claims[0])
        if lock:
            stmt = stmt.with_for_update().execution_options(populate_existing=True)
        user = db.scalar(stmt)
    if user is None or user.is_guest or not user.is_active or claims[1] != password_fingerprint(user.password_hash):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Reset link is invalid, used or expired")
    return user


@router.post("/forgot_password")
def forgot_password(payload: schemas.ForgotPasswordRequest, request: Request, background: BackgroundTasks,
                    db: Session = Depends(get_db)):
    if not mail_enabled():
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="PASSWORD_RESET_EMAIL_DISABLED")
    if _rate_count(f"genova:rate:forgot:{_client_ip(request)}", 3600) > 20:
        raise _too_many("Too many reset requests from this address; try again later")
    user = db.scalar(select(User).where(User.email == payload.email.strip().lower()))
    # The reply never says whether the account exists; mail goes out after the response.
    if (user is not None and user.is_active and not user.is_guest
            and _rate_count(f"genova:password-reset:{user.id}", 60) <= 1):
        background.add_task(send_reset_mail, user.email, reset_link(user))
    return {"ok": True}


@router.get("/reset_password")
def validate_reset_link(token: str = Query(max_length=2048), db: Session = Depends(get_db)):
    _reset_account(db, token)
    return {"ok": True}


@router.post("/reset_password")
def reset_password(payload: schemas.ResetPasswordRequest, request: Request, db: Session = Depends(get_db)):
    password = payload.password.get_secret_value()
    if password != payload.confirm_password.get_secret_value():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Passwords do not match")
    if len(password) < 8 or len(password.encode("utf-8")) > 72:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Password must be 8-72 bytes")
    # The row lock makes a link single-use: a second request sees the new hash and fails.
    user = _reset_account(db, payload.token, lock=True)
    user.password_hash = hash_password(password)
    user.updated_at = utcnow()
    db.execute(update(AuthRefreshToken).where(
        AuthRefreshToken.user_id == user.id,
        AuthRefreshToken.revoked_at.is_(None),
    ).values(revoked_at=utcnow()))
    db.commit()
    # Let the new password sign in right away from the address that reset it.
    _rate_reset(f"genova:rate:login:{_client_ip(request)}:{user.email}")
    return {"ok": True}


@router.post("/logout")
def logout(payload: schemas.LogoutRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    token_hash = hash_token(payload.refresh_token)
    token_record = db.scalar(
        select(AuthRefreshToken).where(
            AuthRefreshToken.token_hash == token_hash,
            AuthRefreshToken.user_id == current_user.id,
            AuthRefreshToken.revoked_at.is_(None),
        )
    )
    if token_record is not None:
        token_record.revoked_at = utcnow()
        db.commit()
    return {"ok": True}


@router.post("/claim", response_model=schemas.UserOut)
def claim_guest_account(
    payload: schemas.ClaimGuestRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Lock and re-read: a concurrent claim of the same guest may have committed after authentication.
    current_user = db.scalar(select(User).where(User.id == current_user.id).with_for_update().execution_options(populate_existing=True))
    if not current_user.is_guest:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Current account is not a guest account")

    email = payload.email.strip().lower()
    username = payload.username.strip()
    exists = db.scalar(
        select(User).where(
            or_(User.email == email, User.username == username),
            User.id != current_user.id,
        )
    )
    if exists:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email or username already exists")
    if len(payload.password.encode("utf-8")) > 72:
        raise HTTPException(status_code=400, detail="PASSWORD_TOO_LONG")

    current_user.email = email
    current_user.username = username
    current_user.password_hash = hash_password(payload.password)
    current_user.is_guest = False
    current_user.guest_code_hash = None
    current_user.guest_code_expires_at = None
    current_user.guest_code_last_used_at = None
    current_user.updated_at = utcnow()
    db.execute(update(AuthRefreshToken).where(AuthRefreshToken.user_id == current_user.id,
        AuthRefreshToken.revoked_at.is_(None)).values(revoked_at=utcnow()))
    db.commit()
    db.refresh(current_user)
    return current_user


@router.get("/me", response_model=schemas.UserOut)
def me(current_user: User = Depends(get_current_user)):
    return current_user
