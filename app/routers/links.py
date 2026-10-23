"""
POST   /v1/links          — create a payment link
GET    /v1/links          — list all payment links
GET    /v1/links/{id}     — retrieve single link
PATCH  /v1/links/{id}     — update link (title, amount, active flag)
DELETE /v1/links/{id}     — deactivate / delete link
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.lib.auth import get_current_merchant
from app.lib.ids import generate_link_id
from app.models.destination import Destination
from app.models.merchant import Merchant
from app.models.payment_link import PaymentLink

router = APIRouter()


class CreateLinkRequest(BaseModel):
    title:                  str
    description:            Optional[str] = None
    amount_cents:           Optional[int] = None
    currency:               Optional[str] = "USD"
    is_fixed_amount:        Optional[bool] = True
    min_amount_cents:       Optional[int] = None
    max_amount_cents:       Optional[int] = None
    default_destination_id: Optional[str] = None
    max_uses:               Optional[int] = None
    success_url:            Optional[str] = None
    cancel_url:             Optional[str] = None
    logo_url:               Optional[str] = None


class UpdateLinkRequest(BaseModel):
    title:          Optional[str] = None
    description:    Optional[str] = None
    amount_cents:   Optional[int] = None
    is_fixed_amount: Optional[bool] = None
    is_active:      Optional[bool] = None
    success_url:    Optional[str] = None
    cancel_url:     Optional[str] = None


def _fmt(link: PaymentLink, base_url: str = "") -> dict:
    return {
        "id":                     str(link.id),
        "link_id":                link.link_id,
        "url":                    f"{base_url}/pay/{link.link_id}",
        "title":                  link.title,
        "description":            link.description,
        "amount_cents":           link.amount_cents,
        "currency":               link.currency,
        "is_fixed_amount":        link.is_fixed_amount,
        "min_amount_cents":       link.min_amount_cents,
        "max_amount_cents":       link.max_amount_cents,
        "default_destination_id": str(link.default_destination_id) if link.default_destination_id else None,
        "is_active":              link.is_active,
        "use_count":              link.use_count,
        "max_uses":               link.max_uses,
        "success_url":            link.success_url,
        "cancel_url":             link.cancel_url,
        "logo_url":               link.logo_url,
        "created_at":             link.created_at.isoformat(),
    }


# ── POST /v1/links ────────────────────────────────────────────────────────────

@router.post("", status_code=201)
def create_link(
    body: CreateLinkRequest,
    merchant: Merchant = Depends(get_current_merchant),
    db: Session = Depends(get_db),
):
    if merchant.account_type.value == "INDIVIDUAL":
        raise HTTPException(403, "Payment links are not available for individual accounts")

    # Validate destination belongs to this merchant
    if body.default_destination_id:
        dest = (
            db.query(Destination)
            .filter(
                Destination.id          == body.default_destination_id,
                Destination.merchant_id == merchant.id,
            )
            .first()
        )
        if not dest:
            raise HTTPException(404, "Destination not found")

    link = PaymentLink(
        merchant_id            = merchant.id,
        link_id                = generate_link_id(),
        title                  = body.title,
        description            = body.description,
        amount_cents           = body.amount_cents,
        currency               = body.currency or "USD",
        is_fixed_amount        = body.is_fixed_amount if body.is_fixed_amount is not None else True,
        min_amount_cents       = body.min_amount_cents,
        max_amount_cents       = body.max_amount_cents,
        default_destination_id = body.default_destination_id,
        max_uses               = body.max_uses,
        success_url            = body.success_url,
        cancel_url             = body.cancel_url,
        logo_url               = body.logo_url,
    )
    db.add(link)
    db.commit()
    db.refresh(link)

    return _fmt(link)


# ── GET /v1/links ─────────────────────────────────────────────────────────────

@router.get("")
def list_links(
    merchant: Merchant = Depends(get_current_merchant),
    db: Session = Depends(get_db),
):
    links = (
        db.query(PaymentLink)
        .filter(PaymentLink.merchant_id == merchant.id)
        .order_by(PaymentLink.created_at.desc())
        .all()
    )
    return [_fmt(lnk) for lnk in links]


# ── GET /v1/links/{link_id} ───────────────────────────────────────────────────

@router.get("/{link_id}")
def get_link(
    link_id: str,
    merchant: Merchant = Depends(get_current_merchant),
    db: Session = Depends(get_db),
):
    link = (
        db.query(PaymentLink)
        .filter(PaymentLink.link_id == link_id, PaymentLink.merchant_id == merchant.id)
        .first()
    )
    if not link:
        raise HTTPException(404, "Payment link not found")
    return _fmt(link)


# ── PATCH /v1/links/{link_id} ─────────────────────────────────────────────────

@router.patch("/{link_id}")
def update_link(
    link_id: str,
    body: UpdateLinkRequest,
    merchant: Merchant = Depends(get_current_merchant),
    db: Session = Depends(get_db),
):
    link = (
        db.query(PaymentLink)
        .filter(PaymentLink.link_id == link_id, PaymentLink.merchant_id == merchant.id)
        .first()
    )
    if not link:
        raise HTTPException(404, "Payment link not found")

    if body.title          is not None: link.title          = body.title
    if body.description    is not None: link.description    = body.description
    if body.amount_cents   is not None: link.amount_cents   = body.amount_cents
    if body.is_fixed_amount is not None: link.is_fixed_amount = body.is_fixed_amount
    if body.is_active      is not None: link.is_active      = body.is_active
    if body.success_url    is not None: link.success_url    = body.success_url
    if body.cancel_url     is not None: link.cancel_url     = body.cancel_url

    db.commit()
    db.refresh(link)
    return _fmt(link)


# ── DELETE /v1/links/{link_id} ────────────────────────────────────────────────

@router.delete("/{link_id}", status_code=200)
def delete_link(
    link_id: str,
    merchant: Merchant = Depends(get_current_merchant),
    db: Session = Depends(get_db),
):
    link = (
        db.query(PaymentLink)
        .filter(PaymentLink.link_id == link_id, PaymentLink.merchant_id == merchant.id)
        .first()
    )
    if not link:
        raise HTTPException(404, "Payment link not found")
    db.delete(link)
    db.commit()
    return {"message": "Payment link deleted", "link_id": link_id}
