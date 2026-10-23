"""
AgilePay FastAPI application entry-point.

Startup order:
  1. Import all SQLAlchemy models so Alembic can detect them
  2. Apply CORS middleware (Next.js frontend only)
  3. Register all routers under /v1/* (and /pay/* for public checkout)
  4. Expose a /health endpoint for Railway / Render health checks
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings

# ── Import models so Alembic autogenerate sees them ───────────────────────────
from app.models import Base  # noqa: F401
from app.models.merchant import Merchant  # noqa: F401
from app.models.api_key import ApiKey  # noqa: F401
from app.models.destination import Destination  # noqa: F401
from app.models.recipient import Recipient  # noqa: F401
from app.models.transaction import Transaction  # noqa: F401
from app.models.payment_link import PaymentLink  # noqa: F401
from app.models.partner_fee_config import PartnerFeeConfig  # noqa: F401
from app.models.webhook_log import WebhookLog  # noqa: F401

# ── Routers ───────────────────────────────────────────────────────────────────
from app.routers import (
    auth,
    merchants,
    api_keys,
    destinations,
    charges,
    links,
    transactions,
    checkout,
    webhooks,
    remittance,
    rails,
)

# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="AgilePay API",
    version="2.0.0",
    description="Stablecoin-to-fiat payment infrastructure for Africa and beyond.",
    docs_url="/docs" if settings.ENV != "production" else None,
    redoc_url="/redoc" if settings.ENV != "production" else None,
)

# ── CORS ──────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.FRONTEND_URL],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routes ────────────────────────────────────────────────────────────────────
app.include_router(auth.router,         prefix="/v1/auth",         tags=["Auth"])
app.include_router(merchants.router,    prefix="/v1/merchants",    tags=["Merchants"])
app.include_router(api_keys.router,     prefix="/v1/api-keys",     tags=["API Keys"])
app.include_router(destinations.router, prefix="/v1/destinations", tags=["Destinations"])
app.include_router(charges.router,      prefix="/v1/charges",      tags=["Charges"])
app.include_router(links.router,        prefix="/v1/links",        tags=["Payment Links"])
app.include_router(transactions.router, prefix="/v1/transactions", tags=["Transactions"])
app.include_router(checkout.router,     prefix="/pay",             tags=["Checkout"])
app.include_router(webhooks.router,     prefix="/v1/webhooks",     tags=["Webhooks"])
app.include_router(remittance.router,   prefix="/v1/remittance",   tags=["Remittance"])
app.include_router(rails.router,        prefix="/v1/rails",        tags=["Rails"])


# ── Health ────────────────────────────────────────────────────────────────────
@app.get("/health", tags=["Health"])
def health():
    return {"status": "ok", "version": "2.0.0"}
