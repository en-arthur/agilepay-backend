"""
POST /v1/webhooks/lumx  — inbound Lumx event handler

Security:
  • HMAC-SHA256 over  "{timestamp}.{raw_body}"  using LUMX_WEBHOOK_SECRET
  • Replay-attack guard: reject events older than 5 minutes
  • Idempotency: skip already-processed lumx_event_id
  • Fail silently (always 200) to avoid Lumx retry storms
"""
import hashlib
import hmac as hmac_lib
import json
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models.destination import Destination
from app.models.merchant import Merchant
from app.models.transaction import Transaction
from app.models.webhook_log import WebhookLog
from app.services.lumx import lumx

router = APIRouter()

TIMESTAMP_TOLERANCE = 300  # seconds (5 minutes)


@router.post("/lumx")
async def lumx_webhook(request: Request, db: Session = Depends(get_db)):
    raw_body = await request.body()
    signature = request.headers.get("X-Lumx-Signature", "")
    timestamp = request.headers.get("X-Lumx-Timestamp", "0")

    # ── Replay-attack guard ────────────────────────────────────────────────────
    try:
        event_ts = int(timestamp)
    except ValueError:
        return {"received": True}

    if abs(int(time.time()) - event_ts) > TIMESTAMP_TOLERANCE:
        return {"received": True}

    # ── HMAC-SHA256 verification ───────────────────────────────────────────────
    signed_payload = f"{timestamp}.{raw_body.decode()}"
    expected_sig = "sha256=" + hmac_lib.new(
        settings.LUMX_WEBHOOK_SECRET.encode(),
        signed_payload.encode(),
        hashlib.sha256,
    ).hexdigest()

    sig_valid = hmac_lib.compare_digest(signature.encode(), expected_sig.encode())
    if not sig_valid:
        return {"received": True}   # fail silently — don't leak info

    # ── Parse event ───────────────────────────────────────────────────────────
    event = json.loads(raw_body)
    event_id   = event.get("id")
    event_type = event.get("type", "")
    data       = event.get("data", {})

    # ── Idempotency ───────────────────────────────────────────────────────────
    existing = db.query(WebhookLog).filter(WebhookLog.lumx_event_id == event_id).first()
    if existing and existing.processed_at:
        return {"received": True, "deduplicated": True}

    # ── Log inbound event ─────────────────────────────────────────────────────
    log = WebhookLog(
        lumx_event_id    = event_id,
        direction        = "INBOUND",
        event_type       = event_type,
        endpoint         = "/v1/webhooks/lumx",
        source_ip        = request.client.host if request.client else "unknown",
        raw_payload      = event,
        signature_header = signature,
        signature_valid  = True,
    )
    db.add(log)
    db.flush()

    # ── Dispatch ──────────────────────────────────────────────────────────────
    try:
        _handle_event(event_type, data, db)
        log.processed_at    = datetime.now(timezone.utc)
        log.response_status = 200
    except Exception as exc:
        log.processing_error = str(exc)
        log.response_status  = 500

    db.commit()
    return {"received": True}


# ── Event handlers ────────────────────────────────────────────────────────────

def _handle_event(event_type: str, data: dict, db: Session) -> None:
    lumx_tx_id = data.get("id")

    if event_type in ("offramp.success", "onramp.success"):
        confirmed  = lumx.get_transaction(lumx_tx_id)
        charge_id  = confirmed.get("request", {}).get("metadata", {}).get("agilepay_charge_id")
        if not charge_id:
            return
        tx = db.query(Transaction).filter(Transaction.charge_id == charge_id).first()
        if tx:
            tx.status       = "COMPLETED"
            tx.completed_at = datetime.now(timezone.utc)

    elif event_type in ("offramp.failed", "onramp.failed"):
        confirmed = lumx.get_transaction(lumx_tx_id)
        charge_id = confirmed.get("request", {}).get("metadata", {}).get("agilepay_charge_id")
        if not charge_id:
            return
        tx = db.query(Transaction).filter(Transaction.charge_id == charge_id).first()
        if tx:
            tx.status    = "FAILED"
            tx.failed_at = datetime.now(timezone.utc)

    elif event_type == "offramp.processing":
        confirmed = lumx.get_transaction(lumx_tx_id)
        charge_id = confirmed.get("request", {}).get("metadata", {}).get("agilepay_charge_id")
        if not charge_id:
            return
        tx = db.query(Transaction).filter(Transaction.charge_id == charge_id).first()
        if tx and tx.status.value == "PENDING":
            tx.status = "PROCESSING"

    elif event_type == "destinations.approved":
        dest = db.query(Destination).filter(
            Destination.lumx_destination_id == lumx_tx_id
        ).first()
        if dest:
            dest.status = "APPROVED"

    elif event_type == "destinations.rejected":
        dest = db.query(Destination).filter(
            Destination.lumx_destination_id == lumx_tx_id
        ).first()
        if dest:
            dest.status = "REJECTED"

    elif event_type == "customer.verification.approved":
        lumx_customer_id = data.get("id")
        merchant = db.query(Merchant).filter(
            Merchant.lumx_customer_id == lumx_customer_id
        ).first()
        if merchant:
            merchant.kyc_status = "APPROVED"
            merchant.status     = "ACTIVE"

    elif event_type in ("customer.verification.rejected", "customer.verification.final_rejection"):
        lumx_customer_id = data.get("id")
        merchant = db.query(Merchant).filter(
            Merchant.lumx_customer_id == lumx_customer_id
        ).first()
        if merchant:
            merchant.kyc_status = "FINAL_REJECTION"
            merchant.status     = "SUSPENDED"

    elif event_type == "customer.verification.pending":
        lumx_customer_id = data.get("id")
        merchant = db.query(Merchant).filter(
            Merchant.lumx_customer_id == lumx_customer_id
        ).first()
        if merchant and merchant.kyc_status.value == "NOT_STARTED":
            merchant.kyc_status = "PENDING"
