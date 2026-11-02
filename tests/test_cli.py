import json
import logging

import pikepdf
import pytest

from traffic_complaint_form import cli
from traffic_complaint_form.cli import is_test_mode, main

BUNDLE = {
    "version": 1,
    "complainant": {
        "first_name": "משה",
        "last_name": "כהן",
        "id_number": "123456782",
        "address": "רחוב הדוגמה 1",
        "phone": "050-0000000",
    },
    "pdf_password": "invented-test-password-only",
    "delivery": {
        "recipient_email": "recipient@example.com",
        "smtp_host": "smtp.example.com",
        "smtp_port": 587,
        "smtp_username": "sender@example.com",
        "smtp_app_password": "invented-app-password",
        "smtp_from": "sender@example.com",
    },
}


def set_env(monkeypatch, bundle=None):
    monkeypatch.setenv("FILING_BUNDLE", json.dumps(BUNDLE if bundle is None else bundle))


def test_dry_run_sample_end_to_end(monkeypatch, tmp_path, caplog):
    set_env(monkeypatch)
    with caplog.at_level(logging.INFO):
        assert main(["--sample", "--out-dir", str(tmp_path), "--dry-run"]) == 0
    pdfs = list(tmp_path.glob("*.pdf"))
    assert len(pdfs) == 1
    with pikepdf.open(pdfs[0], password=BUNDLE["pdf_password"]) as pdf:
        assert len(pdf.pages) == 1
    with pytest.raises(pikepdf.PasswordError):
        pikepdf.open(pdfs[0])
    for value in [*BUNDLE["complainant"].values(), BUNDLE["pdf_password"], *BUNDLE["delivery"].values()]:
        if isinstance(value, str):
            assert value not in caplog.text


@pytest.mark.parametrize("raw", ["", "{}", "[]", '{"pdf_password":"attacker-password"}', '{"secret":"private"'])
def test_missing_partial_bundle_fails_closed_even_with_legacy(monkeypatch, tmp_path, caplog, raw):
    monkeypatch.setenv("FILING_BUNDLE", raw)
    for key in ("FIRST_NAME", "LAST_NAME", "ID", "ADDRESS", "PHONE"):
        monkeypatch.setenv("COMPLAINANT_" + key, "legacy-private-canary")
    monkeypatch.setenv("PDF_PASSWORD", "attacker-password")
    monkeypatch.setattr(cli, "render_form", lambda *a, **k: pytest.fail("must not render"))
    monkeypatch.setattr(cli, "send_encrypted_pdf", lambda **k: pytest.fail("must not send"))
    assert main(["--sample", "--out-dir", str(tmp_path), "--dry-run"]) == 2
    assert not list(tmp_path.iterdir())
    assert "FILING_BUNDLE" in caplog.text
    assert "legacy-private-canary" not in caplog.text
    assert "attacker-password" not in caplog.text
    assert "private" not in caplog.text


def test_send_path_calls_mail(monkeypatch, tmp_path):
    set_env(monkeypatch)
    calls = {}
    monkeypatch.setattr(cli, "send_encrypted_pdf", lambda **kw: calls.update(kw))
    assert main(["--sample", "--out-dir", str(tmp_path)]) == 0
    assert calls["recipient"] == BUNDLE["delivery"]["recipient_email"]
    assert calls["smtp_port"] == 587
    assert calls["smtp_password"] == BUNDLE["delivery"]["smtp_app_password"]


@pytest.mark.parametrize("stage", ["render_form", "encrypt_pdf", "send_encrypted_pdf"])
def test_failures_do_not_log_exception_values(monkeypatch, tmp_path, caplog, capsys, stage):
    set_env(monkeypatch)

    def fail(*args, **kwargs):
        raise RuntimeError(json.dumps(BUNDLE))

    monkeypatch.setattr(cli, stage, fail)
    assert main(["--sample", "--out-dir", str(tmp_path)]) == 1
    output = caplog.text + capsys.readouterr().err
    assert BUNDLE["pdf_password"] not in output
    assert BUNDLE["complainant"]["id_number"] not in output
    assert BUNDLE["delivery"]["smtp_app_password"] not in output


@pytest.mark.parametrize("test_mode", ["true", "false"])
def test_never_disable_encryption(monkeypatch, tmp_path, test_mode):
    set_env(monkeypatch)
    monkeypatch.setenv("TEST_MODE", test_mode)
    monkeypatch.setenv("ENCRYPT_OUTPUT", "false")
    assert main(["--sample", "--out-dir", str(tmp_path), "--dry-run"]) == 4


def test_overflow_returns_3(monkeypatch, tmp_path):
    set_env(monkeypatch)
    monkeypatch.setattr(cli, "html_to_pdf", lambda *a, **k: 2)
    assert main(["--sample", "--out-dir", str(tmp_path), "--dry-run"]) == 3


def test_case_json_and_invalid_input(monkeypatch, tmp_path, caplog):
    set_env(monkeypatch)
    bad = tmp_path / "bad.json"
    bad.write_text('{"can_identify_driver":"private-case-canary"}')
    assert main(["--case-json", str(bad), "--out-dir", str(tmp_path / "o"), "--dry-run"]) == 2
    assert "private-case-canary" not in caplog.text


