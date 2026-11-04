"""Batch mode: payload model, CLI end-to-end, privacy and failure semantics."""

import json
import logging

import pikepdf
import pytest
import pyzipper

from tests.test_cli import BUNDLE
from traffic_complaint_form import cli
from traffic_complaint_form.cli import main
from traffic_complaint_form.models import MAX_BATCH_CASES, CaseBatch, TriState

BUNDLE_V2 = {
    **{k: v for k, v in BUNDLE.items() if k != "version"},
    "version": 2,
    "archive_password": "invented-archive-password",
    "archive_format": "zip-legacy",
}

CASE = {
    "vehicle_number": "98-765-43",
    "vehicle_manufacturer": "סקודה",
    "vehicle_color": "אפור",
    "offence_date": "2026-02-01",
    "offence_time": "09:15",
    "offence_street": "רחוב המבחן",
    "offence_city": "ירושלים",
    "offence_description": "חניה על המדרכה.",
}

CANARY = "private-case-canary-98-765-43"


def set_env(monkeypatch, bundle=None):
    monkeypatch.setenv("FILING_BUNDLE", json.dumps(BUNDLE_V2 if bundle is None else bundle))


# --- model ---


def test_batch_model_valid():
    batch = CaseBatch.from_dict({"cases": [CASE, CASE]})
    assert len(batch.cases) == 2
    assert batch.cases[0].vehicle.number == CASE["vehicle_number"]


@pytest.mark.parametrize(
    "payload",
    [{}, {"cases": []}, {"cases": CASE}, {"cases": [CASE], "extra": 1}, [CASE], "cases"],
)
def test_batch_model_rejects_bad_shape(payload):
    with pytest.raises(ValueError):
        CaseBatch.from_dict(payload)


def test_batch_model_cap():
    with pytest.raises(ValueError, match=f"limit is {MAX_BATCH_CASES}"):
        CaseBatch.from_dict({"cases": [CASE] * (MAX_BATCH_CASES + 1)})


def test_batch_model_reports_case_index_only():
    payload = {"cases": [CASE, {**CASE, "vehicle_number": ""}, "not-an-object"]}
    with pytest.raises(ValueError) as error:
        CaseBatch.from_dict(payload)
    assert "case #2: missing required input: vehicle_number" in str(error.value)
    assert "case #3: must be an object" in str(error.value)
    assert CASE["vehicle_number"] not in str(error.value)


def test_tristate_error_never_echoes_value():
    with pytest.raises(ValueError) as error:
        TriState.parse(CANARY)
    assert CANARY not in str(error.value)


def test_batch_model_bad_field_reports_index_without_value():
    payload = {"cases": [{**CASE, "knows_driver": CANARY}]}
    with pytest.raises(ValueError) as error:
        CaseBatch.from_dict(payload)
    assert "case #1:" in str(error.value)
    assert CANARY not in str(error.value)


# --- CLI ---


def test_batch_sample_dry_run_end_to_end(monkeypatch, tmp_path, caplog):
    set_env(monkeypatch)
    with caplog.at_level(logging.INFO):
        assert main(["--batch-sample", "--out-dir", str(tmp_path), "--dry-run"]) == 0
    zips = list(tmp_path.glob("*.zip"))
    assert len(zips) == 1
    with pyzipper.AESZipFile(zips[0]) as z:
        assert z.namelist() == ["complaint-01.pdf", "complaint-02.pdf"]
        with pytest.raises(RuntimeError):
            z.read("complaint-01.pdf")
        z.setpassword(BUNDLE_V2["archive_password"].encode())
        for name in z.namelist():
            with pikepdf.open(__import__("io").BytesIO(z.read(name))) as pdf:
                assert 1 <= len(pdf.pages) <= 3
    for canary in ["12-345-67", BUNDLE_V2["archive_password"], BUNDLE_V2["complainant"]["id_number"]]:
        assert canary not in caplog.text
    assert "complaint" not in zips[0].name or "12-345" not in zips[0].name


