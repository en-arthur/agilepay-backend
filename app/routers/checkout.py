"""
Public hosted checkout — no auth required.

GET  /pay/{link_id}           — return link metadata for the checkout page
POST /pay/{link_id}           — payer submits their details → creates a charge
"""
from typing import Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.lib.ids import generate_charge_id
from app.models.destination import Destination
from app.models.payment_link import PaymentLink
from app.models.transaction import Transaction
from app.services.lumx import LumxError, lumx

router = APIRouter()


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
        return True
    except (ValueError, AttributeError, TypeError):
        return False


class CheckoutRequest(BaseModel):
    payer_name:  str
    payer_email: EmailStr
    payer_phone: Optional[str] = None
    amount_cents: Optional[int] = None   # only if link is variable-amount


# ── GET /pay/{link_id} — public metadata ─────────────────────────────────────

@router.get("/{link_id}")
def get_checkout(link_id: str, db: Session = Depends(get_db)):
    link = db.query(PaymentLink).filter(PaymentLink.link_id == link_id).first()
    if not link:
        raise HTTPException(404, "Payment link not found")
    if not link.is_active:
        raise HTTPException(410, "This payment link is no longer active")
    if link.max_uses and link.use_count >= link.max_uses:
        raise HTTPException(410, "This payment link has reached its maximum uses")

    return {
        "link_id":        link.link_id,
        "title":          link.title,
        "description":    link.description,
        "amount_cents":   link.amount_cents,
        "currency":       link.currency,
        "is_fixed_amount": link.is_fixed_amount,
        "min_amount_cents": link.min_amount_cents,
        "max_amount_cents": link.max_amount_cents,
        "logo_url":       link.logo_url,
    }


# ── POST /pay/{link_id} — payer submits ───────────────────────────────────────

@router.post("/{link_id}", status_code=202)
def submit_checkout(
    link_id: str,
    body: CheckoutRequest,
    db: Session = Depends(get_db),
):
    link = db.query(PaymentLink).filter(PaymentLink.link_id == link_id).first()
    if not link:
        raise HTTPException(404, "Payment link not found")
    if not link.is_active:
        raise HTTPException(410, "This payment link is no longer active")
    if link.max_uses and link.use_count >= link.max_uses:
        raise HTTPException(410, "This payment link has reached its maximum uses")

    # Resolve amount
    if link.is_fixed_amount:
        if not link.amount_cents:
            raise HTTPException(500, "Fixed-amount link has no amount set")
        amount_cents = link.amount_cents
    else:
        if not body.amount_cents:
            raise HTTPException(400, "amount_cents is required for variable-amount links")
        if link.min_amount_cents and body.amount_cents < link.min_amount_cents:
            raise HTTPException(400, f"Minimum amount is {link.min_amount_cents} cents")
        if link.max_amount_cents and body.amount_cents > link.max_amount_cents:
            raise HTTPException(400, f"Maximum amount is {link.max_amount_cents} cents")
        amount_cents = body.amount_cents

    amount_usdc = amount_cents / 100.0  # simple 1:1 USD → USDC conversion

    # Resolve destination (default destination on the link, fallback to first approved)
    destination: Optional[Destination] = None
    if link.default_destination_id:
        destination = db.query(Destination).filter(
            Destination.id == link.default_destination_id,
            Destination.status == "APPROVED",
        ).first()

    if not destination:
        destination = (
            db.query(Destination)
            .filter(
                Destination.merchant_id == link.merchant_id,
                Destination.status      == "APPROVED",
            )
            .first()
        )

    if not destination:
        raise HTTPException(503, "No approved destination available for this merchant")

    charge_id = generate_charge_id()

    tx = Transaction(
        merchant_id     = link.merchant_id,
        destination_id  = destination.id,
        payment_link_id = link.id,
        charge_id       = charge_id,
        source_amount   = amount_usdc,
        source_currency = "USDC",
        target_currency = destination.currency,
        type            = "OFF_RAMP",
        status          = "PENDING",
        payer_name      = body.payer_name,
        payer_email     = body.payer_email,
        payer_phone     = body.payer_phone,
        description     = link.title,
    )
    db.add(tx)
    db.flush()

    try:
        payload: dict = {
            "destinationId":  destination.lumx_destination_id,
            "sourceCurrency": "USDC",
            "sourceAmount":   f"{amount_usdc:.2f}",
            "purpose":        "TRADE_TRANSACTIONS",
            "metadata": {
                "agilepay_charge_id":      charge_id,
                "agilepay_transaction_id": str(tx.id),
                "payer_email":             body.payer_email,
            },
        }
        # Same rules as POST /v1/charges: only send a blockchain the project
        # actually has wallets on, and only a real partner-fee UUID.
        if settings.LUMX_BLOCKCHAIN:
            payload["blockchain"] = settings.LUMX_BLOCKCHAIN
        if _is_uuid(settings.LUMX_PARTNER_FEE_ID):
            payload["partnerFeeId"] = settings.LUMX_PARTNER_FEE_ID

        lumx_response = lumx.create_offramp(
            payload=payload,
            idempotency_key=str(uuid.uuid4()),
        )
    except LumxError as exc:
        tx.status = "FAILED"
        db.commit()
        raise HTTPException(
            502,
            f"Payment network rejected the payment: {exc.body[:400]}",
        )
    except Exception:
        tx.status = "FAILED"
        db.commit()
        raise HTTPException(502, "Payment processing unavailable. Please try again.")

    tx.lumx_transaction_id = lumx_response["id"]
    tx.status = "PROCESSING"

    # Increment use counter
    link.use_count = (link.use_count or 0) + 1

    db.commit()

    return {
        "charge_id":     charge_id,
        "status":        "PROCESSING",
        "amount_cents":  amount_cents,
        "currency":      link.currency,
        "success_url":   link.success_url,
        "message":       "Payment initiated. You will receive a confirmation email.",
    }
