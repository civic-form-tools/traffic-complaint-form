"""Encrypted archive packing for batch deliveries.

Batch mode delivers several open (unencrypted) PDFs inside ONE encrypted
archive; the archive is the only encryption layer (user decision 2026-11-04).
The format is pluggable, selected by the bundle's ``archive_format``:

- ``zip-legacy`` (default): traditional ZipCrypto. WEAK by design - chosen
  because the owner's iPhone/Mac open it natively while AES-ZIP failed the
  device test (2026-11-04). The known-plaintext risk is documented in
  docs/SECRETS.md. Members always carry neutral names because no ZIP format
  encrypts filenames. Written here in pure Python: pyzipper reads but does
  not write ZipCrypto and no maintained library writes it; the algorithm is
  the legacy public PKWARE spec and interop is pinned by tests against
  pyzipper, stdlib zipfile and Info-ZIP ``unzip``.
- ``zip-aes``: WinZip AES-256 via pyzipper, for when the receiving devices
  support it.

The module never sees case data: members arrive as (arcname, path) pairs and
arcnames are written exactly as given.
"""

from __future__ import annotations

import binascii
import io
import os
import struct
import time
import zlib
from pathlib import Path

import pikepdf
import pyzipper

from .config import ARCHIVE_FORMATS

MAX_MEMBER_PAGES = 3

LOCAL_HEADER_SIG = 0x04034B50
CENTRAL_HEADER_SIG = 0x02014B50
END_OF_CENTRAL_SIG = 0x06054B50
FLAG_ENCRYPTED = 0x0001
METHOD_STORED = 0
METHOD_DEFLATE = 8


class ArchiveError(RuntimeError):
    """Archive creation or verification failed (details withheld)."""


class ArchiveVerificationError(ArchiveError):
    """A finished archive failed its post-creation checks."""


class OversizedMemberError(ArchiveError):
    """One member alone exceeds the archive size cap and cannot be split."""


# --- ZipCrypto (traditional PKWARE) writer ---------------------------------


# Key schedule mirrors the legacy public spec (and stdlib's _ZipDecrypter),
# so archives inter-operate with every ZIP reader that supports passwords.
# NOTE: the key update uses the RAW CRC table step, not binascii.crc32
# (which applies init/xor chaining and produces different keys).
def _gen_crc(c: int) -> int:
    for _ in range(8):
        c = 0xEDB88320 ^ (c >> 1) if c & 1 else c >> 1
    return c


_CRC_TABLE = [_gen_crc(i) for i in range(256)]


def _raw_crc_byte(crc: int, byte: int) -> int:
    return (crc >> 8) ^ _CRC_TABLE[(crc ^ byte) & 0xFF]


class _ZipCrypto:
    def __init__(self, password: bytes):
        self._k0 = 0x12345678
        self._k1 = 0x23456789
        self._k2 = 0x34567890
        for byte in password:
            self._update(byte)

    def _update(self, byte: int) -> None:
        self._k0 = _raw_crc_byte(self._k0, byte)
        self._k1 = (self._k1 + (self._k0 & 0xFF)) & 0xFFFFFFFF
        self._k1 = (self._k1 * 134775813 + 1) & 0xFFFFFFFF
        self._k2 = _raw_crc_byte(self._k2, self._k1 >> 24)

    def encrypt(self, data: bytes) -> bytes:
        out = bytearray(len(data))
        for i, byte in enumerate(data):
            k = self._k2 | 2
            out[i] = byte ^ (((k * (k ^ 1)) >> 8) & 0xFF)
            self._update(byte)
        return bytes(out)


def _dos_datetime(now: time.struct_time) -> tuple[int, int]:
    year = max(now.tm_year, 1980)
    dos_time = now.tm_hour << 11 | now.tm_min << 5 | now.tm_sec // 2
    dos_date = (year - 1980) << 9 | now.tm_mon << 5 | now.tm_mday
    return dos_time, dos_date


def _deflate(data: bytes) -> tuple[bytes, int]:
    compressor = zlib.compressobj(6, zlib.DEFLATED, -15)
    compressed = compressor.compress(data) + compressor.flush()
    if len(compressed) >= len(data):
        return data, METHOD_STORED
    return compressed, METHOD_DEFLATE


def _write_zipcrypto_zip(members: list[tuple[str, Path]], fp, password: bytes) -> None:
    dos_time, dos_date = _dos_datetime(time.localtime())
    central = b""
    offset = 0
    for arcname, path in members:
        name = arcname.encode("utf-8")
        plaintext = path.read_bytes()
        crc = binascii.crc32(plaintext)
        compressed, method = _deflate(plaintext)
        cipher = _ZipCrypto(password)
        # 12-byte encryption header: 11 random bytes + CRC high byte
        # (the local header carries the CRC; no data descriptor used).
        header = os.urandom(11) + bytes(((crc >> 24) & 0xFF,))
        payload = cipher.encrypt(header) + cipher.encrypt(compressed)
        local = struct.pack(
            "<IHHHHHIIIHH",
            LOCAL_HEADER_SIG,
            20,
            FLAG_ENCRYPTED,
            method,
            dos_time,
            dos_date,
            crc,
            len(payload),
            len(plaintext),
            len(name),
            0,
        )
        fp.write(local)
        fp.write(name)
        fp.write(payload)
        central += (
            struct.pack(
                "<IHHHHHHIIIHHHHHII",
                CENTRAL_HEADER_SIG,
                20,
                20,
                FLAG_ENCRYPTED,
                method,
                dos_time,
                dos_date,
                crc,
                len(payload),
                len(plaintext),
                len(name),
                0,
                0,
                0,
                0,
                0,
                offset,
            )
            + name
        )
        offset += len(local) + len(name) + len(payload)
    fp.write(central)
    fp.write(
        struct.pack(
            "<IHHHHIIH",
            END_OF_CENTRAL_SIG,
            0,
            0,
            len(members),
            len(members),
            len(central),
            offset,
            0,
        )
    )


