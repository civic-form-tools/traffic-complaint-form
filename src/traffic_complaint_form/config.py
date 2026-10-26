"""Atomic filing configuration. Never include supplied data in diagnostics or repr."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from email.headerregistry import Address

from .models import Complainant, is_valid_israeli_id


class BundleError(ValueError):
    """Only parser-owned diagnostic codes can cross the log boundary."""

    def __init__(self, code: str = "schema"):
        allowed = {
            "schema",
            "missing_or_oversized",
            "json",
            "duplicate_key",
            "root",
            "version",
            "complainant",
            "complainant.id_number",
            "pdf_password",
            "delivery",
            "delivery.recipient_email",
            "delivery.smtp_from",
            "delivery.smtp_username",
            "delivery.smtp_host",
            "delivery.smtp_app_password",
            "delivery.smtp_port",
            "complainant.first_name",
            "complainant.last_name",
            "complainant.address",
            "complainant.phone",
        }
        self.code = code if code in allowed else "schema"
        super().__init__(ERROR + "; check: " + self.code)


ERROR = "FILING_BUNDLE is missing or invalid; see docs/SECRETS.md (values withheld)"


def _object(value: object, keys: set[str], code: str = "schema") -> dict:
    if not isinstance(value, dict) or set(value) != keys:
        raise BundleError(code)
    return value


def _text(value: object, code: str = "schema") -> str:
    if not isinstance(value, str) or not value.strip() or any(c in value for c in "\r\n\x00"):
        raise BundleError(code)
    return value


def _email(value: object, code: str = "schema") -> str:
    text = _text(value, code)
    try:
        address = Address(addr_spec=text)
        if not address.username or not address.domain:
            raise ValueError
    except ValueError:
        raise BundleError(code) from None
    return text


def _unique(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise BundleError("duplicate_key")
        result[key] = value
    return result


@dataclass(frozen=True, repr=False)
class FilingConfig:
    complainant: Complainant
    pdf_password: str
    delivery: dict

    @classmethod
    def from_env(cls, environ: Mapping[str, str]) -> FilingConfig:
        """No separate-secret fallback, including sample/test/dry runs."""
        try:
            raw = environ.get("FILING_BUNDLE", "")
            if not raw or len(raw.encode()) > 48 * 1024:
                raise BundleError("missing_or_oversized")
            data = _object(
                json.loads(raw, object_pairs_hook=_unique),
                {"version", "complainant", "pdf_password", "delivery"},
                "root",
            )
            if type(data["version"]) is not int or data["version"] != 1:
                raise BundleError("version")
            person = _object(
                data["complainant"], {"first_name", "last_name", "id_number", "address", "phone"}, "complainant"
            )
            person = {k: _text(v, "complainant." + k) for k, v in person.items()}
            if len(person["id_number"]) != 9 or not person["id_number"].isascii() or not person["id_number"].isdigit():
                raise BundleError("complainant.id_number")
            if not is_valid_israeli_id(person["id_number"]):
                raise BundleError("complainant.id_number")
            password = _text(data["pdf_password"], "pdf_password")
            if len(password) < 16 or len(password.encode("utf-8")) > 127 or password.strip() == person["id_number"]:
                raise BundleError("pdf_password")
            delivery = _object(
                data["delivery"],
                {"recipient_email", "smtp_host", "smtp_port", "smtp_username", "smtp_app_password", "smtp_from"},
                "delivery",
            )
            delivery = dict(delivery)
            for key in ("recipient_email", "smtp_from", "smtp_username"):
                delivery[key] = _email(delivery[key], "delivery." + key)
            for key in ("smtp_host", "smtp_app_password"):
                delivery[key] = _text(delivery[key], "delivery." + key)
            if type(delivery["smtp_port"]) is not int or not 1 <= delivery["smtp_port"] <= 65535:
                raise BundleError("delivery.smtp_port")
            return cls(Complainant(**person), password, delivery)
        except BundleError:
            raise
        except json.JSONDecodeError:
            raise BundleError("json") from None
        except (ValueError, TypeError, KeyError, RecursionError):
            raise BundleError() from None
