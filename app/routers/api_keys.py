"""
GET    /v1/api-keys           — list all API keys (masked)
POST   /v1/api-keys           — create new key (raw shown ONCE)
DELETE /v1/api-keys/{key_id}  — revoke a key
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.lib.auth import get_current_merchant, require_account_type
from app.lib.ids import generate_api_key
from app.models.api_key import ApiKey
from app.models.merchant import Merchant

router = APIRouter()


# ── GET /v1/api-keys ──────────────────────────────────────────────────────────

@router.get("")
def list_api_keys(
    merchant: Merchant = Depends(get_current_merchant),
    db: Session = Depends(get_db),
):
    require_account_type(merchant, "DEVELOPER", "MERCHANT")
    keys = (
        db.query(ApiKey)
        .filter(ApiKey.merchant_id == merchant.id, ApiKey.revoked_at.is_(None))
        .order_by(ApiKey.created_at.desc())
        .all()
    )
    return [
        {
            "id":          str(k.id),
            "name":        k.name,
            "environment": k.environment.value,
            "prefix":      k.key_prefix,
            "last_four":   k.last_four_chars,
            "scopes":      k.scopes,
            "is_active":   k.is_active,
            "last_used_at": k.last_used_at.isoformat() if k.last_used_at else None,
            "created_at":  k.created_at.isoformat(),
        }
        for k in keys
    ]


# ── POST /v1/api-keys ─────────────────────────────────────────────────────────

class CreateKeyRequest(BaseModel):
    name:        Optional[str] = "New API Key"
    environment: Optional[str] = "TEST"   # TEST | LIVE
    scopes:      Optional[list[str]] = None


@router.post("", status_code=201)
def create_api_key(
    body: CreateKeyRequest,
    merchant: Merchant = Depends(get_current_merchant),
    db: Session = Depends(get_db),
):
    require_account_type(merchant, "DEVELOPER", "MERCHANT")

    env = body.environment or "TEST"
    if env not in {"TEST", "LIVE"}:
        raise HTTPException(400, "environment must be TEST or LIVE")

    if env == "LIVE" and merchant.kyc_status.value != "APPROVED":
        raise HTTPException(403, "KYC must be APPROVED to create live API keys")

    default_scopes = ["charges:create", "links:create", "transactions:read"]
    scopes = body.scopes if body.scopes is not None else default_scopes

    raw_key, key_hash, prefix, last_four = generate_api_key(env)
    api_key = ApiKey(
        merchant_id     = merchant.id,
        key_prefix      = prefix,
        key_hash        = key_hash,
        last_four_chars = last_four,
        name            = body.name,
        environment     = env,
        scopes          = scopes,
    )
    db.add(api_key)
    db.commit()
    db.refresh(api_key)

    return {
        "id":          str(api_key.id),
        "name":        api_key.name,
        "environment": api_key.environment.value,
        "key":         raw_key,   # shown ONCE — will not be retrievable again
        "scopes":      api_key.scopes,
        "created_at":  api_key.created_at.isoformat(),
        "warning":     "Store this key now. It will not be shown again.",
    }


# ── DELETE /v1/api-keys/{key_id} ──────────────────────────────────────────────

@router.delete("/{key_id}", status_code=200)
def revoke_api_key(
    key_id: str,
    merchant: Merchant = Depends(get_current_merchant),
    db: Session = Depends(get_db),
):
    require_account_type(merchant, "DEVELOPER", "MERCHANT")

    key = (
        db.query(ApiKey)
        .filter(ApiKey.id == key_id, ApiKey.merchant_id == merchant.id)
        .first()
    )
    if not key:
        raise HTTPException(404, "API key not found")
    if key.revoked_at:
        raise HTTPException(400, "Key is already revoked")

    key.revoked_at = datetime.now(timezone.utc)
    key.is_active  = False
    db.commit()

    return {"message": "API key revoked", "id": key_id}