def test_encrypted_case_roundtrip_and_log_privacy(monkeypatch, tmp_path, caplog):
    set_env(monkeypatch)
    from traffic_complaint_form.crypto import encrypt_payload, generate_keypair
    from traffic_complaint_form.sample import sample_case

    public_b64, private_b64 = generate_keypair()
    case_file = tmp_path / "case.enc"
    case_file.write_text(encrypt_payload(public_b64, b"{}"))
    assert main(["--case-encrypted", str(case_file), "--dry-run"]) == 2
    monkeypatch.setenv("CASE_DATA_PRIVATE_KEY", private_b64)
    assert main(["--case-encrypted", str(case_file), "--dry-run"]) == 2
    monkeypatch.setattr(cli.CaseData, "from_dict", lambda data: sample_case())
    with caplog.at_level(logging.INFO):
        assert main(["--case-encrypted", str(case_file), "--out-dir", str(tmp_path / "out"), "--dry-run"]) == 0
    assert "12-345-67" not in caplog.text
    assert "12-345-67" not in next((tmp_path / "out").glob("*.pdf")).name


def test_is_test_mode():
    assert is_test_mode({}) is True
    assert is_test_mode({"TEST_MODE": "false"}) is False


def test_validation_only_never_renders_or_sends(monkeypatch, caplog):
    set_env(monkeypatch)
    monkeypatch.setattr(cli, "render_form", lambda *a, **k: pytest.fail("must not render"))
    monkeypatch.setattr(cli, "send_encrypted_pdf", lambda **k: pytest.fail("must not send"))
    with caplog.at_level(logging.INFO):
        assert main(["--validate-config"]) == 0
    assert "validation OK" in caplog.text


# --- Payload v2 per-call override (docs/CASE_DATA.md, docs/MCP.md) ---

CASE = {
    "vehicle_number": "98-765-43",
    "vehicle_manufacturer": "טויוטה",
    "vehicle_color": "לבן",
    "offence_date": "2026-01-15",
    "offence_time": "14:30",
    "offence_street": "רחוב הדוגמה",
    "offence_city": "ירושלים",
    "offence_description": "הרכב חנה על המדרכה.",
}

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


def _seal(payload_dict, public_b64):
    from traffic_complaint_form.crypto import encrypt_payload

    return encrypt_payload(public_b64, json.dumps(payload_dict, ensure_ascii=False).encode("utf-8"))


def test_per_call_override_end_to_end(monkeypatch, tmp_path, caplog):
    set_env(monkeypatch)
    from traffic_complaint_form.crypto import generate_keypair

    public_b64, private_b64 = generate_keypair()
    monkeypatch.setenv("CASE_DATA_PRIVATE_KEY", private_b64)
    enc = tmp_path / "case.enc"
    enc.write_text(_seal({**CASE, **OVERRIDE}, public_b64))
    calls = {}
    monkeypatch.setattr(cli, "send_encrypted_pdf", lambda **kw: calls.update(kw))
    with caplog.at_level(logging.INFO):
        assert main(["--case-encrypted", str(enc), "--out-dir", str(tmp_path / "out")]) == 0
    # Delivery goes to the per-call recipient, flagged per-call for the body variant
    assert calls["recipient"] == "caller@example.com"
    assert calls["per_call_password"] is True
    # The PDF opens with the per-call password, NOT the bundle password
    pdf = next((tmp_path / "out").glob("*.pdf"))
    with pikepdf.open(pdf, password="invented-per-call-password") as doc:
        assert len(doc.pages) == 1
    with pytest.raises(pikepdf.PasswordError):
        pikepdf.open(pdf, password=BUNDLE["pdf_password"])
    # No per-call value and no bundle value ever reaches the log
    private_values = [
        "invented-per-call-password",
        "caller@example.com",
        "000000018",
        "050-1111111",
        BUNDLE["pdf_password"],
        BUNDLE["delivery"]["recipient_email"],
        BUNDLE["complainant"]["id_number"],
    ]
    for value in private_values:
        assert value not in caplog.text
        assert value not in pdf.name


def test_partial_override_fails_closed(monkeypatch, tmp_path, caplog):
    set_env(monkeypatch)
    from traffic_complaint_form.crypto import generate_keypair

    public_b64, private_b64 = generate_keypair()
    monkeypatch.setenv("CASE_DATA_PRIVATE_KEY", private_b64)
    enc = tmp_path / "case.enc"
    enc.write_text(_seal({**CASE, "recipient_email": "caller@example.com"}, public_b64))
    monkeypatch.setattr(cli, "send_encrypted_pdf", lambda **k: pytest.fail("must not send"))
    monkeypatch.setattr(cli, "render_form", lambda *a, **k: pytest.fail("must not render"))
    with caplog.at_level(logging.INFO):
        assert main(["--case-encrypted", str(enc), "--out-dir", str(tmp_path / "out")]) == 2
    assert "partial_override" in caplog.text
    assert "caller@example.com" not in caplog.text
    assert not list((tmp_path / "out").glob("*.pdf")) if (tmp_path / "out").exists() else True


def test_non_object_payload_fails_closed(monkeypatch, tmp_path, caplog):
    set_env(monkeypatch)
    from traffic_complaint_form.crypto import generate_keypair

    public_b64, private_b64 = generate_keypair()
    monkeypatch.setenv("CASE_DATA_PRIVATE_KEY", private_b64)
    enc = tmp_path / "case.enc"
    enc.write_text(_seal(["not", "an", "object"], public_b64))
    assert main(["--case-encrypted", str(enc), "--out-dir", str(tmp_path / "out"), "--dry-run"]) == 2


def test_case_json_also_accepts_override(monkeypatch, tmp_path):
    set_env(monkeypatch)
    payload = tmp_path / "case.json"
    payload.write_text(json.dumps({**CASE, **OVERRIDE}, ensure_ascii=False))
    calls = {}
    monkeypatch.setattr(cli, "send_encrypted_pdf", lambda **kw: calls.update(kw))
    assert main(["--case-json", str(payload), "--out-dir", str(tmp_path / "out")]) == 0
    assert calls["recipient"] == "caller@example.com"
    assert calls["per_call_password"] is True
