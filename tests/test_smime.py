"""S/MIME round-trip: encrypt to a throwaway cert, decrypt with its key.

The cert/key pair is generated fresh by openssl for the test only; it
contains invented identity data and is deleted with tmp_path.
"""

import shutil
import subprocess
from email.message import EmailMessage
from unittest.mock import MagicMock

import pytest

from traffic_complaint_form.mail import send_encrypted_pdf
from traffic_complaint_form.smime import SMIMEError, encrypt_message, validate_cert_pem

pytestmark = pytest.mark.skipif(shutil.which("openssl") is None, reason="openssl not installed")


@pytest.fixture()
def cert_pair(tmp_path):
    key = tmp_path / "key.pem"
    cert = tmp_path / "cert.pem"
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-keyout",
            str(key),
            "-out",
            str(cert),
            "-days",
            "1",
            "-subj",
            "/CN=Test Recipient/emailAddress=test@example.com",
        ],
        check=True,
        capture_output=True,
        timeout=60,
    )
    return cert.read_text(), key


def make_message(tmp_path):
    msg = EmailMessage()
    msg["From"] = "sender@example.com"
    msg["To"] = "test@example.com"
    msg["Subject"] = "תלונה - בדיקה"
    msg.set_content("body")
    payload = tmp_path / "form.pdf"
    payload.write_bytes(b"%PDF-1.7 fake")
    msg.add_attachment(payload.read_bytes(), maintype="application", subtype="pdf", filename="form.pdf")
    return msg


def test_validate_rejects_non_pem():
    with pytest.raises(SMIMEError):
        validate_cert_pem("not a certificate")


def test_validate_normalizes_pem(cert_pair):
    pem, _ = cert_pair
    assert validate_cert_pem(pem).endswith("\n")


def test_round_trip_decrypts_to_original(cert_pair, tmp_path):
    pem, key = cert_pair
    raw = encrypt_message(make_message(tmp_path), cert_pem=pem, tmpdir=tmp_path)
    marker = b"MIME-Version:"
    header_block, _, entity = raw.partition(marker)
    assert b"To: test@example.com" in header_block
    assert b"From: sender@example.com" in header_block
    assert "תלונה".encode() in header_block
    assert b"\r\n" in entity  # normalized for SMTP
    enc = tmp_path / "enc.eml"
    dec = tmp_path / "dec.eml"
    # openssl expects the MIME entity it produced; strip our prepended headers
    enc.write_bytes(marker + entity)
    subprocess.run(
        [
            "openssl",
            "smime",
            "-decrypt",
            "-in",
            str(enc),
            "-recip",
            tmp_path / "cert.pem",
            "-inkey",
            str(key),
            "-out",
            str(dec),
        ],
        check=True,
        capture_output=True,
        timeout=60,
    )
    from email import message_from_bytes, policy

    decrypted = message_from_bytes(dec.read_bytes(), policy=policy.default)
    attachments = list(decrypted.iter_attachments())
    assert len(attachments) == 1
    assert attachments[0].get_filename() == "form.pdf"
    assert attachments[0].get_payload(decode=True) == b"%PDF-1.7 fake"
    text_parts = [part.get_content().strip() for part in decrypted.walk() if part.get_content_type() == "text/plain"]
    assert text_parts == ["body"]


def test_bad_cert_raises_name_only(cert_pair, tmp_path):
    pem, _ = cert_pair
    broken = pem.replace("-----BEGIN CERTIFICATE-----", "-----BEGIN CERTIFICATE-----\nAAAA", 1)
    with pytest.raises(SMIMEError) as excinfo:
        encrypt_message(make_message(tmp_path), cert_pem=broken, tmpdir=tmp_path)
    assert "SMIME_PUBLIC_CERT" in str(excinfo.value)


def test_mail_sends_smime_raw(cert_pair, tmp_path):
    pem, _ = cert_pair
    attachment = tmp_path / "form.pdf"
    attachment.write_bytes(b"%PDF-1.7 fake")
    server = MagicMock()
    server.sendmail.return_value = {}
    factory = MagicMock()
    factory.return_value.__enter__.return_value = server
    send_encrypted_pdf(
        smtp_username="sender@example.com",
        smtp_password="app-password",
        recipient="test@example.com",
        attachment_path=attachment,
        vehicle_number="12-345-67",
        offence_date="15/01/2026",
        smime_cert_pem=pem,
        smtp_factory=factory,
    )
    server.send_message.assert_not_called()
    (sender, recipients, raw), _ = server.sendmail.call_args
    assert sender == "sender@example.com"
    assert recipients == ["test@example.com"]
    assert b"pkcs7-mime" in raw
