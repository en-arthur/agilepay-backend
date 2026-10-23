"""
Public hosted checkout — no auth required.

GET  /pay/{link_id}                              — link metadata for the checkout page
POST /pay/{link_id}                              — payer submits details → creates a
                                                   fiat COLLECTION (on-ramp) and
                                                   returns the payment instructions
GET  /pay/{link_id}/collections/{collection_id}  — poll the collection status

Money flows IN: the payer sends fiat to the Lumx virtual account (or PIX code)
returned by POST. When Lumx confirms it (`onramp.success` webhook) the
merchant's USDC balance is credited and the collection flips to COMPLETED.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.collection import Collection
from app.models.merchant import Merchant
from app.models.payment_link import PaymentLink
from app.services.collections import (
    create_collection,
    fmt as fmt_collection,
    refresh_collection,
    resolve_rail,
)

router = APIRouter()


class CheckoutRequest(BaseModel):
    payer_name:  str
    payer_email: EmailStr
    payer_phone: Optional[str] = None
    amount_cents: Optional[int] = None   # only if link is variable-amount


def _active_link(link_id: str, db: Session) -> PaymentLink:
    link = db.query(PaymentLink).filter(PaymentLink.link_id == link_id).first()
    if not link:
        raise HTTPException(404, "Payment link not found")
    if not link.is_active:
        raise HTTPException(410, "This payment link is no longer active")
    if link.max_uses and (link.use_count or 0) >= link.max_uses:
        raise HTTPException(410, "This payment link has reached its maximum uses")
    return link


# ── GET /pay/{link_id} — public metadata ─────────────────────────────────────

@router.get("/{link_id}")
def get_checkout(link_id: str, db: Session = Depends(get_db)):
    link = _active_link(link_id, db)
    currency = (link.currency or "USD").upper()

    # Tell the checkout page which rail will be used, so it can label the
    # payment instructions correctly ("Bank transfer (SWIFT)" etc.).
    try:
        rail = resolve_rail(currency, None)
    except HTTPException:
        rail = None

    return {
        "link_id":        link.link_id,
        "title":          link.title,
        "description":    link.description,
        "amount_cents":   link.amount_cents,
        "currency":       currency,
        "is_fixed_amount": link.is_fixed_amount,
        "min_amount_cents": link.min_amount_cents,
        "max_amount_cents": link.max_amount_cents,
        "logo_url":       link.logo_url,
        "rail":           rail,
    }


# ── POST /pay/{link_id} — payer submits → create a collection ────────────────

@router.post("/{link_id}", status_code=202)
def submit_checkout(
    link_id: str,
    body: CheckoutRequest,
    db: Session = Depends(get_db),
):
    link = _active_link(link_id, db)
    currency = (link.currency or "USD").upper()

    # Resolve amount (in the link's currency)
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

    merchant = db.query(Merchant).filter(Merchant.id == link.merchant_id).first()
    if not merchant:
        raise HTTPException(404, "Merchant not found")

    collection = create_collection(
        db,
        merchant,
        amount          = amount_cents / 100.0,
        currency        = currency,
        description     = link.title,
        payer_name      = body.payer_name,
        payer_email     = str(body.payer_email),
        payer_phone     = body.payer_phone,
        payment_link_id = link.id,
        metadata        = {"payment_link_id": link.link_id},
    )

    link.use_count = (link.use_count or 0) + 1
    db.commit()

    return {
        "collection_id":   collection.collection_id,
        "status":          collection.status,
        "rail":            collection.rail,
        "amount":          float(collection.source_amount),
        "currency":        collection.source_currency,
        "target_currency": collection.target_currency,
        "payment":         collection.payment_details or {},
        "success_url":     link.success_url,
        "message":         "Send the exact amount using the details below. "
                           "Include the reference so we can match your payment.",
    }


# ── GET /pay/{link_id}/collections/{collection_id} — status poll ─────────────

@router.get("/{link_id}/collections/{collection_id}")
def get_checkout_collection(
    link_id: str,
    collection_id: str,
    db: Session = Depends(get_db),
):
    link = db.query(PaymentLink).filter(PaymentLink.link_id == link_id).first()
    if not link:
        raise HTTPException(404, "Payment link not found")

    collection = (
        db.query(Collection)
        .filter(
            Collection.collection_id == collection_id,
            Collection.payment_link_id == link.id,
        )
        .first()
    )
    if not collection:
        raise HTTPException(404, "Collection not found")

    collection = refresh_collection(db, collection)
    return fmt_collection(collection)
