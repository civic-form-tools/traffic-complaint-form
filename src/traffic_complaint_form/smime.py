"""S/MIME encryption of the outgoing message with the recipient's public cert.

Only the PUBLIC certificate ever enters the pipeline (environment secret
SMIME_PUBLIC_CERT, PEM). The private key stays with the user; mail clients
on iPhone/Mac decrypt natively. openssl does the cryptography; cert contents
are never logged - errors mention the secret by NAME only.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from email.message import EmailMessage
from pathlib import Path

logger = logging.getLogger(__name__)

BEGIN_MARKER = "-----BEGIN CERTIFICATE-----"
END_MARKER = "-----END CERTIFICATE-----"


class SMIMEError(RuntimeError):
    """Certificate problem or openssl failure - message text is safe to log."""


def validate_cert_pem(cert_pem: str) -> str:
    """Return the normalized PEM block or raise SMIMEError (name-only)."""
    text = cert_pem.strip()
    if BEGIN_MARKER not in text or END_MARKER not in text:
        raise SMIMEError("SMIME_PUBLIC_CERT is not a PEM certificate (missing BEGIN/END CERTIFICATE block)")
    return f"{text}\n"


def encrypt_message(message: EmailMessage, *, cert_pem: str, tmpdir: Path) -> bytes:
    """Encrypt a fully built message and return RFC 2822 bytes ready to send.

    The returned bytes carry To/From/Subject headers plus the
    application/pkcs7-mime body produced by openssl (AES-256).
    """
    pem = validate_cert_pem(cert_pem)
    openssl = shutil.which("openssl")
    if openssl is None:
        raise SMIMEError("openssl is not available on this runner")
    cert_file = tmpdir / "recipient-cert.pem"
    plain_file = tmpdir / "message.eml"
    enc_file = tmpdir / "message.enc"
    cert_file.write_text(pem, encoding="ascii")
    plain_file.write_bytes(message.as_bytes())
    try:
        proc = subprocess.run(  # noqa: S603 - fixed argv, no shell, inputs are local temp paths
            [
                openssl,
                "smime",
                "-encrypt",
                "-aes256",
                "-in",
                str(plain_file),
                "-outform",
                "SMIME",
                "-out",
                str(enc_file),
                str(cert_file),
            ],
            capture_output=True,
            timeout=60,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise SMIMEError("openssl smime -encrypt timed out") from exc
    if proc.returncode != 0:
        # openssl stderr can quote cert internals - keep it out of logs.
        raise SMIMEError(f"openssl failed to encrypt with SMIME_PUBLIC_CERT (rc={proc.returncode})")
    # openssl emits LF; normalize the whole entity to CRLF for SMTP.
    body = enc_file.read_text(encoding="ascii").replace("\r\n", "\n").replace("\n", "\r\n").encode("ascii")
    headers = (f"To: {message['To']}\r\nFrom: {message['From']}\r\nSubject: {message['Subject']}\r\n").encode()
    logger.info("Message S/MIME-encrypted to the recipient's public certificate")
    return headers + body
