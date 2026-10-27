"""Fully synthetic fixture builders for the offline security-contract matrix (#38).

Every value here is invented and marked as such: ``ZZ`` in names, the reserved
``.invalid`` TLD (RFC 2606) for every address and host, a checksum-valid but
invented ID, a ``ZZ``-prefixed password and an all-zero plate. Nothing here is
a real person, recipient, vehicle, key or case. Each builder returns a brand
new object on every call, so no test can leak state into another.
"""

from __future__ import annotations

import json
from typing import Any

# Checksum-valid (Israeli ID Luhn variant) but invented; same placeholder as
# tests/conftest.py so no second ID-shaped value enters the repository.
SYNTHETIC_ID = "123456782"
SYNTHETIC_PASSWORD = "ZZ-synthetic-pdf-password-only"  # noqa: S105 - invented fixture
SYNTHETIC_PLATE = "00-000-00"
SYNTHETIC_DOMAIN = "example.invalid"


def synthetic_bundle(**overrides: Any) -> dict[str, Any]:
    """A complete, valid FILING_BUNDLE v1 object. Top-level keys can be overridden."""
    bundle: dict[str, Any] = {
        "version": 1,
        "complainant": {
            "first_name": "ZZפלוני",
            "last_name": "ZZאלמוני",
            "id_number": SYNTHETIC_ID,
            "address": "ZZ רחוב בדוי 0",
            "phone": "000-0000000",
        },
        "pdf_password": SYNTHETIC_PASSWORD,
        "delivery": {
            "recipient_email": f"zz-recipient@{SYNTHETIC_DOMAIN}",
            "smtp_host": f"smtp.{SYNTHETIC_DOMAIN}",
            "smtp_port": 587,
            "smtp_username": f"zz-sender@{SYNTHETIC_DOMAIN}",
            "smtp_app_password": "ZZ-synthetic-app-password",
            "smtp_from": f"zz-sender@{SYNTHETIC_DOMAIN}",
        },
    }
    bundle.update(overrides)
    return bundle


def synthetic_env(bundle: dict[str, Any] | None = None) -> dict[str, str]:
    """An environ mapping holding only FILING_BUNDLE (never os.environ)."""
    return {"FILING_BUNDLE": json.dumps(synthetic_bundle() if bundle is None else bundle)}


def synthetic_case(**overrides: Any) -> dict[str, Any]:
    """A complete, valid single-incident case dict for CaseData.from_dict."""
    case: dict[str, Any] = {
        "complaint_date": "2026-01-02",
        "vehicle_number": SYNTHETIC_PLATE,
        "vehicle_manufacturer": "ZZ-make",
        "vehicle_color": "ZZ-color",
        "offence_date": "2026-01-01",
        "offence_time": "08:00",
        "offence_street": "ZZ רחוב בדוי",
        "offence_city": "ZZ עיר בדויה",
        "offence_description": "ZZ synthetic description",
        "can_identify_driver": "unknown",
        "knows_driver": "no",
    }
    case.update(overrides)
    return case
