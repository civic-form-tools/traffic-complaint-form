"""Offline non-access tests for the complete dummy SMTP path."""

import io
import json
import zipfile
import zlib
from email.message import EmailMessage
from pathlib import Path

import pikepdf
import pytest
import yaml

from traffic_complaint_form import synthetic as s


def config():
    return {
        "version": 2,
        "complainant": dict(s.DUMMY_IDENTITY),
        "pdf_password": "ZZ-PDF-TEST-ONLY-" + "a" * 24,
        "archive_password": "ZZ-ARCHIVE-TEST-ONLY-" + "b" * 24,
        "delivery": {
            "recipient_email": "owner@example.invalid",
            "smtp_host": "smtp.example.invalid",
            "smtp_port": 587,
            "smtp_username": "sender@example.invalid",
            "smtp_app_password": "ZZ-SMTP-CANARY",
            "smtp_from": "sender@example.invalid",
        },
    }


class GuardEnv(dict):
    def get(self, key, *args):
        assert key in {"TEST_FILING_BUNDLE", "TEST_APPROVED_RECIPIENT"}, "forbidden env read"
        return super().get(key, *args)


def env(c=None):
    return GuardEnv(
        TEST_FILING_BUNDLE=json.dumps(c or config()),
        TEST_APPROVED_RECIPIENT="owner@example.invalid",
        FILING_BUNDLE="ZZ-PRODUCTION-CANARY",
        CASE_DATA_PRIVATE_KEY="ZZ-KEY-CANARY",
    )


def test_only_test_environment_read():
    c, approved = s.load_test_config(env())
    assert c == config() and approved == "owner@example.invalid"
    with pytest.raises(AssertionError, match="forbidden"):
        env().get("FILING_BUNDLE")  # mutation tripwire proves forbidden reads fail


@pytest.mark.parametrize("field", list(s.DUMMY_IDENTITY))
def test_production_shaped_identity_rejected(field):
    c = config()
    c["complainant"][field] = "ZZ-REAL-CANARY"
    with pytest.raises(s.SyntheticError, match="values withheld"):
        s.load_test_config(env(c))


@pytest.mark.parametrize("mutation", ["missing", "recipient", "same_password", "extra", "header"])
def test_bad_test_config_fails_closed(mutation):
    c = config()
    if mutation == "missing":
        c.pop("archive_password")
    if mutation == "recipient":
        c["delivery"]["recipient_email"] = "other@example.invalid"
    if mutation == "same_password":
        c["archive_password"] = c["pdf_password"]
    if mutation == "extra":
        c["FILING_BUNDLE"] = "ZZ-CANARY"
    if mutation == "header":
        c["delivery"]["smtp_from"] += "\nBcc: other@example.invalid"
    with pytest.raises(s.SyntheticError):
        s.load_test_config(env(c))


class SMTP:
    messages = []

    def __init__(self, *args, **kw):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def ehlo(self):
        pass

    def starttls(self):
        pass

    def login(self, *args):
        pass

    def send_message(self, message, *, to_addrs):
        assert to_addrs == ["owner@example.invalid"]
        self.messages.append(message)
        return {}


@pytest.mark.parametrize("header", ["To", "Cc", "Bcc", "Resent-To", "Resent-Cc", "Resent-Bcc"])
def test_final_envelope_guard(header):
    m = EmailMessage()
    m["To"] = "owner@example.invalid"
    if header == "To":
        del m["To"]
    m[header] = "other@example.invalid"
    with pytest.raises(s.SyntheticError):
        s.LockedSMTP(SMTP(), "owner@example.invalid").send_message(m)


@pytest.mark.parametrize("fmt", ["zip-legacy", "zip-aes"])
@pytest.mark.parametrize("split", [False, True])
def test_full_offline_path(tmp_path, monkeypatch, fmt, split):
    import pyzipper

    SMTP.messages = []

    def render(html, *, base_url, out_path):
        assert "TEST-NOT-A-VALID-ID" in html
        pdf = pikepdf.new()
        pdf.add_blank_page()
        pdf.save(out_path)
        return 1

    monkeypatch.setattr(s, "html_to_pdf", render)
    monkeypatch.setattr(s.tempfile, "tempdir", str(tmp_path))
    c, approved = s.load_test_config(env())
    s.run(c, approved, archive_format=fmt, split=split, smtp_factory=SMTP)
    assert len(SMTP.messages) == (2 if split else 1)
    assert not list(tmp_path.iterdir())
    for m in SMTP.messages:
        assert m["Subject"].startswith("[TEST]")
        assert "ZZ-SMTP-CANARY" not in str(m)
        attachment = list(m.iter_attachments())[0]
        with pyzipper.AESZipFile(io.BytesIO(attachment.get_payload(decode=True))) as z:
            for name in z.namelist():
                for bad in (None, b"wrong"):
                    with pytest.raises((RuntimeError, zipfile.BadZipFile, zlib.error)):
                        z.read(name, pwd=bad)
                with pikepdf.open(io.BytesIO(z.read(name, pwd=c["archive_password"].encode()))) as pdf:
                    assert not pdf.is_encrypted


