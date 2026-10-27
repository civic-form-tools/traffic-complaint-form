"""Offline security-contract matrix (#38). See tests/SECURITY_MATRIX.md.

Runs only against interfaces already on main. Rows that depend on #34/#35
are explicit skips naming the PR, and are never counted as executed. Known
gaps on main are strict xfails, so they flip to a failure (and must be
promoted) the moment main changes. Every test here runs with sockets and
SMTP blocked, and with os.environ and secret files unreadable.
"""

from __future__ import annotations

import builtins
import copy
import json
import logging
import os
import smtplib
import socket
from pathlib import Path

import pytest

from tests import fixtures_synthetic as fx
from traffic_complaint_form import mail
from traffic_complaint_form.config import BundleError, FilingConfig
from traffic_complaint_form.crypto import CaseDecryptionError, decrypt_payload, encrypt_payload, generate_keypair
from traffic_complaint_form.models import CaseData, TriState

PENDING_34 = "pending #34 (interface not on main; not executed)"
PENDING_35 = "pending #35 (interface not on main; not executed)"
SECRET_FILE_MARKERS = (".env", "FILING_BUNDLE", "case-data-private", "id_rsa")


class OfflineViolation(AssertionError):
    pass


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    """Fail any test that reaches the network, real SMTP, os.environ or a secret file."""

    def no_network(*_a, **_k):
        raise OfflineViolation("network access attempted")

    monkeypatch.setattr(socket.socket, "connect", no_network)
    monkeypatch.setattr(socket, "create_connection", no_network)
    monkeypatch.setattr(smtplib.SMTP, "__init__", no_network)
    monkeypatch.setattr(smtplib.SMTP_SSL, "__init__", no_network)
    real_open = builtins.open

    def guarded_open(file, *args, **kwargs):
        name = os.fsdecode(file) if isinstance(file, (str, bytes, os.PathLike)) else ""
        if any(marker in Path(name).name for marker in SECRET_FILE_MARKERS):
            raise OfflineViolation(f"secret-file read attempted: {Path(name).name}")
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", guarded_open)
    for key in list(os.environ):
        if key in {"FILING_BUNDLE", "CASE_DATA_PRIVATE_KEY"} or key.startswith("SMTP_"):
            monkeypatch.delenv(key)


def parse(bundle):
    return FilingConfig.from_env(fx.synthetic_env(bundle))


def code_of(bundle) -> str:
    with pytest.raises(BundleError) as info:
        parse(bundle)
    return info.value.code


# --- Guard self-tests (planted violations) --------------------------------


def test_guard_blocks_socket():
    with pytest.raises(OfflineViolation):
        socket.create_connection(("smtp.example.invalid", 25))


def test_guard_blocks_real_smtp():
    with pytest.raises(OfflineViolation):
        smtplib.SMTP("smtp.example.invalid", 587)


def test_guard_blocks_secret_file(tmp_path):
    planted = tmp_path / ".env"
    planted.write_bytes(b"")  # pathlib write uses io.open, not builtins.open
    with pytest.raises(OfflineViolation):
        open(planted)  # noqa: SIM115


def test_guard_scrubs_environment():
    assert "FILING_BUNDLE" not in os.environ
    assert "CASE_DATA_PRIVATE_KEY" not in os.environ


# --- Fixture builders ------------------------------------------------------


def test_builders_return_fresh_objects():
    first, second = fx.synthetic_bundle(), fx.synthetic_bundle()
    assert first == second and first is not second
    first["delivery"]["recipient_email"] = "mutated@example.invalid"
    first["complainant"]["first_name"] = "mutated"
    assert fx.synthetic_bundle() == second
    case_a, case_b = fx.synthetic_case(), fx.synthetic_case()
    case_a["vehicle_number"] = "mutated"
    assert case_b["vehicle_number"] == fx.SYNTHETIC_PLATE


