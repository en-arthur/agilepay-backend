import re
from typing import Any


def validate_destination_identifier(rail: str, identifier: dict[str, Any]) -> list[str]:
    """
    Validate the per-rail identifier blob.
    Returns a list of error strings (empty = valid).
    """
    validators = {
        "PIX":     _validate_pix,
        "SPEI":    _validate_spei,
        "SEPA":    _validate_sepa,
        "ACH":     _validate_ach,
        "FEDWIRE": _validate_fedwire,
        "FPS":     _validate_fps,
        "SWIFT":   _validate_swift,
    }
    fn = validators.get(rail)
    if fn is None:
        return [f"Unsupported rail: {rail}"]
    return fn(identifier)


# ── Per-rail validators ───────────────────────────────────────────────────────

def _validate_pix(id: dict) -> list[str]:
    errors = []
    valid_key_types = {"CPF", "CNPJ", "EMAIL", "PHONE", "RANDOM"}
    if id.get("keyType") not in valid_key_types:
        errors.append(f"keyType must be one of: {', '.join(sorted(valid_key_types))}")
    if not id.get("keyValue"):
        errors.append("keyValue is required")
    return errors


def _validate_spei(id: dict) -> list[str]:
    clabe = str(id.get("clabe", ""))
    if not re.match(r"^\d{18}$", clabe):
        return ["clabe must be an 18-digit number"]
    return []


def _validate_sepa(id: dict) -> list[str]:
    errors = []
    iban = str(id.get("iban", "")).replace(" ", "").upper()
    if not re.match(r"^[A-Z]{2}\d{2}[A-Z0-9]{1,30}$", iban):
        errors.append("iban must be a valid IBAN (e.g. DE89370400440532013000)")
    bic = str(id.get("bic", "")).upper()
    if bic and not re.match(r"^[A-Z]{6}[A-Z0-9]{2}([A-Z0-9]{3})?$", bic):
        errors.append("bic must be a valid 8 or 11 character BIC/SWIFT code")
    return errors


def _validate_ach(id: dict) -> list[str]:
    errors = []
    routing = str(id.get("routingNumber", ""))
    if not re.match(r"^\d{9}$", routing):
        errors.append("routingNumber must be a 9-digit ABA routing number")
    if not id.get("accountNumber"):
        errors.append("accountNumber is required")
    if id.get("accountType") not in {"CHECKING", "SAVINGS"}:
        errors.append("accountType must be CHECKING or SAVINGS")
    return errors


def _validate_fedwire(id: dict) -> list[str]:
    errors = []
    routing = str(id.get("routingNumber", ""))
    if not re.match(r"^\d{9}$", routing):
        errors.append("routingNumber must be a 9-digit ABA routing number")
    if not id.get("accountNumber"):
        errors.append("accountNumber is required")
    return errors


def _validate_fps(id: dict) -> list[str]:
    errors = []
    sort_code = str(id.get("sortCode", ""))
    if not re.match(r"^\d{2}-?\d{2}-?\d{2}$", sort_code):
        errors.append("sortCode must be in format XX-XX-XX")
    account_number = str(id.get("accountNumber", ""))
    if not re.match(r"^\d{8}$", account_number):
        errors.append("accountNumber must be an 8-digit UK account number")
    return errors


def _validate_swift(id: dict) -> list[str]:
    errors = []
    if not id.get("accountNumber"):
        errors.append("accountNumber is required")
    swift = str(id.get("swiftCode", "")).upper()
    if not re.match(r"^[A-Z]{6}[A-Z0-9]{2}([A-Z0-9]{3})?$", swift):
        errors.append("swiftCode must be a valid 8 or 11 character BIC")
    if not id.get("bankName"):
        errors.append("bankName is required")
    return errors
