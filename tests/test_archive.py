"""Archive module: roundtrip, interop, verification and privacy tests."""

import io
import shutil
import subprocess
import zipfile
from pathlib import Path

import pikepdf
import pytest
import pyzipper

from traffic_complaint_form.archive import (
    ArchiveError,
    ArchiveVerificationError,
    create_archive,
    verify_archive,
)

PASSWORD = "invented-archive-password"
WRONG = "00000000-wrong-password-00000000"
FORMATS = ["zip-legacy", "zip-aes"]


def make_pdf(path: Path, pages: int = 1) -> Path:
    pdf = pikepdf.Pdf.new()
    for _ in range(pages):
        pdf.add_blank_page()
    pdf.save(path)
    return path


@pytest.fixture()
def members(tmp_path):
    return [(f"complaint-{i:02d}.pdf", make_pdf(tmp_path / f"m{i}.pdf")) for i in (1, 2, 3)]


@pytest.mark.parametrize("fmt", FORMATS)
def test_roundtrip_opens_with_password_only(members, tmp_path, fmt):
    out = tmp_path / f"batch-{fmt}.zip"
    create_archive(members, out, password=PASSWORD, fmt=fmt)
    with pyzipper.AESZipFile(out) as z:
        assert z.namelist() == [n for n, _ in members]
        with pytest.raises(RuntimeError):
            z.read("complaint-01.pdf")
        z.setpassword(PASSWORD.encode())
        for name, source in members:
            assert z.read(name) == source.read_bytes()


@pytest.mark.parametrize("fmt", FORMATS)
def test_verify_archive_passes_and_rejects(members, tmp_path, fmt):
    out = tmp_path / f"batch-{fmt}.zip"
    create_archive(members, out, password=PASSWORD, fmt=fmt)
    verify_archive(out, password=PASSWORD, expected_members=3)
    with pytest.raises(ArchiveVerificationError, match="expected 2"):
        verify_archive(out, password=PASSWORD, expected_members=2)


@pytest.mark.parametrize("fmt", FORMATS)
def test_verify_rejects_locked_member_pdf(members, tmp_path, fmt):
    locked = tmp_path / "locked.pdf"
    with pikepdf.open(members[0][1]) as pdf:
        pdf.save(locked, encryption=pikepdf.Encryption(user="x" * 16, owner="x" * 16, aes=True, R=6))
    members[0] = (members[0][0], locked)
    out = tmp_path / f"batch-{fmt}.zip"
    create_archive(members, out, password=PASSWORD, fmt=fmt)
    with pytest.raises(ArchiveVerificationError, match="PASSWORD-LOCKED"):
        verify_archive(out, password=PASSWORD, expected_members=3)


@pytest.mark.parametrize("fmt", FORMATS)
def test_verify_rejects_non_pdf_member(members, tmp_path, fmt):
    junk = tmp_path / "junk.pdf"
    junk.write_bytes(b"not a pdf at all")
    members[0] = (members[0][0], junk)
    out = tmp_path / f"batch-{fmt}.zip"
    create_archive(members, out, password=PASSWORD, fmt=fmt)
    with pytest.raises(ArchiveVerificationError, match="not a well-formed PDF"):
        verify_archive(out, password=PASSWORD, expected_members=3)


@pytest.mark.parametrize("fmt", FORMATS)
def test_verify_rejects_oversized_member(members, tmp_path, fmt):
    members[0] = (members[0][0], make_pdf(tmp_path / "big.pdf", pages=4))
    out = tmp_path / f"batch-{fmt}.zip"
    create_archive(members, out, password=PASSWORD, fmt=fmt)
    with pytest.raises(ArchiveVerificationError, match="4 pages"):
        verify_archive(out, password=PASSWORD, expected_members=3)


def test_legacy_interop_stdlib_zipfile(members, tmp_path):
    out = tmp_path / "batch.zip"
    create_archive(members, out, password=PASSWORD, fmt="zip-legacy")
    with zipfile.ZipFile(out) as z:
        assert z.namelist() == [n for n, _ in members]
        with pytest.raises(RuntimeError):
            z.read("complaint-01.pdf")
        assert z.read("complaint-02.pdf", pwd=PASSWORD.encode()) == members[1][1].read_bytes()


@pytest.mark.skipif(not shutil.which("unzip"), reason="Info-ZIP unzip not installed")
def test_legacy_interop_infozip_unzip(members, tmp_path):
    out = tmp_path / "batch.zip"
    create_archive(members, out, password=PASSWORD, fmt="zip-legacy")
    dest = tmp_path / "x"
    dest.mkdir()
    subprocess.run(["unzip", "-o", "-q", "-P", PASSWORD, str(out), "-d", str(dest)], check=True)
    assert (dest / "complaint-01.pdf").read_bytes() == members[0][1].read_bytes()


@pytest.mark.skipif(not shutil.which("zip"), reason="Info-ZIP zip not installed")
def test_legacy_reads_infozip_output(members, tmp_path):
    staging = tmp_path / "stage"
    staging.mkdir()
    for arcname, source in members:
        (staging / arcname).write_bytes(source.read_bytes())
    out = tmp_path / "infozip.zip"
    subprocess.run(["zip", "-q", "-j", "-P", PASSWORD, str(out)] + [str(staging / n) for n, _ in members], check=True)
    verify_archive(out, password=PASSWORD, expected_members=3)


def test_wrong_password_and_no_password_rejected(members, tmp_path):
    out = tmp_path / "batch.zip"
    create_archive(members, out, password=PASSWORD, fmt="zip-legacy")
    with zipfile.ZipFile(out) as z:
        with pytest.raises(RuntimeError):
            z.read("complaint-01.pdf", pwd=WRONG.encode())


def test_create_rejects_bad_input(members, tmp_path):
    out = tmp_path / "batch.zip"
    with pytest.raises(ArchiveError):
        create_archive(members, out, password=PASSWORD, fmt="7z")
    with pytest.raises(ArchiveError):
        create_archive([], out, password=PASSWORD, fmt="zip-legacy")
    with pytest.raises(ArchiveError):
        create_archive(members, out, password="", fmt="zip-legacy")
    with pytest.raises(ArchiveError):
        create_archive(members + [members[0]], out, password=PASSWORD, fmt="zip-legacy")  # duplicate arcname
    with pytest.raises(ArchiveError):
        create_archive([("dir/evil.pdf", members[0][1])], out, password=PASSWORD, fmt="zip-legacy")


def test_verify_rejects_garbage_file(tmp_path):
    junk = tmp_path / "junk.zip"
    junk.write_bytes(b"this is not a zip")
    with pytest.raises(ArchiveVerificationError):
        verify_archive(junk, password=PASSWORD, expected_members=1)


def test_member_content_is_open_pdf(members, tmp_path):
    out = tmp_path / "batch.zip"
    create_archive(members, out, password=PASSWORD, fmt="zip-aes")
    with pyzipper.AESZipFile(out) as z:
        z.setpassword(PASSWORD.encode())
        data = z.read("complaint-01.pdf")
    with pikepdf.open(io.BytesIO(data)) as pdf:
        assert len(pdf.pages) == 1
