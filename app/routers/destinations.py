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
from app.lib.countries import UnsupportedCountry, to_alpha3
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
    # Lumx requires a `holder` block for SEPA / ACH / FEDWIRE / FPS / SWIFT and
    # a `bank` block for the same rails. PIX only needs the identifier, SPEI
    # needs type + taxId. Everything here defaults to the merchant's own KYC
    # data (the destination holder is the merchant, relationship SELF).
    holder_tax_id:            Optional[str] = None
    holder_address_country:   Optional[str] = None
    holder_address_line1:     Optional[str] = None
    holder_address_city:      Optional[str] = None
    holder_address_state:     Optional[str] = None
    holder_address_postal_code: Optional[str] = None
    bank_name:                Optional[str] = None
    bank_address_country:     Optional[str] = None
    bank_address_line1:       Optional[str] = None
    bank_address_city:        Optional[str] = None
    bank_address_state:       Optional[str] = None
    bank_address_postal_code: Optional[str] = None


# Rails whose Lumx payload requires a `holder` object.
HOLDER_REQUIRED_RAILS = {"SEPA", "ACH", "FEDWIRE", "FPS", "SWIFT"}
# Rails whose Lumx payload requires a `bank` object.
BANK_REQUIRED_RAILS = {"SEPA", "ACH", "FEDWIRE", "FPS", "SWIFT"}
# ACH/FEDWIRE use the stricter bank address schema (all fields required).
FULL_BANK_ADDRESS_RAILS = {"ACH", "FEDWIRE"}


def _normalise_identifier(rail: str, identifier: dict[str, Any]) -> dict[str, Any]:
    """
    Map AgilePay's identifier keys onto Lumx's per-rail identifiers.

    The dashboard/API use `accountType` for ACH and FEDWIRE, while Lumx expects
    `type` (and rejects unknown properties). FEDWIRE omits `type` upstream, so
    default it to CHECKING.
    """
    ident = dict(identifier)

    if rail in {"ACH", "FEDWIRE"}:
        account_type = ident.pop("accountType", None)
        ident.setdefault("type", account_type or "CHECKING")

    return ident


def _holder_block(merchant: Merchant, body: DestinationRequest, rail: str) -> dict:
    """Build the Lumx `holder` object, defaulting to the merchant's KYC data."""
    # SELF destinations must match the customer's KYC identity, otherwise Lumx
    # rejects with HOLDER_TAX_ID_MISMATCH / HOLDER_TYPE_MISMATCH.
    tax_id = body.holder_tax_id or merchant.tax_id
    if not tax_id:
        raise HTTPException(
            400,
            f"holder_tax_id required for {rail} destinations "
            "(it must match the account holder's tax ID)",
        )

    holder: dict[str, Any] = {
        "type": "BUSINESS" if merchant.business_type == "BUSINESS" else "INDIVIDUAL",
        "taxId": tax_id,
    }

    # SPEI only takes type + taxId + name. Sending relationship makes Lumx
    # enforce SELF tax-ID matching, which the SPEI rail rejects.
    if rail == "SPEI":
        holder["name"] = body.holder_name
        return holder

    holder["relationship"] = "SELF"

    country = (
        body.holder_address_country
        or merchant.address_country
        or merchant.country
        or body.country
    )
    try:
        address: dict[str, Any] = {"country": to_alpha3(country)}
    except UnsupportedCountry as exc:
        raise HTTPException(400, str(exc))

    if rail in FULL_BANK_ADDRESS_RAILS:
        # ACH / FEDWIRE use the full address schema for the holder too.
        fields = {
            "line1":      body.holder_address_line1 or merchant.address_line1,
            "city":       body.holder_address_city or merchant.address_city,
            "state":      body.holder_address_state or merchant.address_state,
            "postalCode": body.holder_address_postal_code or merchant.address_postal_code,
        }
        missing = [key for key, value in fields.items() if not value]
        if missing:
            raise HTTPException(
                400,
                f"holder address incomplete for {rail} destinations: "
                f"missing {', '.join(missing)}",
            )
        address.update(fields)

    holder["address"] = address
    holder["name"] = body.holder_name

    return holder


def _bank_block(merchant: Merchant, body: DestinationRequest, rail: str) -> dict:
    """Build the Lumx `bank` object required by non-PIX/SPEI rails."""
    name = body.bank_name or merchant.business_name
    if not name:
        raise HTTPException(400, f"bank_name required for {rail} destinations")

    country = (
        body.bank_address_country
        or merchant.address_country
        or body.country
    )
    try:
        address: dict[str, Any] = {"country": to_alpha3(country)}
    except UnsupportedCountry as exc:
        raise HTTPException(400, str(exc))

    if rail in FULL_BANK_ADDRESS_RAILS:
        # ACH / FEDWIRE require a complete bank address.
        fields = {
            "line1":      body.bank_address_line1 or merchant.address_line1,
            "city":       body.bank_address_city or merchant.address_city,
            "state":      body.bank_address_state or merchant.address_state,
            "postalCode": body.bank_address_postal_code or merchant.address_postal_code,
        }
        missing = [key for key, value in fields.items() if not value]
        if missing:
            raise HTTPException(
                400,
                f"bank address incomplete for {rail} destinations: "
                f"missing {', '.join(missing)}",
            )
        address.update(fields)

    return {"name": name, "address": address}


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

    # PIX destinations don't take a `holder` in the Lumx schema — only
    # customerId, name, rail, currency and identifier. SPEI wants type + taxId.
    lumx_payload: dict[str, Any] = {
        "customerId": merchant.lumx_customer_id,
        "name":       body.label or body.holder_name,
        "rail":       rail_cfg.rail,
        "currency":   rail_cfg.currency,
        "identifier": _normalise_identifier(rail_cfg.rail, body.identifier),
    }

    if rail_cfg.rail in HOLDER_REQUIRED_RAILS or rail_cfg.rail == "SPEI":
        lumx_payload["holder"] = _holder_block(merchant, body, rail_cfg.rail)

    if rail_cfg.rail in BANK_REQUIRED_RAILS:
        lumx_payload["bank"] = _bank_block(merchant, body, rail_cfg.rail)

    try:
        lumx_dest = lumx.create_destination(
            customer_id=merchant.lumx_customer_id,
            payload=lumx_payload,
            idempotency_key=str(uuid.uuid4()),
        )
    except LumxError as exc:
        raise HTTPException(
            502,
            f"Failed to register destination with payment network: {exc.body[:900]}",
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
        identifier          = lumx_payload["identifier"],
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


# ── GET /v1/destinations/{destination_id} ─────────────────────────────────────
# Declared LAST on purpose: FastAPI matches routes in declaration order, so a
# dynamic "/{destination_id}" route placed before "/dashboard" swallows
# GET /v1/destinations/dashboard and rejects the dashboard JWT with
# "Invalid API key format". Keeping it last lets every static /dashboard*
# route win.

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
