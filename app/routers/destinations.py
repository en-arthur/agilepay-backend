"""
Destinations — dual auth support:

  API-key auth  (SDK / programmatic):
    POST   /v1/destinations
    GET    /v1/destinations
    GET    /v1/destinations/{id}
    DELETE /v1/destinations/{id}

  JWT auth  (dashboard UI):
    POST   /v1/destinations/dashboard
    GET    /v1/destinations/dashboard
    DELETE /v1/destinations/dashboard/{id}
    PATCH  /v1/destinations/dashboard/{id}/default  ← set as default
"""
from typing import Any, Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.lib.auth import get_api_key_context, ApiKeyContext, get_current_merchant
from app.lib.rails import get_rail_config, list_supported_countries
from app.lib.validators import validate_destination_identifier
from app.models.destination import Destination
from app.models.merchant import Merchant
from app.services.lumx import LumxError, lumx

router = APIRouter()


# ── Shared ────────────────────────────────────────────────────────────────────

class DestinationRequest(BaseModel):
    label:       Optional[str] = None
    country:     str
    holder_name: str
    identifier:  dict[str, Any]


def _fmt(dest: Destination) -> dict:
    return {
        "id":                   str(dest.id),
        "lumx_destination_id":  dest.lumx_destination_id,
        "label":                dest.label,
        "rail":                 dest.rail.value,
        "currency":             dest.currency,
        "country":              dest.country,
        "holder_name":          dest.holder_name,
        "holder_relationship":  dest.holder_relationship,
        "status":               dest.status.value,
        "is_default":           dest.is_default,
        "identifier":           dest.identifier,
        "created_at":           dest.created_at.isoformat(),
    }


def _create_destination_for_merchant(merchant: Merchant, body: DestinationRequest, db: Session) -> dict:
    """Shared creation logic used by both SDK and dashboard routes."""
    if not merchant or not merchant.lumx_customer_id:
        raise HTTPException(422, "Merchant not provisioned in payment network")

    rail_cfg = get_rail_config(body.country)
    errors = validate_destination_identifier(rail_cfg.rail, body.identifier)
    if errors:
        raise HTTPException(400, ". ".join(errors))

    # PIX and SPEI destinations don't take a `holder` in the Lumx schema —
    # only customerId, name, rail, currency and identifier. Sending a partial
    # holder makes the API reject the request with VALIDATION_ERROR.
    lumx_payload: dict[str, Any] = {
        "customerId": merchant.lumx_customer_id,
        "name":       body.label or body.holder_name,
        "rail":       rail_cfg.rail,
        "currency":   rail_cfg.currency,
        "identifier": body.identifier,
    }

    if rail_cfg.rail not in {"PIX", "SPEI"}:
        lumx_payload["holder"] = {
            "type":         "INDIVIDUAL",
            "relationship": "SELF",
            "name":         body.holder_name,
        }

    try:
        lumx_dest = lumx.create_destination(
            customer_id=merchant.lumx_customer_id,
            payload=lumx_payload,
            idempotency_key=str(uuid.uuid4()),
        )
    except LumxError as exc:
        raise HTTPException(
            502,
            f"Failed to register destination with payment network: {exc.body[:400]}",
        )
    except Exception as exc:
        raise HTTPException(502, f"Failed to register destination with payment network: {exc}")

    destination = Destination(
        merchant_id         = merchant.id,
        lumx_destination_id = lumx_dest["id"],
        label               = body.label or body.holder_name,
        rail                = rail_cfg.rail,
        currency            = rail_cfg.currency,
        country             = body.country.upper(),
        identifier          = body.identifier,
        holder_name         = body.holder_name,
    )
    db.add(destination)
    db.commit()
    db.refresh(destination)

    settlement = "1–3 business days" if rail_cfg.rail == "SWIFT" else "Instant"
    return {
        **_fmt(destination),
        "settlement_time": settlement,
        "message": "Destination registered. Approval takes up to 24 hours.",
    }


