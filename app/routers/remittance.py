"""
INDIVIDUAL account remittance flow:

POST /v1/remittance/kyc          — submit extended KYC info
POST /v1/remittance/deposit      — create on-ramp (fund wallet)
POST /v1/remittance/recipients   — add a recipient (RELATIVE | FRIEND)
GET  /v1/remittance/recipients   — list recipients
POST /v1/remittance/rate         — lock exchange rate (pre-send quote)
POST /v1/remittance/send         — execute remittance with locked rate
GET  /v1/remittance/history      — list own remittance transactions
"""
from typing import Any, List, Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.lib.auth import get_current_merchant
from app.lib.ids import generate_charge_id
from app.lib.rails import get_rail_config
from app.lib.validators import validate_destination_identifier
from app.models.merchant import Merchant
from app.models.recipient import Recipient
from app.models.transaction import Transaction
from app.services.lumx import lumx

router = APIRouter()


def _require_individual(merchant: Merchant) -> None:
    if merchant.account_type.value != "INDIVIDUAL":
        raise HTTPException(403, "INDIVIDUAL account required for this endpoint")


# ── POST /v1/remittance/kyc ───────────────────────────────────────────────────

class KycRequest(BaseModel):
    phone:                  str
    address_line1:          str
    address_city:           str
    address_state:          str
    address_postal_code:    str
    address_country:        str
    monthly_volume_usd:     str
    transaction_volume_usd: str
    source_of_funds:        str
    professional_situation: str
    occupation:             str
    jurisdictions:          List[str]


@router.post("/kyc")
def submit_kyc(
    body: KycRequest,
    merchant: Merchant = Depends(get_current_merchant),
    db: Session = Depends(get_db),
):
    _require_individual(merchant)
    if merchant.kyc_status.value == "APPROVED":
        raise HTTPException(400, "KYC already approved")

    name_parts = merchant.full_name.strip().split(" ")
    first_name = name_parts[0]
    last_name  = " ".join(name_parts[1:]) if len(name_parts) > 1 else first_name

    try:
        lumx.patch_customer_info(merchant.lumx_customer_id, {
            "phone":     body.phone,
            "firstName": first_name,
            "lastName":  last_name,
            "address": {
                "country":    body.address_country,
                "line1":      body.address_line1,
                "city":       body.address_city,
                "state":      body.address_state,
                "postalCode": body.address_postal_code,
            },
            "monthlyVolumeInUSD":        body.monthly_volume_usd,
            "transactionVolumeInUSD":    body.transaction_volume_usd,
            "sourceOfFunds":             body.source_of_funds,
            "professionalSituation":     body.professional_situation,
            "professionalOccupation":    body.occupation,
            "jurisdictions":             body.jurisdictions,
            "transactionCounterparties": ["SELF"],
            "involvedActivities":        ["NONE"],
        })
    except Exception as exc:
        raise HTTPException(502, f"Failed to submit KYC info: {exc}")

    merchant.phone                  = body.phone
    merchant.address_line1          = body.address_line1
    merchant.address_city           = body.address_city
    merchant.address_state          = body.address_state
    merchant.address_postal_code    = body.address_postal_code
    merchant.address_country        = body.address_country
    merchant.monthly_volume_usd     = body.monthly_volume_usd
    merchant.transaction_volume_usd = body.transaction_volume_usd
    merchant.source_of_funds        = body.source_of_funds
    merchant.professional_situation = body.professional_situation
    merchant.occupation             = body.occupation
    merchant.jurisdictions          = body.jurisdictions
    merchant.kyc_status             = "PENDING"
    db.commit()

    return {
        "message":  "KYC submitted. Review typically takes 1 business day.",
        "kyc_link": merchant.kyc_sumsub_link,
    }


# ── POST /v1/remittance/deposit ───────────────────────────────────────────────

class DepositRequest(BaseModel):
    amount:          str   # e.g. "500.00"
    source_currency: str   # "USD"
    rail:            str   # "ACH" | "SWIFT"