def test_builders_are_valid_and_clearly_invented():
    config = parse(None)
    assert config.complainant.id_number == fx.SYNTHETIC_ID
    blob = json.dumps(fx.synthetic_bundle(), ensure_ascii=False)
    for key in ("recipient_email", "smtp_host", "smtp_username", "smtp_from"):
        assert fx.synthetic_bundle()["delivery"][key].endswith(".invalid")
    assert "ZZ" in blob and fx.SYNTHETIC_PASSWORD.startswith("ZZ")
    CaseData.from_dict(fx.synthetic_case())


# --- Bundle: missing, partial, wrong type, oversized -----------------------


@pytest.mark.parametrize("section", ["complainant", "delivery"])
def test_partial_sections_rejected_with_section_code(section):
    for key in fx.synthetic_bundle()[section]:
        bundle = fx.synthetic_bundle()
        del bundle[section][key]
        assert code_of(bundle) == section


@pytest.mark.parametrize(
    "path,value,code",
    [
        (("version",), "1", "version"),
        (("complainant",), [], "complainant"),
        (("complainant", "phone"), 0, "complainant.phone"),
        (("pdf_password",), None, "pdf_password"),
        (("delivery", "smtp_port"), "587", "delivery.smtp_port"),
        (("delivery", "smtp_port"), True, "delivery.smtp_port"),
        (("delivery", "smtp_port"), 0, "delivery.smtp_port"),
        (("delivery", "recipient_email"), ["zz@example.invalid"], "delivery.recipient_email"),
    ],
)
def test_wrong_types_rejected_with_field_code(path, value, code):
    bundle = fx.synthetic_bundle()
    target = bundle
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    assert code_of(bundle) == code


def test_extra_key_rejected():
    assert code_of(fx.synthetic_bundle(extra="ZZ")) == "root"


def test_oversized_bundle_rejected_before_parsing():
    bundle = fx.synthetic_bundle()
    bundle["complainant"]["address"] = "ZZ" * (25 * 1024)
    assert code_of(bundle) == "missing_or_oversized"


@pytest.mark.skip(reason=PENDING_34 + ": per-field length caps for case/override fields")
def test_oversized_case_fields_rejected():
    raise AssertionError("not executed")


# --- Email header injection in delivery addresses -------------------------


@pytest.mark.parametrize("key", ["recipient_email", "smtp_from", "smtp_username"])
@pytest.mark.parametrize(
    "value",
    [
        "zz@example.invalid\r\nBcc: zz-other@example.invalid",
        "zz@example.invalid\nBcc: zz-other@example.invalid",
        "zz@example.invalid\x00",
        "zz@example.invalid, zz-other@example.invalid",
        "ZZ Name <zz@example.invalid>",
        "zz name@example.invalid",
    ],
)
def test_header_injection_rejected(key, value):
    bundle = fx.synthetic_bundle()
    bundle["delivery"][key] = value
    assert code_of(bundle) == "delivery." + key


@pytest.mark.xfail(
    strict=True,
    raises=Exception,
    reason="gap on main: config._email lets email.errors.HeaderParseError (not a ValueError) escape "
    "the BundleError boundary; its message echoes part of the address and cli.main does not catch it",
)
@pytest.mark.parametrize("value", ["zz@@example.invalid", "@example.invalid", "zz@"])
def test_malformed_address_stays_inside_bundle_error(value):
    bundle = fx.synthetic_bundle()
    bundle["delivery"]["recipient_email"] = value
    with pytest.raises(BundleError):
        parse(bundle)


# --- Value-free diagnostics -------------------------------------------------


@pytest.mark.parametrize(
    "mutate",
    [
        lambda b: b["complainant"].update(id_number="123456789"),
        lambda b: b.update(pdf_password=fx.SYNTHETIC_ID),
        lambda b: b["delivery"].update(recipient_email="zz-planted\r\n@example.invalid"),
        lambda b: b["delivery"].update(smtp_port=70000),
    ],
)
def test_bundle_diagnostics_never_echo_values(mutate):
    bundle = fx.synthetic_bundle()
    mutate(bundle)
    with pytest.raises(BundleError) as info:
        parse(bundle)
    message = str(info.value) + repr(info.value)
    for planted in ("123456789", fx.SYNTHETIC_ID, "zz-planted", "70000", fx.SYNTHETIC_PASSWORD):
        assert planted not in message


