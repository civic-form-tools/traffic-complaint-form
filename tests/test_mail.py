from unittest.mock import MagicMock

import pytest

from traffic_complaint_form.mail import send_encrypted_pdf


def make_smtp():
    server = MagicMock()
    server.send_message.return_value = {}
    factory = MagicMock()
    factory.return_value.__enter__.return_value = server
    return factory, server


def test_send_flow_uses_tls_and_login(tmp_path):
    attachment = tmp_path / "form.pdf"
    attachment.write_bytes(b"%PDF-1.7 fake")
    factory, server = make_smtp()
    send_encrypted_pdf(
        smtp_host="smtp.example.com",
        smtp_port=587,
        smtp_username="sender@example.com",
        smtp_password="app-password",
        from_address="sender@example.com",
        recipient="dest@example.com",
        attachment_path=attachment,
        vehicle_number="12-345-67",
        offence_date="15/01/2026",
        smtp_factory=factory,
    )
    server.starttls.assert_called_once()
    server.login.assert_called_once_with("sender@example.com", "app-password")
    (message,), _ = server.send_message.call_args
    assert message["To"] == "dest@example.com"
    assert "12-345-67" in message["Subject"]
    assert "[TEST]" not in message["Subject"]
    attachments = list(message.iter_attachments())
    assert len(attachments) == 1
    assert attachments[0].get_filename() == "form.pdf"


def test_test_mode_prefixes_subject(tmp_path):
    attachment = tmp_path / "form.pdf"
    attachment.write_bytes(b"%PDF-1.7 fake")
    factory, server = make_smtp()
    send_encrypted_pdf(
        smtp_host="smtp.example.com",
        smtp_port=587,
        smtp_username="s",
        smtp_password="p",
        from_address="sender@example.com",
        recipient="d",
        attachment_path=attachment,
        vehicle_number="1",
        offence_date="d",
        test_mode=True,
        smtp_factory=factory,
    )
    (message,), _ = server.send_message.call_args
    assert message["Subject"].startswith("[TEST] ")


def test_refused_recipient_raises(tmp_path):
    attachment = tmp_path / "form.pdf"
    attachment.write_bytes(b"%PDF-1.7 fake")
    factory, server = make_smtp()
    server.send_message.return_value = {"dest@example.com": (550, b"no")}
    with pytest.raises(RuntimeError, match="refused"):
        send_encrypted_pdf(
            smtp_host="smtp.example.com",
            smtp_port=587,
            smtp_username="s",
            smtp_password="p",
            from_address="sender@example.com",
            recipient="dest@example.com",
            attachment_path=attachment,
            vehicle_number="1",
            offence_date="d",
            smtp_factory=factory,
        )


def test_no_credentials_in_logs(tmp_path, caplog):
    attachment = tmp_path / "form.pdf"
    attachment.write_bytes(b"%PDF-1.7 fake")
    factory, _ = make_smtp()
    import logging

    with caplog.at_level(logging.INFO):
        send_encrypted_pdf(
            smtp_host="smtp.example.com",
            smtp_port=587,
            smtp_username="sender@example.com",
            smtp_password="super-secret-pw",
            from_address="sender@example.com",
            recipient="dest@example.com",
            attachment_path=attachment,
            vehicle_number="1",
            offence_date="d",
            smtp_factory=factory,
        )
    assert "super-secret-pw" not in caplog.text
    assert "dest@example.com" not in caplog.text


@pytest.mark.parametrize("test_mode", [False, True])
def test_subject_is_ascii_only(tmp_path, test_mode):
    """A gateway-prepended warning must not be able to break subject decoding."""
    attachment = tmp_path / "form.pdf"
    attachment.write_bytes(b"%PDF-1.7 fake")
    factory, server = make_smtp()
    send_encrypted_pdf(
        smtp_host="smtp.example.com",
        smtp_port=587,
        smtp_username="sender@example.com",
        smtp_password="app-password",
        from_address="sender@example.com",
        recipient="dest@example.com",
        attachment_path=attachment,
        vehicle_number="12-345-67",
        offence_date="15/01/2026",
        test_mode=test_mode,
        smtp_factory=factory,
    )
    (message,), _ = server.send_message.call_args
    subject = str(message["Subject"])
    assert subject.isascii(), subject
    assert "12-345-67" in subject
    body = message.get_body(preferencelist=("plain",)).get_content()
    assert "unscannable" in body  # sets expectations about the gateway warning
    assert "מוצפן" in body


def test_per_call_body_variant_mentions_caller_password(tmp_path):
    attachment = tmp_path / "form.pdf"
    attachment.write_bytes(b"%PDF-1.7 fake")
    factory, server = make_smtp()
    send_encrypted_pdf(
        smtp_host="smtp.example.com",
        smtp_port=587,
        smtp_username="sender@example.com",
        smtp_password="app-password",
        from_address="sender@example.com",
        recipient="dest@example.com",
        attachment_path=attachment,
        vehicle_number="12-345-67",
        offence_date="15/01/2026",
        per_call_password=True,
        smtp_factory=factory,
    )
    (message,), _ = server.send_message.call_args
    body = message.get_body(preferencelist=("plain",)).get_content()
    assert "שבחרת" in body  # the caller's own chosen password, not the bundle's
    assert "FILING_BUNDLE" not in body
    # Fixed template: no caller-controlled free text anywhere in the body
    assert "12-345-67" not in body
