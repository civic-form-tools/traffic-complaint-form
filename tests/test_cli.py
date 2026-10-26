import json
import logging

from traffic_complaint_form import cli
from traffic_complaint_form.cli import is_test_mode, main, required_secret_names

ENV = {
    "COMPLAINANT_FIRST_NAME": "משה",
    "COMPLAINANT_LAST_NAME": "כהן",
    "COMPLAINANT_ID": "123456782",  # documented test placeholder
    "COMPLAINANT_ADDRESS": "רחוב הדוגמה 1",
    "COMPLAINANT_PHONE": "050-0000000",
    "PDF_PASSWORD": "test-pw",
}


def set_env(monkeypatch, extra=None):
    for key, value in {**ENV, **(extra or {})}.items():
        monkeypatch.setenv(key, value)


def test_missing_secrets_reports_names_not_values(monkeypatch, tmp_path, caplog):
    monkeypatch.setenv("COMPLAINANT_FIRST_NAME", "secret-first-name")
    with caplog.at_level(logging.INFO):
        code = main(["--sample", "--out-dir", str(tmp_path), "--dry-run"])
    assert code == 2
    assert "COMPLAINANT_ID" in caplog.text
    assert "secret-first-name" not in caplog.text


def test_dry_run_sample_end_to_end(monkeypatch, tmp_path, caplog):
    set_env(monkeypatch)
    with caplog.at_level(logging.INFO):
        code = main(["--sample", "--out-dir", str(tmp_path), "--dry-run"])
    assert code == 0
    produced = list(tmp_path.glob("*.pdf"))
    assert len(produced) == 1
    import pikepdf

    with pikepdf.open(str(produced[0]), password="test-pw") as pdf:
        assert len(pdf.pages) == 1
    assert ENV["COMPLAINANT_ID"] not in caplog.text  # secrets stay out of logs
    assert ENV["COMPLAINANT_PHONE"] not in caplog.text


def test_case_json_input(monkeypatch, tmp_path):
    set_env(monkeypatch)
    case_file = tmp_path / "case.json"
    case_file.write_text(
        json.dumps(
            {
                "police_station": "מוריה",
                "vehicle_number": "98-765-43",
                "vehicle_manufacturer": "מאזדה",
                "vehicle_color": "אדום",
                "offence_date": "2026-02-01",
                "offence_time": "09:15",
                "offence_street": "רחוב הדוגמה",
                "offence_city": "ירושלים",
                "offence_description": "תיאור",
            }
        )
    )
    assert main(["--case-json", str(case_file), "--out-dir", str(tmp_path / "o"), "--dry-run"]) == 0


def test_invalid_case_json(monkeypatch, tmp_path):
    set_env(monkeypatch)
    bad = tmp_path / "bad.json"
    bad.write_text("{}")
    assert main(["--case-json", str(bad), "--out-dir", str(tmp_path / "o"), "--dry-run"]) == 2


def test_overflow_returns_3(monkeypatch, tmp_path):
    set_env(monkeypatch)
    monkeypatch.setattr(cli, "html_to_pdf", lambda *a, **k: 2)
    assert main(["--sample", "--out-dir", str(tmp_path), "--dry-run"]) == 3


SMTP_ENV = {
    "RECIPIENT_EMAIL": "d@example.com",
    "SMTP_HOST": "smtp.example.com",
    "SMTP_USERNAME": "u",
    "SMTP_APP_PASSWORD": "p",
    "SMTP_FROM": "f@example.com",
}


def test_send_path_calls_mail(monkeypatch, tmp_path):
    set_env(monkeypatch, SMTP_ENV)
    calls = {}
    monkeypatch.setattr(cli, "send_encrypted_pdf", lambda **kw: calls.update(kw))
    assert main(["--sample", "--out-dir", str(tmp_path)]) == 0
    assert calls["recipient"] == "d@example.com"
    assert calls["vehicle_number"] == "12-345-67"
    assert calls["smtp_host"] == "smtp.example.com"
    assert calls["smtp_port"] == 587
    assert calls["from_address"] == "f@example.com"


def test_send_path_requires_smtp_host_and_from(monkeypatch, tmp_path, caplog):
    set_env(monkeypatch, {"RECIPIENT_EMAIL": "d@example.com", "SMTP_USERNAME": "u", "SMTP_APP_PASSWORD": "p"})
    with caplog.at_level(logging.INFO):
        code = main(["--sample", "--out-dir", str(tmp_path)])
    assert code == 2
    assert "SMTP_HOST" in caplog.text
    assert "SMTP_FROM" in caplog.text
    assert "SMTP_PORT" not in caplog.text  # optional, defaults to 587


def test_smtp_port_override(monkeypatch, tmp_path):
    set_env(monkeypatch, {**SMTP_ENV, "SMTP_PORT": "465"})
    calls = {}
    monkeypatch.setattr(cli, "send_encrypted_pdf", lambda **kw: calls.update(kw))
    assert main(["--sample", "--out-dir", str(tmp_path)]) == 0
    assert calls["smtp_port"] == 465


