import pikepdf
import pytest

from traffic_complaint_form.encrypt import (
    EncryptionVerificationError,
    encrypt_pdf,
    verify_encrypted_pdf,
)
from traffic_complaint_form.fill import render_form, template_base_url
from traffic_complaint_form.pdf import html_to_pdf
from traffic_complaint_form.sample import sample_case, sample_multi_case


@pytest.fixture()
def plain_pdf(tmp_path, complainant):
    out = tmp_path / "plain.pdf"
    html_to_pdf(render_form(sample_case(), complainant), base_url=template_base_url(), out_path=out)
    return out


def test_encrypt_requires_password(tmp_path, plain_pdf):
    enc = tmp_path / "enc.pdf"
    encrypt_pdf(plain_pdf, enc, password="pw-123")
    with pytest.raises(pikepdf.PasswordError):
        with pikepdf.open(str(enc)):
            pass
    with pikepdf.open(str(enc), password="pw-123") as pdf:
        assert len(pdf.pages) == 1


def test_empty_password_rejected(tmp_path, plain_pdf):
    with pytest.raises(ValueError):
        encrypt_pdf(plain_pdf, tmp_path / "x.pdf", password="")


def test_verify_passes_on_good_file(tmp_path, plain_pdf):
    enc = tmp_path / "enc.pdf"
    encrypt_pdf(plain_pdf, enc, password="pw-123")
    verify_encrypted_pdf(enc, password="pw-123", expected_pages=1)


def test_verify_rejects_unencrypted(tmp_path, plain_pdf):
    with pytest.raises(EncryptionVerificationError):
        verify_encrypted_pdf(plain_pdf, password="pw-123")


def test_verify_allows_any_page_count_when_unspecified(tmp_path, complainant):
    plain = tmp_path / "plain.pdf"
    html_to_pdf(render_form(sample_multi_case(), complainant), base_url=template_base_url(), out_path=plain)
    enc = tmp_path / "enc.pdf"
    encrypt_pdf(plain, enc, password="pw-123")
    verify_encrypted_pdf(enc, password="pw-123", expected_pages=None)
