"""
ISO 3166-1 alpha-2 → alpha-3 conversion for Lumx.

Lumx requires `country` in alpha-3 format (`GHA`, `BRA`, `DEU`), while the
AgilePay frontend, the Supabase rows and the rails table all use alpha-2
(`GH`, `BR`, `DE`). Sending `GH` to Lumx fails customer creation with 400.

Only countries Lumx can onboard are listed (Supported + High-Risk EDD tiers).
Restricted jurisdictions are deliberately excluded, so attempting to sign up
from one raises a clear 400 instead of an opaque Lumx error.
"""
from __future__ import annotations

# Supported tier + High-Risk (EDD) tier — see
# https://docs.lumx.io/compliance/supported-countries
_ALPHA2_TO_ALPHA3: dict[str, str] = {
    # Supported
    "AL": "ALB", "AD": "AND", "AG": "ATG", "AR": "ARG", "AM": "ARM",
    "AU": "AUS", "AT": "AUT", "AZ": "AZE", "BS": "BHS", "BH": "BHR",
    "BB": "BRB", "BE": "BEL", "BZ": "BLZ", "BJ": "BEN", "BT": "BTN",
    "BA": "BIH", "BW": "BWA", "BR": "BRA", "BN": "BRN", "BI": "BDI",
    "CV": "CPV", "KH": "KHM", "CA": "CAN", "TD": "TCD", "CL": "CHL",
    "KM": "COM", "CG": "COG", "CR": "CRI", "CY": "CYP", "CZ": "CZE",
    "DK": "DNK", "DJ": "DJI", "DM": "DMA", "DO": "DOM", "SV": "SLV",
    "GQ": "GNQ", "ER": "ERI", "EE": "EST", "SZ": "SWZ", "ET": "ETH",
    "FJ": "FJI", "FI": "FIN", "FR": "FRA", "GA": "GAB", "GM": "GMB",
    "GE": "GEO", "DE": "DEU", "GH": "GHA", "GR": "GRC", "GD": "GRD",
    "GT": "GTM", "GN": "GIN", "GW": "GNB", "GY": "GUY", "HN": "HND",
    "HU": "HUN", "IS": "ISL", "IN": "IND", "ID": "IDN", "IE": "IRL",
    "IL": "ISR", "IT": "ITA", "JM": "JAM", "JP": "JPN", "JO": "JOR",
    "KZ": "KAZ", "KI": "KIR", "KW": "KWT", "KG": "KGZ", "LV": "LVA",
    "LS": "LSO", "LR": "LBR", "LI": "LIE", "LT": "LTU", "LU": "LUX",
    "MG": "MDG", "MW": "MWI", "MY": "MYS", "MV": "MDV", "MT": "MLT",
    "MH": "MHL", "MR": "MRT", "MU": "MUS", "MX": "MEX", "FM": "FSM",
    "MD": "MDA", "MN": "MNG", "ME": "MNE", "NR": "NRU", "NL": "NLD",
    "NZ": "NZL", "NI": "NIC", "NE": "NER", "NO": "NOR", "OM": "OMN",
    "PK": "PAK", "PW": "PLW", "PG": "PNG", "PY": "PRY", "PE": "PER",
    "PH": "PHL", "PL": "POL", "PT": "PRT", "QA": "QAT", "RO": "ROU",
    "RW": "RWA", "KN": "KNA", "LC": "LCA", "VC": "VCT", "WS": "WSM",
    "SM": "SMR", "ST": "STP", "SA": "SAU", "SN": "SEN", "RS": "SRB",
    "SC": "SYC", "SL": "SLE", "SG": "SGP", "SK": "SVK", "SI": "SVN",
    "SB": "SLB", "ZA": "ZAF", "KR": "KOR", "SS": "SSD", "ES": "ESP",
    "LK": "LKA", "SR": "SUR", "SE": "SWE", "CH": "CHE", "TJ": "TJK",
    "TH": "THA", "TL": "TLS", "TG": "TGO", "TO": "TON", "TT": "TTO",
    "TN": "TUN", "TR": "TUR", "TM": "TKM", "TV": "TUV", "UG": "UGA",
    "UA": "UKR", "AE": "ARE", "GB": "GBR", "US": "USA", "UY": "URY",
    "UZ": "UZB", "VU": "VUT", "ZM": "ZMB",
    # High-Risk (EDD required, onboarding allowed)
    "AO": "AGO", "BO": "BOL", "BG": "BGR", "BF": "BFA", "CM": "CMR",
    "CF": "CAF", "CN": "CHN", "CO": "COL", "CI": "CIV", "HR": "HRV",
    "CD": "COD", "HT": "HTI", "IQ": "IRQ", "KE": "KEN", "LA": "LAO",
    "LY": "LBY", "ML": "MLI", "MC": "MCO", "MZ": "MOZ", "NA": "NAM",
    "NG": "NGA", "PA": "PAN", "SO": "SOM", "TZ": "TZA", "VN": "VNM",
    "YE": "YEM", "ZW": "ZWE",
}

_ALPHA3 = set(_ALPHA2_TO_ALPHA3.values())


class UnsupportedCountry(ValueError):
    """Raised when a country cannot be onboarded through Lumx."""


def to_alpha3(code: str | None, default: str = "GH") -> str:
    """
    Return the ISO alpha-3 code Lumx expects.

    Accepts alpha-2 ("GH"), alpha-3 ("GHA") or a full country name is NOT
    accepted. Raises UnsupportedCountry for restricted/unknown countries.
    """
    if not code or not str(code).strip():
        code = default

    code = str(code).strip().upper()

    if len(code) == 2:
        alpha3 = _ALPHA2_TO_ALPHA3.get(code)
        if not alpha3:
            raise UnsupportedCountry(
                f"Country '{code}' is not supported for onboarding"
            )
        return alpha3

    if len(code) == 3 and code in _ALPHA3:
        return code

    raise UnsupportedCountry(f"Country '{code}' is not supported for onboarding")
