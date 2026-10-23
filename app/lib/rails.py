from dataclasses import dataclass, field
from typing import List


@dataclass
class RailConfig:
    rail:        str
    currency:    str
    label:       str
    description: str
    fields:      List[str] = field(default_factory=list)  # identifier fields shown in UI


# ── Per-country rail mapping ──────────────────────────────────────────────────
COUNTRY_RAIL_MAP: dict[str, RailConfig] = {
    "BR": RailConfig("PIX",  "BRL", "PIX",              "Instant — Brazil",       ["keyType", "keyValue"]),
    "MX": RailConfig("SPEI", "MXN", "SPEI",             "Instant — Mexico",       ["clabe"]),
    "DE": RailConfig("SEPA", "EUR", "SEPA",             "Instant — Germany",      ["iban", "bic"]),
    "FR": RailConfig("SEPA", "EUR", "SEPA",             "Instant — France",       ["iban", "bic"]),
    "ES": RailConfig("SEPA", "EUR", "SEPA",             "Instant — Spain",        ["iban", "bic"]),
    "IT": RailConfig("SEPA", "EUR", "SEPA",             "Instant — Italy",        ["iban", "bic"]),
    "NL": RailConfig("SEPA", "EUR", "SEPA",             "Instant — Netherlands",  ["iban", "bic"]),
    "PT": RailConfig("SEPA", "EUR", "SEPA",             "Instant — Portugal",     ["iban", "bic"]),
    "AT": RailConfig("SEPA", "EUR", "SEPA",             "Instant — Austria",      ["iban", "bic"]),
    "BE": RailConfig("SEPA", "EUR", "SEPA",             "Instant — Belgium",      ["iban", "bic"]),
    "US": RailConfig("ACH",  "USD", "ACH",              "Same day — USA",         ["routingNumber", "accountNumber", "accountType"]),
    "GB": RailConfig("FPS",  "GBP", "Faster Payments",  "Instant — UK",           ["sortCode", "accountNumber"]),
}

DEFAULT_RAIL = RailConfig(
    rail="SWIFT",
    currency="USD",
    label="SWIFT",
    description="International wire (1–3 business days)",
    fields=["accountNumber", "swiftCode", "bankName", "bankAddress"],
)


def get_rail_config(country_code: str) -> RailConfig:
    """Return the RailConfig for a country, falling back to SWIFT."""
    return COUNTRY_RAIL_MAP.get(country_code.upper(), DEFAULT_RAIL)


def list_supported_countries() -> list[dict]:
    """Return a UI-friendly list of all supported country + rail combos."""
    entries = []
    seen_rails: set[str] = set()

    for country, cfg in COUNTRY_RAIL_MAP.items():
        entries.append({
            "country":     country,
            "rail":        cfg.rail,
            "currency":    cfg.currency,
            "label":       cfg.label,
            "description": cfg.description,
            "fields":      cfg.fields,
        })
        seen_rails.add(cfg.rail)

    # Append SWIFT as the catch-all
    entries.append({
        "country":     "*",
        "rail":        DEFAULT_RAIL.rail,
        "currency":    DEFAULT_RAIL.currency,
        "label":       DEFAULT_RAIL.label,
        "description": DEFAULT_RAIL.description,
        "fields":      DEFAULT_RAIL.fields,
    })

    return entries
