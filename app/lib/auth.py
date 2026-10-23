import re
from datetime import datetime, timezone
from functools import lru_cache

import bcrypt
import jwt
from fastapi import Depends, Header, HTTPException
from jwt import PyJWKClient
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models.api_key import ApiKey
from app.models.merchant import Merchant


# ── Supabase JWT auth — dashboard / user-facing routes ───────────────────────

@lru_cache(maxsize=1)
def _jwks_client() -> PyJWKClient:
    """
    Supabase projects created after the JWT-signing-keys migration sign access
    tokens with an asymmetric key (ES256/RS256) instead of the legacy shared
    HS256 secret. Public keys are published as a JWKS document.
    """
    return PyJWKClient(
        f"{settings.SUPABASE_URL.rstrip('/')}/auth/v1/.well-known/jwks.json",
        cache_keys=True,
    )


def _decode_supabase_jwt(token: str) -> dict:
    header = jwt.get_unverified_header(token)
    alg = header.get("alg", "")

    if alg == "HS256":
        # Legacy projects: shared secret from Settings → API → JWT Secret.
        key = settings.SUPABASE_JWT_SECRET
    elif alg in {"ES256", "RS256"}:
        # New projects: verify against the project's JWKS.
        key = _jwks_client().get_signing_key_from_jwt(token).key
    else:
        raise jwt.InvalidTokenError(f"Unsupported JWT algorithm: {alg}")

    return jwt.decode(token, key, algorithms=[alg], audience="authenticated")


def get_current_merchant(
    authorization: str | None = Header(None),
    db: Session = Depends(get_db),
) -> Merchant:
    """
    Verify the Supabase JWT sent as  Authorization: Bearer <token>
    and return the matching Merchant row.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")

    token = authorization[7:]

    # Reject API keys on JWT routes — they start with sk_
    if token.startswith("sk_"):
        raise HTTPException(
            status_code=401,
            detail="Use API key auth for SDK routes",
        )

    try:
        payload = _decode_supabase_jwt(token)
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

    user_id = payload.get("sub")
    merchant = db.query(Merchant).filter(Merchant.id == user_id).first()
    if not merchant:
        raise HTTPException(status_code=404, detail="Merchant not found")

    return merchant


# ── API key auth — SDK / programmatic routes ──────────────────────────────────

class ApiKeyContext:
    """Lightweight context object attached to SDK requests."""

    def __init__(self, merchant_id: str, environment: str, scopes: list):
        self.merchant_id = merchant_id
        self.environment = environment
        self.scopes = scopes


def get_api_key_context(
    authorization: str | None = Header(None),
    db: Session = Depends(get_db),
) -> ApiKeyContext:
    """
    Verify  Authorization: Bearer sk_live_xxx  or  sk_test_xxx.
    Uses bcrypt compare against stored hash — no plaintext stored.
    """
    if not authorization or not authorization.startswith("Bearer sk_"):
        raise HTTPException(status_code=401, detail="Invalid API key format")

    raw_key = authorization[7:]  # strip "Bearer "

    if not re.match(r"^sk_(test|live)_[A-Za-z0-9]{32}$", raw_key):
        raise HTTPException(status_code=401, detail="Invalid API key format")

    # Only load candidates that share the same 8-char prefix to limit bcrypt checks
    prefix = raw_key[:8]  # "sk_test_" or "sk_live_"
    candidates = (
        db.query(ApiKey)
        .filter(
            ApiKey.key_prefix == prefix,
            ApiKey.is_active.is_(True),
            ApiKey.revoked_at.is_(None),
        )
        .limit(20)
        .all()
    )

    now = datetime.now(timezone.utc)

    for candidate in candidates:
        if candidate.expires_at and candidate.expires_at < now:
            continue
        if bcrypt.checkpw(raw_key.encode(), candidate.key_hash.encode()):
            candidate.last_used_at = now
            db.commit()
            return ApiKeyContext(
                merchant_id=str(candidate.merchant_id),
                environment=candidate.environment.value,
                scopes=candidate.scopes or [],
            )

    raise HTTPException(status_code=401, detail="Invalid API key")


# ── Scope / account-type guards ───────────────────────────────────────────────

def require_scope(ctx: ApiKeyContext, scope: str) -> None:
    """Raise 403 if the API key does not carry the required scope."""
    if scope not in ctx.scopes and "*" not in ctx.scopes:
        raise HTTPException(status_code=403, detail=f"Missing scope: {scope}")


def require_account_type(merchant: Merchant, *types: str) -> None:
    """Raise 403 if the merchant's account type is not in the allowed list."""
    if merchant.account_type.value not in types:
        raise HTTPException(
            status_code=403,
            detail=f"This endpoint requires account type: {', '.join(types)}",
        )