def test_batch_requires_v2_bundle(monkeypatch, tmp_path, caplog):
    set_env(monkeypatch, bundle=BUNDLE)  # version 1
    with caplog.at_level(logging.INFO):
        assert main(["--batch-sample", "--out-dir", str(tmp_path), "--dry-run"]) == 2
    assert "archive_password" in caplog.text
    assert not list(tmp_path.iterdir())


def test_batch_encrypted_requires_private_key(monkeypatch, tmp_path):
    set_env(monkeypatch)
    monkeypatch.delenv("CASE_DATA_PRIVATE_KEY", raising=False)
    payload = tmp_path / "batch.enc"
    payload.write_text("anything")
    assert main(["--batch-encrypted", str(payload), "--out-dir", str(tmp_path / "o"), "--dry-run"]) == 2


def test_batch_encrypted_roundtrip_and_log_privacy(monkeypatch, tmp_path, caplog):
    set_env(monkeypatch)
    from traffic_complaint_form.crypto import encrypt_payload, generate_keypair

    public_b64, private_b64 = generate_keypair()
    monkeypatch.setenv("CASE_DATA_PRIVATE_KEY", private_b64)
    payload = tmp_path / "batch.enc"
    payload.write_text(encrypt_payload(public_b64, json.dumps({"cases": [CASE, CASE]}).encode()))
    with caplog.at_level(logging.INFO):
        assert main(["--batch-encrypted", str(payload), "--out-dir", str(tmp_path / "out"), "--dry-run"]) == 0
    zips = list((tmp_path / "out").glob("*.zip"))
    assert len(zips) == 1
    assert CANARY not in caplog.text
    assert CASE["vehicle_number"] not in caplog.text
    assert CASE["vehicle_number"] not in zips[0].name


def test_batch_invalid_payload_never_renders_or_mails(monkeypatch, tmp_path, caplog):
    set_env(monkeypatch)
    from traffic_complaint_form.crypto import encrypt_payload, generate_keypair

    public_b64, private_b64 = generate_keypair()
    monkeypatch.setenv("CASE_DATA_PRIVATE_KEY", private_b64)
    payload = tmp_path / "batch.enc"
    payload.write_text(encrypt_payload(public_b64, json.dumps({"cases": [{**CASE, "vehicle_number": ""}]}).encode()))
    monkeypatch.setattr(cli, "render_form", lambda *a, **k: pytest.fail("must not render"))
    monkeypatch.setattr(cli, "send_encrypted_archive", lambda **k: pytest.fail("must not send"))
    with caplog.at_level(logging.INFO):
        assert main(["--batch-encrypted", str(payload), "--out-dir", str(tmp_path), "--dry-run"]) == 2
    assert "case #1:" not in caplog.text  # contents withheld at the CLI boundary
    assert CASE["vehicle_number"] not in caplog.text


def test_batch_overflow_returns_3(monkeypatch, tmp_path):
    set_env(monkeypatch)
    monkeypatch.setattr(cli, "html_to_pdf", lambda *a, **k: 5)
    assert main(["--batch-sample", "--out-dir", str(tmp_path), "--dry-run"]) == 3


def test_batch_archive_failure_leaves_no_file(monkeypatch, tmp_path, caplog):
    set_env(monkeypatch)

    def boom(*a, **k):
        raise RuntimeError("injected archive failure " + CANARY)

    monkeypatch.setattr(cli, "create_archive", boom)
    with caplog.at_level(logging.INFO):
        assert main(["--batch-sample", "--out-dir", str(tmp_path), "--dry-run"]) == 1
    assert CANARY not in caplog.text
    assert not list(tmp_path.glob("*.zip"))


def test_batch_send_path_calls_mail(monkeypatch, tmp_path):
    set_env(monkeypatch)
    sent = {}
    monkeypatch.setattr(cli, "send_encrypted_archive", lambda **k: sent.update(k))
    assert main(["--batch-sample", "--out-dir", str(tmp_path)]) == 0
    assert sent["case_count"] == 2
    assert sent["archive_path"].suffix == ".zip"
    assert sent["recipient"] == BUNDLE_V2["delivery"]["recipient_email"]