@router.post("/deposit", status_code=202)
def create_deposit(
    body: DepositRequest,
    merchant: Merchant = Depends(get_current_merchant),
    db: Session = Depends(get_db),
):
    _require_individual(merchant)
    if merchant.kyc_status.value != "APPROVED":
        raise HTTPException(403, "KYC must be approved before depositing")

    charge_id = generate_charge_id()

    try:
        lumx_onramp = lumx.create_onramp(
            payload={
                "customerId":     merchant.lumx_customer_id,
                "rail":           body.rail,
                "sourceCurrency": body.source_currency,
                "sourceAmount":   body.amount,
                "targetCurrency": "USDC",
                "purpose":        "PERSONAL_ACCOUNT",
                "blockchain":     "BASE",
                "partnerFeeId":   settings.LUMX_PARTNER_FEE_ID,
                "metadata":       {"agilepay_charge_id": charge_id},
            },
            idempotency_key=str(uuid.uuid4()),
        )
    except Exception as exc:
        raise HTTPException(502, f"Deposit initiation failed: {exc}")

    tx = Transaction(
        merchant_id         = merchant.id,
        charge_id           = charge_id,
        lumx_transaction_id = lumx_onramp["id"],
        type                = "ON_RAMP",
        status              = "AWAITING_FUNDS",
        source_amount       = float(body.amount),
        source_currency     = body.source_currency,
        target_currency     = "USDC",
    )
    db.add(tx)
    db.commit()

    return {
        "charge_id":            charge_id,
        "status":               "AWAITING_FUNDS",
        "payment_instructions": lumx_onramp.get("state", {}).get("payment"),
        "message":              "Send funds to the payment instructions. Wallet credited on receipt.",
    }


# ── POST /v1/remittance/recipients ────────────────────────────────────────────

class RecipientRequest(BaseModel):
    full_name:    str
    email:        Optional[str] = None
    phone:        Optional[str] = None
    relationship: str               # "RELATIVE" | "FRIEND"
    country:      str
    identifier:   dict[str, Any]


@router.post("/recipients", status_code=201)
def add_recipient(
    body: RecipientRequest,
    merchant: Merchant = Depends(get_current_merchant),
    db: Session = Depends(get_db),
):
    _require_individual(merchant)
    if body.relationship not in {"RELATIVE", "FRIEND"}:
        raise HTTPException(400, "relationship must be RELATIVE or FRIEND")

    rail_cfg = get_rail_config(body.country)
    errors = validate_destination_identifier(rail_cfg.rail, body.identifier)
    if errors:
        raise HTTPException(400, ". ".join(errors))

    try:
        lumx_dest = lumx.create_destination(
            customer_id=merchant.lumx_customer_id,
            payload={
                "customerId": merchant.lumx_customer_id,
                "name":       body.full_name,
                "rail":       rail_cfg.rail,
                "currency":   rail_cfg.currency,
                "identifier": body.identifier,
                "holder": {
                    "name":         body.full_name,
                    "relationship": body.relationship,
                },
            },
            idempotency_key=str(uuid.uuid4()),
        )
    except Exception as exc:
        raise HTTPException(502, f"Failed to register recipient: {exc}")

    recipient = Recipient(
        merchant_id         = merchant.id,
        lumx_destination_id = lumx_dest["id"],
        full_name           = body.full_name,
        email               = body.email,
        phone               = body.phone,
        relationship        = body.relationship,
        rail                = rail_cfg.rail,
        currency            = rail_cfg.currency,
        country             = body.country.upper(),
        identifier          = body.identifier,
    )
    db.add(recipient)
    db.commit()
    db.refresh(recipient)

    return {
        "recipient_id": str(recipient.id),
        "status":       "PENDING",
        "message":      "Recipient registered. Approval takes up to 24 hours.",
    }


# ── GET /v1/remittance/recipients ─────────────────────────────────────────────

@router.get("/recipients")
def list_recipients(
    merchant: Merchant = Depends(get_current_merchant),
    db: Session = Depends(get_db),
):
    _require_individual(merchant)
    recipients = (
        db.query(Recipient)
        .filter(Recipient.merchant_id == merchant.id)
        .order_by(Recipient.created_at.desc())
        .all()
    )
    return [
        {
            "id":           str(r.id),
            "full_name":    r.full_name,
            "email":        r.email,
            "phone":        r.phone,
            "relationship": r.relationship.value,
            "rail":         r.rail.value,
            "currency":     r.currency,
            "country":      r.country,
            "status":       r.status.value,
            "created_at":   r.created_at.isoformat(),
        }
        for r in recipients
    ]


# ── POST /v1/remittance/rate ──────────────────────────────────────────────────

class RateRequest(BaseModel):
    recipient_id: str
    amount:       str   # USDC amount to send


