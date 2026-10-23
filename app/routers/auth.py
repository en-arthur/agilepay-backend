"""
POST /v1/auth/signup

Creates:
  1. Supabase Auth user
  2. Lumx customer
  3. merchants row (id = Supabase UUID)
  4. Default TEST API key (DEVELOPER accounts only)
"""
from datetime import datetime
import logging
from typing import Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session
from supabase import create_client

from app.config import settings
from app.database import get_db
from app.lib.countries import UnsupportedCountry, to_alpha3
from app.lib.ids import generate_api_key
from app.models.api_key import ApiKey
from app.models.merchant import Merchant
from app.services.lumx import LumxError, lumx

logger = logging.getLogger(__name__)

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
    business_type: Optional[str] = "INDIVIDUAL"   # INDIVIDUAL | BUSINESS
    country:       Optional[str] = "GH"           # alpha-2 or alpha-3
    account_type:  Optional[str] = "MERCHANT"    # MERCHANT | INDIVIDUAL (DEVELOPER = legacy)
    # Required for INDIVIDUAL customers (KYC)
    tax_id:        Optional[str] = None
    birth_date:    Optional[str] = None           # "YYYY-MM-DD"
    # Required for BUSINESS customers (KYB)
    incorporation_date: Optional[str] = None      # "YYYY-MM-DD"
    phone:         Optional[str] = None


REDIRECT_MAP = {
    "DEVELOPER":  "/dashboard/developers",
    "MERCHANT":   "/dashboard/links",
    "INDIVIDUAL": "/dashboard/remittance",
}


def _date(value: str | None, field: str) -> str:
    """Validate a YYYY-MM-DD date and return it unchanged (Lumx format)."""
    try:
        datetime.strptime(value or "", "%Y-%m-%d")
    except ValueError:
        raise HTTPException(400, f"{field} must be in YYYY-MM-DD format")
    return value  # type: ignore[return-value]


def _customer_payload(body: SignupRequest) -> dict:
    """
    Build a POST /customers body that matches the Lumx schema.

    INDIVIDUAL requires: type, name, taxId, birthDate, country (alpha-3), email
    BUSINESS   requires: type, legalName, taxId, incorporationDate, country, email

    Lumx rejects 2-letter country codes, so `country` is converted to alpha-3.
    """
    try:
        country = to_alpha3(body.country)
    except UnsupportedCountry as exc:
        raise HTTPException(400, str(exc))

    # Provision the local-currency accounts Lumx allows for this project.
    # An off-ramp to a rail whose account was never provisioned returns
    # ACCOUNT_NOT_FOUND, so create them up front.
    accounts = [
        currency.strip().upper()
        for currency in settings.LUMX_ACCOUNTS.split(",")
        if currency.strip()
    ]

    if body.business_type == "BUSINESS":
        missing = [
            name for name, value in (
                ("tax_id", body.tax_id),
                ("incorporation_date", body.incorporation_date),
                ("business_name", body.business_name),
            )
            if not value
        ]
        if missing:
            raise HTTPException(
                400,
                f"{', '.join(missing)} required for BUSINESS customers",
            )
        return {
            "type":              "BUSINESS",
            "legalName":         body.business_name,
            "taxId":             body.tax_id,
            "incorporationDate": _date(body.incorporation_date, "incorporation_date"),
            "country":           country,
            "email":             body.email,
            "accounts":          accounts,
        }

    missing = [
        name for name, value in (
            ("tax_id", body.tax_id),
            ("birth_date", body.birth_date),
        )
        if not value
    ]
    if missing:
        raise HTTPException(
            400,
            f"{', '.join(missing)} required for identity verification",
        )

    return {
        "type":      "INDIVIDUAL",
        "name":      body.full_name,
        "taxId":     body.tax_id,
        "birthDate": _date(body.birth_date, "birth_date"),
        "country":   country,
        "email":     body.email,
        "accounts":  accounts,
    }


@router.post("/signup", status_code=201)
def signup(body: SignupRequest, db: Session = Depends(get_db)):
    if body.account_type not in {"DEVELOPER", "MERCHANT", "INDIVIDUAL"}:
        raise HTTPException(400, "account_type must be DEVELOPER, MERCHANT, or INDIVIDUAL")

    # Validate everything that would make Lumx reject the request BEFORE
    # creating the Supabase user, so a bad payload doesn't burn the email.
    lumx_payload = _customer_payload(body)

    # 1. Create Supabase Auth user ─────────────────────────────────────────────
    try:
        auth_response = supabase_admin.auth.admin.create_user({
            "email":         body.email,
            "password":      body.password,
            "email_confirm": True,
            "user_metadata": {"account_type": body.account_type},
        })
    except Exception as exc:
        message = str(exc)
        if "already" in message.lower():
            raise HTTPException(409, "Email already registered")
        raise HTTPException(400, message)

    auth_user_id: str = auth_response.user.id

    # 2. Create Lumx customer ──────────────────────────────────────────────────
    try:
        lumx_customer = lumx.create_customer(
            lumx_payload, idempotency_key=str(uuid.uuid4())
        )
    except Exception as exc:
        logger.exception("Lumx customer creation failed for %s", body.email)
        try:
            supabase_admin.auth.admin.delete_user(auth_user_id)
        except Exception:  # noqa: BLE001 — nothing else we can do here
            logger.exception("Could not roll back Supabase user %s", auth_user_id)

        detail = "Failed to provision payment account"
        if isinstance(exc, LumxError):
            detail = f"{detail}: {exc.body[:300]}"
        raise HTTPException(502, detail)

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
        # KYC identity is required for every account type and is reused as the
        # default holder tax ID on SELF payout destinations.
        tax_id           = body.tax_id,
        birth_date       = datetime.strptime(body.birth_date, "%Y-%m-%d") if body.birth_date else None,
        phone            = body.phone,
    )
    db.add(merchant)
    db.flush()

    # 4. Issue default TEST API key (business accounts) ────────────────────────
    test_api_key: Optional[str] = None
    if body.account_type in {"DEVELOPER", "MERCHANT"}:
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