def _write_aes_zip(members: list[tuple[str, Path]], out_path: Path, password: bytes) -> None:
    with pyzipper.AESZipFile(out_path, "w", compression=pyzipper.ZIP_DEFLATED, encryption=pyzipper.WZ_AES) as archive:
        archive.setpassword(password)
        archive.setencryption(pyzipper.WZ_AES, nbits=256)
        for arcname, path in members:
            archive.write(path, arcname)


_WRITERS = {
    "zip-legacy": _write_zipcrypto_zip,
    "zip-aes": _write_aes_zip,
}


def _check_members(members: list[tuple[str, Path]], password: str, fmt: str) -> None:
    if fmt not in ARCHIVE_FORMATS:
        raise ArchiveError("unknown archive format (check archive_format)")
    if not members:
        raise ArchiveError("no members to archive")
    if not password:
        raise ArchiveError("archive password must not be empty")
    names = [arcname for arcname, _ in members]
    if len(set(names)) != len(names) or any("/" in n or "\\" in n or n.startswith(".") for n in names):
        raise ArchiveError("invalid member names")


def _archive_bytes(members: list[tuple[str, Path]], *, password: str, fmt: str) -> bytes:
    buffer = io.BytesIO()
    _WRITERS[fmt](members, buffer, password.encode("utf-8"))
    return buffer.getvalue()


def create_archive(members: list[tuple[str, Path]], out_path: Path, *, password: str, fmt: str) -> None:
    """Write members into one password-encrypted archive at out_path."""
    _check_members(members, password, fmt)
    with out_path.open("wb") as fp:
        _WRITERS[fmt](members, fp, password.encode("utf-8"))


def pack_members(
    members: list[tuple[str, Path]], *, max_bytes: int, password: str, fmt: str
) -> list[list[tuple[str, Path]]]:
    """Greedy deterministic grouping under the email size cap (user decision 2026-11-04).

    Members keep payload order; the trial archive is REALLY built in memory
    with the chosen backend, so the cap is measured on the exact bytes that
    will be sent. One member alone over the cap raises OversizedMemberError
    (a single document cannot be split) and nothing is produced.
    """
    _check_members(members, password, fmt)
    groups: list[list[tuple[str, Path]]] = []
    current: list[tuple[str, Path]] = []
    for member in members:
        trial = [*current, member]
        if len(_archive_bytes(trial, password=password, fmt=fmt)) <= max_bytes:
            current = trial
            continue
        if not current:
            raise OversizedMemberError(f"member {member[0]} alone is over the {max_bytes}-byte archive cap")
        groups.append(current)
        current = [member]
        if len(_archive_bytes(current, password=password, fmt=fmt)) > max_bytes:
            raise OversizedMemberError(f"member {member[0]} alone is over the {max_bytes}-byte archive cap")
    if current:
        groups.append(current)
    return groups


def _open_member(archive: pyzipper.AESZipFile, name: str, password: bytes | None) -> bytes:
    if password is not None:
        archive.setpassword(password)
    return archive.read(name)


def verify_archive(path: Path, *, password: str, expected_members: int, max_bytes: int | None = None) -> None:
    """Confirm the archive is unreadable without its password and well-formed with it.

    Every member must be an open (PDF-level unencrypted), well-formed PDF of
    1..MAX_MEMBER_PAGES pages: batch PDFs are open BY DESIGN, so a member that
    demands a password means the single-mode lock leaked into the batch path.
    """
    if max_bytes is not None:
        size = path.stat().st_size
        if size > max_bytes:
            raise ArchiveVerificationError(f"{path.name} is {size} bytes, over the {max_bytes}-byte email cap")
    try:
        with pyzipper.AESZipFile(str(path)) as archive:
            names = archive.namelist()
            if not names:
                raise ArchiveVerificationError(f"{path.name} has no members")
            try:
                _open_member(archive, names[0], None)
            except (RuntimeError, zlib.error, OSError):
                pass
            else:
                raise ArchiveVerificationError(f"{path.name} opens WITHOUT a password - refusing to deliver it")
            try:
                _open_member(archive, names[0], b"00000000-wrong-password-00000000")
            except (RuntimeError, zlib.error, OSError):
                pass
            else:
                raise ArchiveVerificationError(f"{path.name} opens with a WRONG password - refusing to deliver it")
            if len(names) != expected_members:
                raise ArchiveVerificationError(f"{path.name} holds {len(names)} members, expected {expected_members}")
            for name in names:
                try:
                    data = _open_member(archive, name, password.encode("utf-8"))
                except (RuntimeError, zlib.error, OSError) as exc:
                    raise ArchiveVerificationError(f"member {name} unreadable with the archive password") from exc
                try:
                    with pikepdf.open(io.BytesIO(data)) as pdf:
                        pages = len(pdf.pages)
                except pikepdf.PasswordError as exc:
                    raise ArchiveVerificationError(
                        f"member {name} is PASSWORD-LOCKED - batch members must be open PDFs"
                    ) from exc
                except Exception as exc:
                    raise ArchiveVerificationError(f"member {name} is not a well-formed PDF") from exc
                if not 1 <= pages <= MAX_MEMBER_PAGES:
                    raise ArchiveVerificationError(f"member {name} has {pages} pages, expected 1-{MAX_MEMBER_PAGES}")
    except pyzipper.BadZipFile as exc:
        raise ArchiveVerificationError(f"{path.name} is not a readable ZIP archive") from exc
