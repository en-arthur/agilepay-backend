import secrets
import string

import bcrypt

ALPHABET = string.ascii_letters + string.digits


def _nanoid(size: int = 20) -> str:
    """Generate a URL-safe random string of the given length."""
    return "".join(secrets.choice(ALPHABET) for _ in range(size))


def generate_charge_id() -> str:
    """Return a unique charge ID, e.g.  chg_aB3xK9mN1pQr2sT4"""
    return f"chg_{_nanoid(20)}"


def generate_link_id() -> str:
    """Return a unique payment-link ID, e.g.  lnk_aB3xK9mN1pQ"""
    return f"lnk_{_nanoid(12)}"


def generate_api_key(environment: str) -> tuple[str, str, str, str]:
    """
    Generate a new API key.

    Returns
    -------
    (raw_key, key_hash, prefix, last_four)
        raw_key   — shown ONCE to the user, never stored in plaintext
        key_hash  — bcrypt hash to persist in the DB
        prefix    — "sk_live_" or "sk_test_"
        last_four — last 4 chars for UI display
    """
    env = "live" if environment == "LIVE" else "test"
    prefix = f"sk_{env}_"
    # 32 alphanumeric chars after the prefix
    secret = "".join(secrets.choice(ALPHABET) for _ in range(32))
    raw_key = f"{prefix}{secret}"
    last_four = raw_key[-4:]
    key_hash = bcrypt.hashpw(raw_key.encode(), bcrypt.gensalt(12)).decode()
    return raw_key, key_hash, prefix, last_four
