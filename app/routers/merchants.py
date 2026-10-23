"""
GET  /v1/merchants/me         — fetch own merchant profile
PATCH /v1/merchants/me        — update profile fields
GET  /v1/merchants/me/kyc     — fetch KYC status + link
POST /v1/merchants/me/go-live — request live mode activation
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.lib.auth import get_current_merchant
from app.models.merchant import Merchant
from app.services.lumx import lumx

router = APIRouter()


# ── GET /v1/merchants/me ──────────────────────────────────────────────────────

@router.get("/me")
def get_me(merchant: Merchant = Depends(get_current_merchant)):
    return {
        "id":              str(merchant.id),
        "email":           merchant.email,
        "full_name":       merchant.full_name,
        "business_name":   merchant.business_name,
        "country":         merchant.country,
        "account_type":    merchant.account_type.value,
        "status":          merchant.status.value,
        "kyc_status":      merchant.kyc_status.value,
        "is_live":         merchant.is_live,
        "is_sandbox":      merchant.is_sandbox,
        "lumx_customer_id": merchant.lumx_customer_id,
    }


# ── PATCH /v1/merchants/me ────────────────────────────────────────────────────

class UpdateMerchantRequest(BaseModel):
    full_name:     Optional[str] = None
    business_name: Optional[str] = None
    phone:         Optional[str] = None


@router.patch("/me")
def update_me(
    body: UpdateMerchantRequest,
    merchant: Merchant = Depends(get_current_merchant),
    db: Session = Depends(get_db),
):
    if body.full_name:
        merchant.full_name = body.full_name
    if body.business_name:
        merchant.business_name = body.business_name
    if body.phone:
        merchant.phone = body.phone
    db.commit()
    return {"message": "Profile updated"}


# ── GET /v1/merchants/me/kyc ──────────────────────────────────────────────────

@router.get("/me/kyc")
def get_kyc_status(merchant: Merchant = Depends(get_current_merchant)):
    # Optionally refresh from Lumx for up-to-date status
    kyc_link = merchant.kyc_sumsub_link
    if merchant.lumx_customer_id:
        try:
            lumx_data = lumx.get_customer(merchant.lumx_customer_id)
            kyc_link = lumx_data.get("verification", {}).get("link", kyc_link)
        except Exception:
            pass  # fall back to cached value

    return {
        "kyc_status": merchant.kyc_status.value,
        "kyc_link":   kyc_link,
    }


# ── POST /v1/merchants/me/go-live ─────────────────────────────────────────────

@router.post("/me/go-live")
def request_go_live(
    merchant: Merchant = Depends(get_current_merchant),
    db: Session = Depends(get_db),
):
    if merchant.kyc_status.value != "APPROVED":
        raise HTTPException(403, "KYC must be APPROVED before going live")
    if merchant.is_live:
        return {"message": "Already in live mode"}

    merchant.is_live    = True
    merchant.is_sandbox = False
    db.commit()

    return {"message": "Live mode activated", "is_live": True}
