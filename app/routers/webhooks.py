"""
POST /v1/webhooks/lumx — inbound Lumx event handler.

Verification (Svix-style scheme, per https://docs.lumx.io/developer/webhooks):

    signed_content = f"{webhook-id}.{webhook-timestamp}.{raw_body}"
    expected       = base64( HMAC-SHA256( base64decode(secret without "whsec_"),
                                          signed_content ) )

The `webhook-signature` header is space-delimited and each entry is prefixed
with a version, e.g. ``v1,<sig>``. During secret rotation Lumx sends both the
old and new signature, so any valid entry is accepted.

Other rules:
  • Replay guard: reject timestamps more than 5 minutes away
  • Idempotency: dedupe on the `webhook-id` header
  • Signature failures return 401; processing failures return 500 so Lumx retries
"""
import base64
import binascii
import hashlib
import hmac
import json
import time
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models.destination import Destination
from app.models.merchant import Merchant
from app.models.transaction import Transaction
from app.models.webhook_log import WebhookLog

router = APIRouter()

TIMESTAMP_TOLERANCE = 300  # seconds (5 minutes)


# ── Signature verification ────────────────────────────────────────────────────

def verify_signature(
    raw_body: bytes,
    msg_id: str | None,
    timestamp: str | None,
    signature_header: str | None,
) -> bool:
    """Return True only if the request carries a valid Lumx signature."""
    if not msg_id or not timestamp or not signature_header:
        return False

    try:
        event_ts = int(timestamp)
    except (TypeError, ValueError):
        return False

    if abs(int(time.time()) - event_ts) > TIMESTAMP_TOLERANCE:
        return False

    secret = settings.LUMX_WEBHOOK_SECRET
    secret = secret[len("whsec_"):] if secret.startswith("whsec_") else secret

    try:
        key = base64.b64decode(secret, validate=True)
    except (binascii.Error, ValueError):
        # Fall back to the raw secret so local dev can use a plain string.
        key = secret.encode()

    signed_content = f"{msg_id}.{timestamp}.{raw_body.decode()}".encode()
    expected = base64.b64encode(
        hmac.new(key, signed_content, hashlib.sha256).digest()
    ).decode()

    for candidate in signature_header.split():
        if candidate.startswith("v1,") and hmac.compare_digest(
            candidate[3:], expected
        ):
            return True

    return False


# ── Endpoint ──────────────────────────────────────────────────────────────────

