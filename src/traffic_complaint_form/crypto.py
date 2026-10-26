"""Sealed-box encryption for case data delivered through a public workflow.

workflow_dispatch inputs and run logs of a public repository are visible to
everyone, so case data (plates, locations, incident details) must never
travel in plaintext. Callers encrypt the case JSON with the repository's
public key (form/keys/case-data-public.key); only the workflow, holding the
private key from Secrets, can decrypt it. Uses libsodium sealed boxes
(ephemeral X25519 + XSalsa20-Poly1305) via PyNaCl.
"""

from __future__ import annotations

import argparse
import base64
from pathlib import Path

from nacl.exceptions import CryptoError
from nacl.public import PrivateKey, PublicKey, SealedBox

DEFAULT_PUBLIC_KEY_PATH = Path("form/keys/case-data-public.key")


class CaseDecryptionError(RuntimeError):
    """Raised when an encrypted case payload cannot be decrypted."""


def generate_keypair() -> tuple[str, str]:
    """Return (public_key_b64, private_key_b64) for a fresh sealed-box keypair."""
    private = PrivateKey.generate()
    return (
        base64.b64encode(bytes(private.public_key)).decode(),
        base64.b64encode(bytes(private)).decode(),
    )


def encrypt_payload(public_key_b64: str, payload: bytes) -> str:
    box = SealedBox(PublicKey(base64.b64decode(public_key_b64)))
    return base64.b64encode(box.encrypt(payload)).decode()


def decrypt_payload(private_key_b64: str, ciphertext_b64: str) -> bytes:
    box = SealedBox(PrivateKey(base64.b64decode(private_key_b64)))
    try:
        return box.decrypt(base64.b64decode(ciphertext_b64.strip()))
    except (CryptoError, ValueError) as exc:
        raise CaseDecryptionError("case payload could not be decrypted - wrong key or corrupted ciphertext") from exc


def encrypt_case_main(argv: list[str] | None = None) -> int:
    """Caller-side helper: encrypt a case JSON file for the workflow."""
    parser = argparse.ArgumentParser(prog="traffic-complaint-form-encrypt-case")
    parser.add_argument("--in", dest="infile", type=Path, required=True, help="case JSON file")
    parser.add_argument("--out", dest="outfile", type=Path, required=True, help="output file for the base64 ciphertext")
    parser.add_argument("--public-key", type=Path, default=DEFAULT_PUBLIC_KEY_PATH)
    args = parser.parse_args(argv)
    public_key_b64 = args.public_key.read_text(encoding="utf-8").strip()
    ciphertext = encrypt_payload(public_key_b64, args.infile.read_bytes())
    args.outfile.write_text(ciphertext + "\n", encoding="utf-8")
    print(f"encrypted case written to {args.outfile}")
    return 0