def test_encrypted_case_requires_private_key(monkeypatch, tmp_path, caplog):
    set_env(monkeypatch)
    from traffic_complaint_form.crypto import encrypt_payload, generate_keypair

    public_b64, _ = generate_keypair()
    enc = tmp_path / "case.enc"
    enc.write_text(encrypt_payload(public_b64, b"{}"))
    with caplog.at_level(logging.INFO):
        code = main(["--case-encrypted", str(enc), "--out-dir", str(tmp_path / "o"), "--dry-run"])
    assert code == 2
    assert "CASE_DATA_PRIVATE_KEY" in caplog.text


def test_encrypted_case_roundtrip_and_log_privacy(monkeypatch, tmp_path, caplog):
    set_env(monkeypatch)
    from traffic_complaint_form.crypto import encrypt_payload, generate_keypair

    public_b64, private_b64 = generate_keypair()
    monkeypatch.setenv("CASE_DATA_PRIVATE_KEY", private_b64)
    payload = json.dumps(
        {
            "police_station": "מוריה",
            "vehicle_number": "55-444-33",
            "vehicle_manufacturer": "סקודה",
            "vehicle_color": "שחור",
            "offence_date": "2026-02-02",
            "offence_time": "08:00",
            "offence_street": "רחוב חסוי",
            "offence_city": "ירושלים",
            "offence_description": "תיאור חסוי",
        }
    ).encode()
    enc = tmp_path / "case.enc"
    enc.write_text(encrypt_payload(public_b64, payload))
    with caplog.at_level(logging.INFO):
        code = main(["--case-encrypted", str(enc), "--out-dir", str(tmp_path / "o"), "--dry-run"])
    assert code == 0
    assert "55-444-33" not in caplog.text
    assert "רחוב חסוי" not in caplog.text
    produced = list((tmp_path / "o").glob("*.pdf"))
    assert len(produced) == 1
    assert "55-444-33" not in produced[0].name  # filename must not leak the plate


def test_is_test_mode_default_true():
    assert is_test_mode({}) is True
    assert is_test_mode({"TEST_MODE": "false"}) is False


def test_required_secret_names_dry_run():
    assert "SMTP_USERNAME" not in required_secret_names(dry_run=True)
    assert "SMTP_USERNAME" in required_secret_names(dry_run=False)


def test_required_secret_names_pdf_password_only_real_mode():
    assert "PDF_PASSWORD" not in required_secret_names(dry_run=True, encrypt_output=True, test_mode=True)
    assert "PDF_PASSWORD" in required_secret_names(dry_run=True, encrypt_output=True, test_mode=False)
    assert "PDF_PASSWORD" not in required_secret_names(dry_run=True, encrypt_output=False, test_mode=False)


def test_real_mode_requires_pdf_password(monkeypatch, tmp_path, caplog):
    env = dict(ENV)
    env.pop("PDF_PASSWORD", None)
    set_env(monkeypatch, extra=env)
    monkeypatch.setenv("PDF_PASSWORD", "")
    monkeypatch.setenv("TEST_MODE", "false")
    with caplog.at_level(logging.INFO):
        code = main(["--sample", "--out-dir", str(tmp_path), "--dry-run"])
    assert code == 2
    assert "PDF_PASSWORD" in caplog.text


def test_test_mode_falls_back_to_id_password(monkeypatch, tmp_path, caplog):
    env = dict(ENV)
    env.pop("PDF_PASSWORD", None)
    set_env(monkeypatch, extra=env)
    monkeypatch.setenv("PDF_PASSWORD", "")
    with caplog.at_level(logging.INFO):
        code = main(["--sample", "--out-dir", str(tmp_path), "--dry-run"])
    assert code == 0
    assert "low entropy" in caplog.text
    assert ENV["COMPLAINANT_ID"] not in caplog.text  # the password never logs
    produced = list(tmp_path.glob("*.pdf"))
    assert len(produced) == 1
    import pikepdf

    with pikepdf.open(str(produced[0]), password=ENV["COMPLAINANT_ID"]) as pdf:
        assert len(pdf.pages) == 1


def test_dedicated_password_overrides_id(monkeypatch, tmp_path):
    set_env(monkeypatch)  # ENV includes PDF_PASSWORD=test-pw
    code = main(["--sample", "--out-dir", str(tmp_path), "--dry-run"])
    assert code == 0
    produced = list(tmp_path.glob("*.pdf"))
    import pikepdf

    with pikepdf.open(str(produced[0]), password="test-pw") as pdf:
        assert len(pdf.pages) == 1
    import pytest

    with pytest.raises(pikepdf.PasswordError):
        pikepdf.open(str(produced[0]), password=ENV["COMPLAINANT_ID"])
