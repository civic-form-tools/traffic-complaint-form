"""AES-256 password protection for the filled PDF.

The encrypted file opens natively in any PDF reader (iPhone, Mac, Android)
after typing the password, so no extra tooling is needed on the receiving
side. The password lives only in a GitHub Secret and in the user's hands.
"""

from __future__ import annotations

from pathlib import Path

import pikepdf


class EncryptionVerificationError(RuntimeError):
    """Raised when an encrypted PDF fails its post-encryption checks."""


def encrypt_pdf(source: Path, target: Path, *, password: str) -> None:
    if not password:
        raise ValueError("encryption password must not be empty")
    with pikepdf.open(str(source)) as pdf:
        pdf.save(
            str(target),
            encryption=pikepdf.Encryption(user=password, owner=password, aes=True, R=6),
        )


def verify_encrypted_pdf(path: Path, *, password: str, expected_pages: int | None = 1) -> None:
    """Confirm the file is unreadable without the password and well-formed with it.

    expected_pages=None accepts any page count: a merged multi-incident
    complaint may spill onto a continuation page (the CLI caps the total).
    """
    try:
        with pikepdf.open(str(path)):
            pass
    except pikepdf.PasswordError:
        pass
    else:
        raise EncryptionVerificationError(f"{path.name} opens WITHOUT a password - refusing to deliver it") from None
    with pikepdf.open(str(path), password=password) as pdf:
        pages = len(pdf.pages)
    if expected_pages is None:
        if pages < 1:
            raise EncryptionVerificationError(f"{path.name} has no pages")
    elif pages != expected_pages:
        raise EncryptionVerificationError(
            f"{path.name} has {pages} pages, expected {expected_pages} - check the description length"
        )