# ── API-key auth routes (SDK) ─────────────────────────────────────────────────

@router.post("", status_code=201)
def create_destination(
    body: DestinationRequest,
    ctx:  ApiKeyContext = Depends(get_api_key_context),
    db:   Session = Depends(get_db),
):
    merchant = db.query(Merchant).filter(Merchant.id == ctx.merchant_id).first()
    return _create_destination_for_merchant(merchant, body, db)


@router.get("")
def list_destinations(
    ctx: ApiKeyContext = Depends(get_api_key_context),
    db:  Session = Depends(get_db),
):
    dests = (
        db.query(Destination)
        .filter(Destination.merchant_id == ctx.merchant_id)
        .order_by(Destination.created_at.desc())
        .all()
    )
    return [_fmt(d) for d in dests]


@router.get("/{destination_id}")
def get_destination(
    destination_id: str,
    ctx: ApiKeyContext = Depends(get_api_key_context),
    db:  Session = Depends(get_db),
):
    dest = (
        db.query(Destination)
        .filter(Destination.id == destination_id, Destination.merchant_id == ctx.merchant_id)
        .first()
    )
    if not dest:
        raise HTTPException(404, "Destination not found")
    return _fmt(dest)


@router.delete("/{destination_id}", status_code=200)
def delete_destination(
    destination_id: str,
    ctx: ApiKeyContext = Depends(get_api_key_context),
    db:  Session = Depends(get_db),
):
    dest = (
        db.query(Destination)
        .filter(Destination.id == destination_id, Destination.merchant_id == ctx.merchant_id)
        .first()
    )
    if not dest:
        raise HTTPException(404, "Destination not found")
    db.delete(dest)
    db.commit()
    return {"message": "Destination removed", "id": destination_id}


# ── JWT-auth routes (dashboard UI) ────────────────────────────────────────────
# Prefix: /v1/destinations/dashboard

@router.post("/dashboard", status_code=201)
def dashboard_create_destination(
    body:     DestinationRequest,
    merchant: Merchant = Depends(get_current_merchant),
    db:       Session  = Depends(get_db),
):
    return _create_destination_for_merchant(merchant, body, db)


@router.get("/dashboard")
def dashboard_list_destinations(
    merchant: Merchant = Depends(get_current_merchant),
    db:       Session  = Depends(get_db),
):
    dests = (
        db.query(Destination)
        .filter(Destination.merchant_id == merchant.id)
        .order_by(Destination.is_default.desc(), Destination.created_at.desc())
        .all()
    )
    return [_fmt(d) for d in dests]


@router.delete("/dashboard/{destination_id}", status_code=200)
def dashboard_delete_destination(
    destination_id: str,
    merchant: Merchant = Depends(get_current_merchant),
    db:       Session  = Depends(get_db),
):
    dest = (
        db.query(Destination)
        .filter(Destination.id == destination_id, Destination.merchant_id == merchant.id)
        .first()
    )
    if not dest:
        raise HTTPException(404, "Destination not found")
    db.delete(dest)
    db.commit()
    return {"message": "Destination removed", "id": destination_id}


@router.patch("/dashboard/{destination_id}/default", status_code=200)
def dashboard_set_default(
    destination_id: str,
    merchant: Merchant = Depends(get_current_merchant),
    db:       Session  = Depends(get_db),
):
    """Set a destination as the default payout target for this merchant."""
    dest = (
        db.query(Destination)
        .filter(Destination.id == destination_id, Destination.merchant_id == merchant.id)
        .first()
    )
    if not dest:
        raise HTTPException(404, "Destination not found")

    # Clear existing default
    db.query(Destination).filter(
        Destination.merchant_id == merchant.id,
        Destination.is_default.is_(True),
    ).update({"is_default": False})

    dest.is_default = True
    db.commit()
    return {"message": "Default destination updated", "id": destination_id}
