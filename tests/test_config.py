import copy
import json

import pytest

from tests.test_cli import BUNDLE
from traffic_complaint_form.config import ERROR, BundleError, FilingConfig


def test_complete_bundle_and_safe_repr():
    config = FilingConfig.from_env({"FILING_BUNDLE": json.dumps(BUNDLE)})
    assert config.complainant.id_number == BUNDLE["complainant"]["id_number"]
    assert BUNDLE["pdf_password"] not in repr(config)


@pytest.mark.parametrize("key", list(BUNDLE))
def test_every_root_key_required(key):
    bundle = copy.deepcopy(BUNDLE)
    del bundle[key]
    with pytest.raises(BundleError, match="FILING_BUNDLE"):
        FilingConfig.from_env({"FILING_BUNDLE": json.dumps(bundle)})


@pytest.mark.parametrize("section", ["complainant", "delivery"])
def test_every_nested_key_required(section):
    for key in BUNDLE[section]:
        bundle = copy.deepcopy(BUNDLE)
        del bundle[section][key]
        with pytest.raises(BundleError):
            FilingConfig.from_env({"FILING_BUNDLE": json.dumps(bundle)})


@pytest.mark.parametrize(
    "path,value",
    [
        (("version",), True),
        (("version",), 2),
        (("pdf_password",), "short"),
        (("pdf_password",), "x" * 128),
        (("pdf_password",), "x\n" * 20),
        (("complainant", "id_number"), "000000001"),
        (("complainant", "first_name"), 1),
        (("delivery", "smtp_port"), True),
        (("delivery", "smtp_port"), 0),
        (("delivery", "smtp_port"), "587"),
        (("delivery", "recipient_email"), "not-an-email"),
        (("delivery", "smtp_from"), "a@example.com\nBcc:bad@example.com"),
        (("delivery", "smtp_username"), ""),
        (("delivery", "smtp_app_password"), None),
    ],
)
def test_strict_schema_never_echoes_invalid_data(path, value):
    bundle = copy.deepcopy(BUNDLE)
    target = bundle
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(BundleError) as error:
        FilingConfig.from_env({"FILING_BUNDLE": json.dumps(bundle)})
    assert str(error.value).startswith(ERROR)


@pytest.mark.parametrize(
    "raw",
    [
        "[]",
        "null",
        '"value"',
        "not-json-secret",
        '{"version":1,"version":1}',
        '{"attacker-private-field":1}',
        "x" * 50000,
    ],
)
def test_malformed_duplicate_and_unknown_fields_fail_closed(raw):
    with pytest.raises(BundleError) as error:
        FilingConfig.from_env({"FILING_BUNDLE": raw})
    assert str(error.value).startswith(ERROR)


def test_diagnostic_code_cannot_echo_arbitrary_value():
    assert BundleError("private-canary").code == "schema"
    assert "private-canary" not in str(BundleError("private-canary"))


def test_known_field_diagnostic_and_no_values():
    bundle = copy.deepcopy(BUNDLE)
    bundle["pdf_password"] = "private-short"  # noqa: S105 - invented validation fixture
    with pytest.raises(BundleError) as error:
        FilingConfig.from_env({"FILING_BUNDLE": json.dumps(bundle)})
    assert error.value.code == "pdf_password"
    assert "private-short" not in str(error.value)


# --- Payload v2 per-call override (docs/CASE_DATA.md) ---

from traffic_complaint_form.config import FilingOverride, PayloadError  # noqa: E402

OVERRIDE = {
    "complainant": {
        "first_name": "דנה",
        "last_name": "לוי",
        "id_number": "000000018",
        "address": "רחוב המבחן 2",
        "phone": "050-1111111",
    },
    "recipient_email": "caller@example.com",
    "pdf_password": "invented-per-call-password",
}


def test_override_absent_returns_none():
    assert FilingOverride.from_payload({"vehicle_number": "12-345-67"}) is None
    assert FilingOverride.from_payload({}) is None


def test_override_valid_roundtrip():
    override = FilingOverride.from_payload(dict(OVERRIDE))
    assert override.recipient_email == "caller@example.com"
    assert override.pdf_password == "invented-per-call-password"  # noqa: S105 - invented fixture
    assert override.complainant.id_number == "000000018"
    assert "caller@example.com" not in repr(override)


@pytest.mark.parametrize("missing", ["complainant", "recipient_email", "pdf_password"])
def test_override_is_all_or_nothing(missing):
    payload = {key: value for key, value in OVERRIDE.items() if key != missing}
    with pytest.raises(PayloadError) as err:
        FilingOverride.from_payload(payload)
    assert err.value.code == "partial_override"


@pytest.mark.parametrize(
    "key,bad,code",
    [
        ("id_number", "123456789", "complainant.id_number"),  # checksum fails
        ("id_number", "123", "complainant.id_number"),
        ("id_number", "00000001a", "complainant.id_number"),
        ("first_name", "", "complainant.first_name"),
        ("phone", "050\n111", "complainant.phone"),
    ],
)
def test_override_complainant_validation(key, bad, code):
    payload = json.loads(json.dumps(OVERRIDE))
    payload["complainant"][key] = bad
    with pytest.raises(PayloadError) as err:
        FilingOverride.from_payload(payload)
    assert err.value.code == code
    if bad:
        assert bad not in str(err.value)


def test_override_complainant_unknown_key_rejected():
    payload = json.loads(json.dumps(OVERRIDE))
    payload["complainant"]["nickname"] = "canary"
    with pytest.raises(PayloadError) as err:
        FilingOverride.from_payload(payload)
    assert err.value.code == "complainant"


@pytest.mark.parametrize(
    "bad",
    ["short", "x" * 128, "000000018"],  # too short / too many bytes / equals the ID
)
def test_override_password_rules(bad):
    payload = dict(OVERRIDE, pdf_password=bad)
    with pytest.raises(PayloadError) as err:
        FilingOverride.from_payload(payload)
    assert err.value.code == "pdf_password"


@pytest.mark.parametrize("bad", ["not-an-email", "@example.com", "a@b\nc", ""])
def test_override_email_validation(bad):
    payload = dict(OVERRIDE, recipient_email=bad)
    with pytest.raises(PayloadError) as err:
        FilingOverride.from_payload(payload)
    assert err.value.code == "recipient_email"


def test_override_diagnostics_never_echo_values():
    payload = json.loads(json.dumps(OVERRIDE))
    payload["complainant"]["id_number"] = "canary-id"
    payload["pdf_password"] = "canary-password"  # noqa: S105 - invented fixture
    payload["recipient_email"] = "canary@example.com"
    with pytest.raises(PayloadError) as err:
        FilingOverride.from_payload(payload)
    message = str(err.value)
    assert "canary" not in message