@router.post("/rate")
def lock_rate(
    body: RateRequest,
    merchant: Merchant = Depends(get_current_merchant),
    db: Session = Depends(get_db),
):
    _require_individual(merchant)

    recipient = (
        db.query(Recipient)
        .filter(
            Recipient.id          == body.recipient_id,
            Recipient.merchant_id == merchant.id,
            Recipient.status      == "APPROVED",
        )
        .first()
    )
    if not recipient:
        raise HTTPException(404, "Recipient not found or not yet approved")

    try:
        rate = lumx.lock_exchange_rate({
            "sourceCurrency": "USDC",
            "targetCurrency": recipient.currency,
            "sourceAmount":   body.amount,
            "destinationId":  recipient.lumx_destination_id,
            "partnerFeeId":   settings.LUMX_PARTNER_FEE_ID,
        })
    except Exception as exc:
        raise HTTPException(502, f"Could not lock exchange rate: {exc}")

    return {
        "exchange_rate_id":    rate["id"],
        "source_amount":       body.amount,
        "source_currency":     "USDC",
        "final_target_amount": rate["finalTargetAmount"],
        "target_currency":     recipient.currency,
        "exchange_rate":       rate["finalExchangeRate"],
        "expires_at":          rate["expiresAt"],
    }


# ── POST /v1/remittance/send ──────────────────────────────────────────────────

class SendRequest(BaseModel):
    recipient_id:     str
    exchange_rate_id: str
    amount:           str   # USDC amount


@router.post("/send", status_code=202)
def send_remittance(
    body: SendRequest,
    merchant: Merchant = Depends(get_current_merchant),
    db: Session = Depends(get_db),
):
    _require_individual(merchant)

    recipient = (
        db.query(Recipient)
        .filter(
            Recipient.id          == body.recipient_id,
            Recipient.merchant_id == merchant.id,
            Recipient.status      == "APPROVED",
        )
        .first()
    )
    if not recipient:
        raise HTTPException(404, "Recipient not found or not yet approved")

    charge_id = generate_charge_id()

    tx = Transaction(
        merchant_id          = merchant.id,
        recipient_id         = recipient.id,
        charge_id            = charge_id,
        type                 = "OFF_RAMP",
        status               = "PENDING",
        source_amount        = float(body.amount),
        source_currency      = "USDC",
        target_currency      = recipient.currency,
        lumx_exchange_rate_id = body.exchange_rate_id,
        purpose              = "BILLS",
    )
    db.add(tx)
    db.flush()

    try:
        lumx_response = lumx.create_offramp(
            payload={
                "destinationId":  recipient.lumx_destination_id,
                "sourceCurrency": "USDC",
                "sourceAmount":   body.amount,
                "exchangeRateId": body.exchange_rate_id,
                "purpose":        "BILLS",
                "blockchain":     "BASE",
                "partnerFeeId":   settings.LUMX_PARTNER_FEE_ID,
                "metadata":       {"agilepay_charge_id": charge_id},
            },
            idempotency_key=str(uuid.uuid4()),
        )
    except Exception as exc:
        tx.status = "FAILED"
        db.commit()
        raise HTTPException(502, f"Remittance failed: {exc}")

    tx.lumx_transaction_id = lumx_response["id"]
    tx.status = "PROCESSING"
    db.commit()

    return {
        "charge_id": charge_id,
        "status":    "PROCESSING",
        "message":   "Remittance initiated.",
    }


# ── GET /v1/remittance/history ────────────────────────────────────────────────

@router.get("/history")
def remittance_history(
    merchant: Merchant = Depends(get_current_merchant),
    db: Session = Depends(get_db),
    limit: int = 20,
    offset: int = 0,
):
    _require_individual(merchant)
    txs = (
        db.query(Transaction)
        .filter(Transaction.merchant_id == merchant.id)
        .order_by(Transaction.created_at.desc())
        .limit(min(limit, 100))
        .offset(offset)
        .all()
    )
    return [
        {
            "charge_id":      tx.charge_id,
            "type":           tx.type.value,
            "status":         tx.status.value,
            "source_amount":  float(tx.source_amount),
            "source_currency": tx.source_currency,
            "target_currency": tx.target_currency,
            "created_at":     tx.created_at.isoformat(),
            "completed_at":   tx.completed_at.isoformat() if tx.completed_at else None,
        }
        for tx in txs
    ]
