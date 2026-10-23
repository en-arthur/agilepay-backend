"""
GET /v1/rails          — list all supported countries + their rail/currency/fields
GET /v1/rails/{country} — get rail config for a single country code
"""
from fastapi import APIRouter, HTTPException
from app.lib.rails import get_rail_config, list_supported_countries, COUNTRY_RAIL_MAP

router = APIRouter()


@router.get("")
def get_all_rails():
    """Return the full country → rail mapping for the frontend destination form."""
    return list_supported_countries()


@router.get("/{country_code}")
def get_rail_for_country(country_code: str):
    """Return the rail config for a specific ISO-3166 country code."""
    cfg = get_rail_config(country_code)
    return {
        "country":     country_code.upper(),
        "rail":        cfg.rail,
        "currency":    cfg.currency,
        "label":       cfg.label,
        "description": cfg.description,
        "fields":      cfg.fields,
    }
