"""
POST /v1/auth/signup

Creates:
  1. Supabase Auth user
  2. Lumx customer
  3. merchants row (id = Supabase UUID)
  4. Default TEST API key (DEVELOPER accounts only)
"""
from datetime import datetime
from typing import Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session
from supabase import create_client

from app.config import settings
from app.database import get_db
from app.lib.ids import generate_api_key
from app.models.api_key import ApiKey
from app.models.merchant import Merchant
from app.services.lumx import lumx

router = APIRouter()

supabase_admin = create_client(
    settings.SUPABASE_URL,
    settings.SUPABASE_SERVICE_ROLE_KEY,
)


class SignupRequest(BaseModel):
    email:         EmailStr
    password:      str
    full_name:     str
    business_name: Optional[str] = None
    business_type: Optional[str] = "INDIVIDUAL"
    country:       Optional[str] = "GH"
    account_type:  Optional[str] = "DEVELOPER"  # DEVELOPER | MERCHANT | INDIVIDUAL
    # INDIVIDUAL only
    tax_id:        Optional[str] = None
    birth_date:    Optional[str] = None   # "YYYY-MM-DD"
    phone:         Optional[str] = None


REDIRECT_MAP = {
    "DEVELOPER":  "/dashboard/developers",
    "MERCHANT":   "/dashboard/links",
    "INDIVIDUAL": "/dashboard/remittance",
}


@router.post("/signup", status_code=201)
def signup(body: SignupRequest, db: Session = Depends(get_db)):
    if body.account_type not in {"DEVELOPER", "MERCHANT", "INDIVIDUAL"}:
        raise HTTPException(400, "account_type must be DEVELOPER, MERCHANT, or INDIVIDUAL")

    if body.account_type == "INDIVIDUAL" and (not body.tax_id or not body.birth_date):
        raise HTTPException(400, "tax_id and birth_date required for INDIVIDUAL accounts")

    # 1. Create Supabase Auth user ─────────────────────────────────────────────
    try:
        auth_response = supabase_admin.auth.admin.create_user({
            "email":         body.email,
            "password":      body.password,
            "email_confirm": True,
            "user_metadata": {"account_type": body.account_type},
        })
    except Exception as exc:
        if "already registered" in str(exc).lower():
            raise HTTPException(409, "Email already registered")
        raise HTTPException(400, str(exc))

    auth_user_id: str = auth_response.user.id

    # 2. Create Lumx customer ──────────────────────────────────────────────────
    if body.account_type == "INDIVIDUAL":
        lumx_payload = {
            "type":      "INDIVIDUAL",
            "name":      body.full_name,
            "email":     body.email,
            "country":   body.country or "GH",
            "taxId":     body.tax_id,
            "birthDate": body.birth_date,
            "accounts":  ["USD"],
        }
    else:
        lumx_payload = {
            "type":    "BUSINESS" if body.business_type == "BUSINESS" else "INDIVIDUAL",
            "name":    body.business_name or body.full_name,
            "email":   body.email,
            "country": body.country or "GH",
        }

    try:
        lumx_customer = lumx.create_customer(lumx_payload, idempotency_key=str(uuid.uuid4()))
    except Exception:
        supabase_admin.auth.admin.delete_user(auth_user_id)
        raise HTTPException(502, "Failed to provision payment account")

    # 3. Create merchant row ───────────────────────────────────────────────────
    merchant = Merchant(
        id               = uuid.UUID(auth_user_id),
        email            = body.email,
        full_name        = body.full_name,
        business_name    = body.business_name if body.account_type != "INDIVIDUAL" else None,
        business_type    = body.business_type or "INDIVIDUAL",
        country          = body.country or "GH",
        account_type     = body.account_type,
        lumx_customer_id = lumx_customer["id"],
        kyc_sumsub_link  = lumx_customer.get("verification", {}).get("link"),
        tax_id           = body.tax_id if body.account_type == "INDIVIDUAL" else None,
        birth_date       = datetime.strptime(body.birth_date, "%Y-%m-%d") if body.birth_date else None,
        phone            = body.phone,
    )
    db.add(merchant)
    db.flush()

    # 4. Issue default TEST API key (DEVELOPER only) ───────────────────────────
    test_api_key: Optional[str] = None
    if body.account_type == "DEVELOPER":
        raw_key, key_hash, prefix, last_four = generate_api_key("TEST")
        api_key_row = ApiKey(
            merchant_id     = merchant.id,
            key_prefix      = prefix,
            key_hash        = key_hash,
            last_four_chars = last_four,
            name            = "Default Test Key",
            environment     = "TEST",
            scopes          = ["charges:create", "links:create", "transactions:read"],
        )
        db.add(api_key_row)
        test_api_key = raw_key   # shown ONCE — not stored in plaintext

    db.commit()

    return {
        "merchant_id":  str(merchant.id),
        "account_type": merchant.account_type,
        "kyc_link":     merchant.kyc_sumsub_link,
        **({"test_api_key": test_api_key} if test_api_key else {}),
        "redirect_to":  REDIRECT_MAP[body.account_type],
        "message":      "Account created. Complete KYC to activate live payments.",
    }
