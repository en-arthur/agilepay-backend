"""
Collections API — money coming IN from a payer (fiat on-ramp).

POST /v1/collections            — create a collection, returns payment instructions
GET  /v1/collections            — list collections
GET  /v1/collections/{id}       — retrieve one collection (refreshes from Lumx)

Authentication: API key (`Authorization: Bearer sk_test_…`).
A key needs `collections:create` (or the legacy `charges:create`) to create,
and `transactions:read` to list/read.
"""
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from app.database import get_db
from app.lib.auth import ApiKeyContext, get_api_key_context
from app.models.collection import Collection
from app.models.merchant import Merchant
from app.services import collections as collection_service
from app.services.collections import create_collection, fmt, refresh_collection

router = APIRouter()


class CreateCollectionRequest(BaseModel):
    amount:          float
    currency:        Optional[str] = "USD"   # USD | GBP | EUR | MXN | BRL
    rail:            Optional[str] = None    # SWIFT | ACH | FEDWIRE | FPS | SEPA | SPEI | PIX
    purpose:         Optional[str] = None
    reference_id:    Optional[str] = None
    description:     Optional[str] = None
    payer_name:      Optional[str] = None
    payer_email:     Optional[EmailStr] = None
    payer_phone:     Optional[str] = None
    metadata:        Optional[dict[str, Any]] = None
    idempotency_key: Optional[str] = None


def _require_create_scope(ctx: ApiKeyContext) -> None:
    allowed = {"collections:create", "charges:create", "*"}
    if not allowed.intersection(set(ctx.scopes or [])):
        raise HTTPException(403, "Missing scope: collections:create")


def _require_read_scope(ctx: ApiKeyContext) -> None:
    allowed = {"transactions:read", "collections:read", "*"}
    if not allowed.intersection(set(ctx.scopes or [])):
        raise HTTPException(403, "Missing scope: transactions:read")


def _merchant(db: Session, ctx: ApiKeyContext) -> Merchant:
    merchant = db.query(Merchant).filter(Merchant.id == ctx.merchant_id).first()
    if not merchant:
        raise HTTPException(404, "Merchant not found")
    return merchant


# ── POST /v1/collections ──────────────────────────────────────────────────────

@router.post("", status_code=201)
def create(
    body: CreateCollectionRequest,
    ctx: ApiKeyContext = Depends(get_api_key_context),
    db:  Session = Depends(get_db),
):
    _require_create_scope(ctx)
    merchant = _merchant(db, ctx)

    if ctx.environment == "LIVE" and merchant.kyc_status.value != "APPROVED":
        raise HTTPException(403, "KYC verification required for live collections")

    collection = create_collection(
        db,
        merchant,
        amount          = body.amount,
        currency        = body.currency or "USD",
        rail            = body.rail,
        purpose         = body.purpose,
        reference_id    = body.reference_id,
        description     = body.description,
        payer_name      = body.payer_name,
        payer_email     = str(body.payer_email) if body.payer_email else None,
        payer_phone     = body.payer_phone,
        idempotency_key = body.idempotency_key,
        metadata        = body.metadata,
    )
    return fmt(collection)


# ── GET /v1/collections ───────────────────────────────────────────────────────

@router.get("")
def list_collections(
    ctx:   ApiKeyContext = Depends(get_api_key_context),
    db:    Session = Depends(get_db),
    limit: int = 20,
    offset: int = 0,
):
    _require_read_scope(ctx)
    rows = (
        db.query(Collection)
        .filter(Collection.merchant_id == ctx.merchant_id)
        .order_by(Collection.created_at.desc())
        .limit(min(limit, 100))
        .offset(offset)
        .all()
    )
    return [fmt(c) for c in rows]


# ── GET /v1/collections/meta/rails ────────────────────────────────────────────

@router.get("/meta/rails")
def collection_rails():
    """Currency → rail mapping and defaults, for SDK/client form rendering."""
    return {
        "rails":    collection_service.RAIL_BY_CURRENCY,
        "defaults": collection_service.DEFAULT_RAIL,
        "purposes": sorted(collection_service.ALLOWED_PURPOSES),
    }


# ── GET /v1/collections/{collection_id} ──────────────────────────────────────

@router.get("/{collection_id}")
def get_collection(
    collection_id: str,
    ctx: ApiKeyContext = Depends(get_api_key_context),
    db:  Session = Depends(get_db),
):
    _require_read_scope(ctx)
    collection = (
        db.query(Collection)
        .filter(
            Collection.collection_id == collection_id,
            Collection.merchant_id == ctx.merchant_id,
        )
        .first()
    )
    if not collection:
        raise HTTPException(404, "Collection not found")

    collection = refresh_collection(db, collection)
    return fmt(collection)