@router.post("/lumx")
async def lumx_webhook(request: Request, db: Session = Depends(get_db)):
    raw_body = await request.body()

    if not verify_signature(
        raw_body,
        request.headers.get("webhook-id"),
        request.headers.get("webhook-timestamp"),
        request.headers.get("webhook-signature"),
    ):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    try:
        event = json.loads(raw_body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    # `webhook-id` is stable across retries — preferred dedupe key.
    event_id = request.headers.get("webhook-id") or event.get("eventId")
    event_type = event.get("eventType", "")
    data = event.get("data") or {}

    existing = (
        db.query(WebhookLog)
        .filter(WebhookLog.lumx_event_id == event_id)
        .first()
    )
    if existing and existing.processed_at:
        return {"received": True, "deduplicated": True}

    log = existing or WebhookLog(
        lumx_event_id=event_id,
        direction="INBOUND",
        event_type=event_type,
        endpoint="/v1/webhooks/lumx",
        source_ip=request.client.host if request.client else "unknown",
        raw_payload=event,
        signature_header=request.headers.get("webhook-signature"),
        signature_valid=True,
    )
    if existing is None:
        db.add(log)
    db.flush()

    failure: Exception | None = None
    try:
        _handle_event(event_type, data, db)
        log.processed_at = datetime.now(timezone.utc)
        log.response_status = 200
    except Exception as exc:  # noqa: BLE001 — recorded and retried by Lumx
        log.processing_error = str(exc)[:2000]
        log.response_status = 500
        failure = exc

    db.commit()

    if failure is not None:
        # 500 → Lumx retries with exponential backoff.
        raise HTTPException(status_code=500, detail="Webhook processing failed")

    return {"received": True}


# ── Lookups ───────────────────────────────────────────────────────────────────

def _find_transaction(db: Session, data: dict) -> Transaction | None:
    lumx_tx_id = data.get("id")
    if lumx_tx_id:
        tx = (
            db.query(Transaction)
            .filter(Transaction.lumx_transaction_id == lumx_tx_id)
            .first()
        )
        if tx:
            return tx

    charge_id = (
        (data.get("request") or {}).get("metadata") or {}
    ).get("agilepay_charge_id") or (data.get("metadata") or {}).get(
        "agilepay_charge_id"
    )
    if charge_id:
        return db.query(Transaction).filter(Transaction.charge_id == charge_id).first()
    return None


def _find_merchant(db: Session, data: dict) -> Merchant | None:
    # Customer events carry both `id` and `customerId`; accept either.
    for key in ("customerId", "id"):
        customer_id = data.get(key)
        if customer_id:
            merchant = (
                db.query(Merchant)
                .filter(Merchant.lumx_customer_id == customer_id)
                .first()
            )
            if merchant:
                return merchant
    return None


def _decimal(value) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


# ── Dispatch ──────────────────────────────────────────────────────────────────

_TRANSACTION_STATUS = {
    "offramp.transferring_stablecoin": "TRANSFERRING_STABLECOIN",
    "onramp.transferring_stablecoin": "TRANSFERRING_STABLECOIN",
    "transfer.transferring_stablecoin": "TRANSFERRING_STABLECOIN",
    "offramp.trading": "TRADING",
    "onramp.trading": "TRADING",
    "offramp.transferring_fiat": "TRANSFERRING_FIAT",
    "onramp.transferring_fiat": "TRANSFERRING_FIAT",
    "onramp.awaiting_funds": "AWAITING_FUNDS",
}


def _handle_event(event_type: str, data: dict, db: Session) -> None:
    now = datetime.now(timezone.utc)

    # ── Transactions ─────────────────────────────────────────────────────────
    if event_type in _TRANSACTION_STATUS:
        tx = _find_transaction(db, data)
        if tx:
            tx.status = _TRANSACTION_STATUS[event_type]
        return

    if event_type in ("offramp.success", "onramp.success", "transfer.success"):
        tx = _find_transaction(db, data)
        if tx:
            tx.status = "COMPLETED"
            tx.completed_at = now
            receipt = (data.get("state") or {}).get("receipt") or {}
            tx.final_target_amount = _decimal(receipt.get("finalTargetAmount"))
            tx.final_exchange_rate = _decimal(receipt.get("finalExchangeRate"))
        return

    if event_type in ("offramp.failed", "onramp.failed", "transfer.failed",
                      "onramp.expired"):
        tx = _find_transaction(db, data)
        if tx:
            tx.status = "FAILED"
            tx.failed_at = now
        return

    # ── Destinations ─────────────────────────────────────────────────────────
    # Lumx emits `destination.approved` (singular). Accept the plural form too
    # so both the documented and the observed naming are handled.
    if event_type.startswith(("destination.", "destinations.")):
        suffix = event_type.split(".", 1)[1]
        destination = (
            db.query(Destination)
            .filter(Destination.lumx_destination_id == data.get("id"))
            .first()
        )
        if not destination:
            return
        if suffix == "approved":
            destination.status = "APPROVED"
        elif suffix == "final_rejection":
            destination.status = "REJECTED"
        elif suffix in {"under_verification", "created", "temporary_rejection"}:
            destination.status = "PENDING"
        return

    # ── Customers (KYC) ──────────────────────────────────────────────────────
    if event_type.startswith("customer."):
        merchant = _find_merchant(db, data)
        if not merchant:
            return

        if event_type == "customer.approved":
            merchant.kyc_status = "APPROVED"
            merchant.status = "ACTIVE"
        elif event_type == "customer.final_rejection":
            merchant.kyc_status = "FINAL_REJECTION"
            merchant.status = "SUSPENDED"
        elif event_type == "customer.rfi":
            merchant.kyc_status = "RFI"
        elif event_type == "customer.under_verification":
            merchant.kyc_status = "PENDING"
        elif event_type == "customer.created":
            merchant.kyc_status = "NOT_STARTED"