def test_batch_mail_subject_ascii(monkeypatch, tmp_path):
    set_env(monkeypatch)
    captured = {}

    class FakeSMTP:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def ehlo(self):
            pass

        def starttls(self):
            pass

        def login(self, u, p):
            pass

        def send_message(self, message):
            captured["subject"] = message["Subject"]
            captured["filename"] = next(message.iter_attachments()).get_filename()
            return {}

    from traffic_complaint_form import mail

    monkeypatch.setattr(
        cli, "send_encrypted_archive", lambda **k: mail.send_encrypted_archive(smtp_factory=FakeSMTP, **k)
    )
    assert main(["--batch-sample", "--out-dir", str(tmp_path)]) == 0
    assert captured["subject"].isascii()
    assert "batch of 2" in captured["subject"]
    assert captured["subject"].startswith("[TEST] ")
    assert captured["filename"].endswith(".zip")


# --- Size-capped splitting (#51) ---


def test_batch_splits_into_multiple_emails(monkeypatch, tmp_path):
    set_env(monkeypatch)
    from traffic_complaint_form.archive import pack_members as real_pack

    def capped_pack(members, *, max_bytes, password, fmt):
        biggest = max(p.stat().st_size for _, p in members)
        return real_pack(members, max_bytes=biggest + 600, password=password, fmt=fmt)

    monkeypatch.setattr(cli, "pack_members", capped_pack)
    sent = []
    monkeypatch.setattr(cli, "send_encrypted_archive", lambda **k: sent.append(k))
    assert main(["--batch-sample", "--out-dir", str(tmp_path)]) == 0
    assert len(sent) == 2
    assert (sent[0]["part"], sent[0]["total_parts"]) == (1, 2)
    assert (sent[1]["part"], sent[1]["total_parts"]) == (2, 2)
    names = sorted(p.name for p in tmp_path.glob("*.zip"))
    assert "part1of2" in names[0] and "part2of2" in names[1]
    # Global member numbering across parts, payload order preserved.
    import pyzipper as pz

    all_members = []
    for part in sent:
        with pz.AESZipFile(part["archive_path"]) as z:
            z.setpassword(BUNDLE_V2["archive_password"].encode())
            all_members += z.namelist()
    assert all_members == ["complaint-01.pdf", "complaint-02.pdf"]


def test_batch_oversized_single_document_aborts_before_mail(monkeypatch, tmp_path, caplog):
    set_env(monkeypatch)

    def boom(members, *, max_bytes, password, fmt):
        from traffic_complaint_form.archive import OversizedMemberError

        raise OversizedMemberError("member complaint-01.pdf alone is over the 100-byte archive cap")

    monkeypatch.setattr(cli, "pack_members", boom)
    monkeypatch.setattr(cli, "send_encrypted_archive", lambda **k: pytest.fail("must not send"))
    with caplog.at_level(logging.INFO):
        assert main(["--batch-sample", "--out-dir", str(tmp_path)]) == 3
    assert "cannot be split" in caplog.text
    assert not list(tmp_path.glob("*.zip"))


def test_batch_multipart_subject_and_body(monkeypatch, tmp_path):
    from traffic_complaint_form import mail

    captured = []

    class FakeSMTP:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def ehlo(self):
            pass

        def starttls(self):
            pass

        def login(self, u, p):
            pass

        def send_message(self, message):
            captured.append(str(message["Subject"]))
            return {}

    part_path = tmp_path / "part.zip"
    part_path.write_bytes(b"PK\x05\x06" + b"\0" * 18)
    mail.send_encrypted_archive(
        smtp_host="h",
        smtp_port=587,
        smtp_username="u",
        smtp_password="p",
        from_address="a@b.c",
        recipient="r@b.c",
        archive_path=part_path,
        case_count=7,
        batch_date="04/11/2026",
        part=2,
        total_parts=3,
        smtp_factory=FakeSMTP,
    )
    assert captured == ["Traffic complaint forms - batch of 7 - part 2 of 3 - 04/11/2026"]
    assert captured[0].isascii()