def test_unknown_code_collapses_to_schema():
    assert BundleError("ZZ-planted-value").code == "schema"
    assert "ZZ-planted-value" not in str(BundleError("ZZ-planted-value"))


def test_config_repr_withholds_secrets():
    text = repr(parse(None))
    for planted in (fx.SYNTHETIC_PASSWORD, "ZZ-synthetic-app-password", "zz-recipient", fx.SYNTHETIC_ID):
        assert planted not in text


def test_case_diagnostics_name_keys_not_values():
    case = fx.synthetic_case(offence_time="ZZ-planted-time", complaint_date="ZZ-planted-date")
    del case["vehicle_color"]
    with pytest.raises(ValueError) as info:
        CaseData.from_dict(case)
    message = str(info.value)
    assert "vehicle_color" in message and "offence_time" in message
    assert "ZZ-planted" not in message


@pytest.mark.xfail(
    strict=True,
    reason="gap on main: a shape-valid impossible date reaches strptime, whose message echoes the value "
    "(cli withholds it today; #34's validate_filing must not)",
)
@pytest.mark.parametrize("value", ["2026-13-01", "2026-00-10"])
def test_impossible_date_diagnostic_is_value_free(value):
    with pytest.raises(ValueError) as info:
        CaseData.from_dict(fx.synthetic_case(offence_date=value))
    assert value not in str(info.value)


@pytest.mark.parametrize("incidents", [[], "ZZ", [None], [{"offence_date": "ZZ-planted"}]])
def test_case_incident_shapes_rejected_without_values(incidents):
    with pytest.raises(ValueError) as info:
        CaseData.from_dict(fx.synthetic_case(incidents=incidents))
    assert "ZZ-planted" not in str(info.value)


# --- Tri-state parsing -----------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("yes", TriState.YES),
        (" כן ", TriState.YES),
        ("TRUE", TriState.YES),
        ("1", TriState.YES),
        ("no", TriState.NO),
        ("לא", TriState.NO),
        ("0", TriState.NO),
        ("", TriState.UNKNOWN),
        (None, TriState.UNKNOWN),
        ("לא ידוע", TriState.UNKNOWN),
    ],
)
def test_tristate_accepts_only_known_tokens(raw, expected):
    assert TriState.parse(raw) is expected


@pytest.mark.parametrize("raw", ["maybe", "yes!", "2", "ZZ"])
def test_tristate_rejects_unknown_tokens(raw):
    with pytest.raises(ValueError):
        TriState.parse(raw)


@pytest.mark.xfail(strict=True, reason="gap on main: TriState.parse echoes the input (fixed in #34)")
def test_tristate_diagnostic_is_value_free():
    with pytest.raises(ValueError) as info:
        TriState.parse("ZZ-planted")
    assert "ZZ-planted" not in str(info.value)


# --- Mail: fixed templates, mocked SMTP, cross-call isolation -------------


class FakeSMTP:
    instances: list[FakeSMTP] = []

    def __init__(self, host, port, timeout):
        self.host, self.port, self.sent = host, port, []
        FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def ehlo(self):
        pass

    def starttls(self):
        pass

    def login(self, user, password):
        self.user = user

    def send_message(self, message):
        self.sent.append(message)
        return {}