def test_workflow_boundary():
    text = Path(".github/workflows/test-batch.yml").read_text()
    data = yaml.safe_load(text)
    job = data["jobs"]["synthetic"]
    assert job["environment"] == "testing"
    assert job["if"] == "github.ref == 'refs/heads/main'"
    assert "env" not in job
    assert "secrets.FILING_BUNDLE" not in text and "CASE_DATA_PRIVATE_KEY" not in text
    assert "upload-artifact" not in text and "secrets: inherit" not in text
    secret_steps = [step for step in job["steps"] if "secrets." in str(step)]
    assert len(secret_steps) == 1
    assert set(secret_steps[0]["env"]) == {"TEST_FILING_BUNDLE", "TEST_APPROVED_RECIPIENT", "FORMAT", "SPLIT"}


def test_forbidden_file_and_production_parser_reads(tmp_path, monkeypatch):
    from traffic_complaint_form.config import FilingConfig
    from traffic_complaint_form.crypto import decrypt_payload

    trap = tmp_path / "FILING_BUNDLE.json"
    trap.write_text("ZZ-REAL-FILE-CANARY")
    original = Path.open

    def guarded_open(path, *args, **kwargs):
        assert path != trap, "forbidden production file"
        return original(path, *args, **kwargs)

    def forbidden(*args, **kwargs):
        raise AssertionError("forbidden production parser")

    monkeypatch.setattr(Path, "open", guarded_open)
    monkeypatch.setattr(FilingConfig, "from_env", forbidden)
    monkeypatch.setattr("traffic_complaint_form.crypto.decrypt_payload", forbidden)
    s.load_test_config(env())
    with pytest.raises(AssertionError):
        trap.read_text()  # mutation tripwire
    with pytest.raises(AssertionError):
        FilingConfig.from_env({})
    assert decrypt_payload is not None


def test_main_safe_error_and_reject_real_input(monkeypatch, caplog):
    monkeypatch.setenv("TEST_FILING_BUNDLE", json.dumps({"bad": "ZZ-REAL-CANARY"}))
    monkeypatch.setenv("TEST_APPROVED_RECIPIENT", "owner@example.invalid")
    assert s.main([]) == 1
    assert "ZZ-REAL-CANARY" not in caplog.text
    with pytest.raises(SystemExit):
        s.main(["--batch-encrypted", "production.json"])


def test_main_success_without_network(monkeypatch, capsys):
    monkeypatch.setenv("TEST_FILING_BUNDLE", json.dumps(config()))
    monkeypatch.setenv("TEST_APPROVED_RECIPIENT", "owner@example.invalid")
    monkeypatch.setattr(s, "run", lambda *a, **kw: None)
    assert s.main([]) == 0
    assert "SMTP accepted" in capsys.readouterr().out


def test_cleanup_when_smtp_fails(tmp_path, monkeypatch):
    def render(html, *, base_url, out_path):
        pdf = pikepdf.new()
        pdf.add_blank_page()
        pdf.save(out_path)
        return 1

    class FailingSMTP(SMTP):
        def send_message(self, *args, **kwargs):
            raise RuntimeError("ZZ-SMTP-FAILURE-CANARY")

    monkeypatch.setattr(s, "html_to_pdf", render)
    monkeypatch.setattr(s.tempfile, "tempdir", str(tmp_path))
    c, approved = s.load_test_config(env())
    with pytest.raises(RuntimeError):
        s.run(c, approved, archive_format="zip-legacy", split=False, smtp_factory=FailingSMTP)
    assert not list(tmp_path.iterdir())


def test_complete_renderer_with_no_send(monkeypatch):
    SMTP.messages = []
    c, approved = s.load_test_config(env())
    s.run(c, approved, archive_format="zip-aes", split=False, smtp_factory=SMTP)
    assert len(SMTP.messages) == 1
    assert "TEST_FILING_BUNDLE" in SMTP.messages[0].get_body().get_content()


def test_forbidden_read_mutations(monkeypatch):
    original = s.load_test_config

    def mutant(environ):
        environ.get("CASE_DATA_PRIVATE_KEY")
        return original(environ)

    with pytest.raises(AssertionError, match="forbidden"):
        mutant(env())


def test_duplicate_json_and_missing_test_bundle():
    e = env()
    e["TEST_FILING_BUNDLE"] = '{"version":2,"version":2}'
    with pytest.raises(s.SyntheticError):
        s.load_test_config(e)
    e.pop("TEST_FILING_BUNDLE")
    with pytest.raises(s.SyntheticError):
        s.load_test_config(e)