def send(config, attachment, *, test_mode, vehicle=fx.SYNTHETIC_PLATE):
    mail.send_encrypted_pdf(
        smtp_host=config.delivery["smtp_host"],
        smtp_port=config.delivery["smtp_port"],
        smtp_username=config.delivery["smtp_username"],
        smtp_password=config.delivery["smtp_app_password"],
        from_address=config.delivery["smtp_from"],
        recipient=config.delivery["recipient_email"],
        attachment_path=attachment,
        vehicle_number=vehicle,
        offence_date="01/01/2026",
        test_mode=test_mode,
        smtp_factory=FakeSMTP,
    )
    return FakeSMTP.instances[-1].sent[-1]


@pytest.mark.parametrize("test_mode", [False, True])
def test_mail_uses_fixed_templates_and_logs_no_values(tmp_path, caplog, test_mode):
    attachment = tmp_path / "complaint.pdf"
    attachment.write_bytes(b"%PDF-synthetic")
    caplog.set_level(logging.DEBUG)
    message = send(parse(None), attachment, test_mode=test_mode)
    assert message.get_body().get_content().strip() == (mail.BODY_TEST if test_mode else mail.BODY_REAL).strip()
    prefix = "[TEST] " if test_mode else ""
    assert message["Subject"] == f"{prefix}Traffic complaint form - vehicle {fx.SYNTHETIC_PLATE} - 01/01/2026"
    assert fx.SYNTHETIC_PASSWORD not in message.as_string()
    for planted in ("zz-recipient", "zz-sender", fx.SYNTHETIC_PLATE, "ZZ-synthetic-app-password"):
        assert planted not in caplog.text


def test_two_parses_and_sends_share_no_state(tmp_path):
    attachment = tmp_path / "complaint.pdf"
    attachment.write_bytes(b"%PDF-synthetic")
    first_bundle = fx.synthetic_bundle()
    second_bundle = copy.deepcopy(first_bundle)
    second_bundle["delivery"]["recipient_email"] = "zz-second@example.invalid"
    second_bundle["pdf_password"] = "ZZ-second-synthetic-password"  # noqa: S105 - invented fixture
    first, second = parse(first_bundle), parse(second_bundle)
    first_message = send(first, attachment, test_mode=True, vehicle="00-000-01")
    second_message = send(second, attachment, test_mode=True, vehicle="00-000-02")
    assert first.delivery is not second.delivery
    assert first.pdf_password != second.pdf_password
    assert first_message["To"] == "zz-recipient@example.invalid"
    assert second_message["To"] == "zz-second@example.invalid"
    assert "00-000-01" not in second_message["Subject"]
    first_bundle["delivery"]["recipient_email"] = "mutated@example.invalid"
    assert first.delivery["recipient_email"] == "zz-recipient@example.invalid"


# --- Crypto boundary --------------------------------------------------------


def test_wrong_key_decryption_error_is_value_free():
    public, _ = generate_keypair()
    _, other_private = generate_keypair()
    ciphertext = encrypt_payload(public, b'{"vehicle_number": "ZZ-planted"}')
    with pytest.raises(CaseDecryptionError) as info:
        decrypt_payload(other_private, ciphertext)
    assert "ZZ-planted" not in str(info.value) and other_private not in str(info.value)


# --- Proposed interfaces: explicit pending rows ----------------------------


@pytest.mark.skip(reason=PENDING_34 + ": FilingOverride all-or-nothing")
def test_filing_override_all_or_nothing():
    raise AssertionError("not executed")


@pytest.mark.skip(reason=PENDING_34 + ": PayloadError value-free codes / validate_filing codes")
def test_payload_error_codes_value_free():
    raise AssertionError("not executed")


@pytest.mark.skip(reason=PENDING_34 + ": plate-shaped vehicle_number validation")
def test_plate_shaped_vehicle_number():
    raise AssertionError("not executed")


@pytest.mark.skip(reason=PENDING_34 + ": per-call body variant and nonce correlation")
def test_per_call_body_and_nonce():
    raise AssertionError("not executed")


@pytest.mark.skip(reason=PENDING_35 + ": HTTP bearer and toolset invariants")
def test_http_bearer_and_toolset():
    raise AssertionError("not executed")
