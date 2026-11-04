"""Isolated fictional-data SMTP exercise. Never loads production configuration."""

from __future__ import annotations

import argparse
import io
import json
import logging
import os
import tempfile
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path

import pikepdf

from .archive import create_archive, pack_members, verify_archive
from .fill import render_form, template_base_url
from .mail import send_encrypted_archive
from .models import Complainant
from .pdf import html_to_pdf
from .sample import sample_case

logger = logging.getLogger(__name__)
DUMMY_IDENTITY = {
    "first_name": "ZZ-SYNTHETIC-NOT-A-PERSON",
    "last_name": "ZZ-TEST-ONLY",
    "id_number": "TEST-NOT-A-VALID-ID",
    "address": "ZZ-FICTIONAL-NOT-A-DELIVERY-ADDRESS",
    "phone": "NOT-A-PHONE",
}
DELIVERY_KEYS = {"recipient_email", "smtp_host", "smtp_port", "smtp_username", "smtp_app_password", "smtp_from"}


class SyntheticError(ValueError):
    """Safe, value-free configuration failure."""


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError
        result[key] = value
    return result


def load_test_config(environ):
    """Only explicitly named testing settings are accessed. No production fallback."""
    try:
        raw = environ.get("TEST_FILING_BUNDLE", "")
        approved = environ.get("TEST_APPROVED_RECIPIENT", "")
        if len(raw.encode()) > 48 * 1024:
            raise ValueError
        config = json.loads(raw, object_pairs_hook=_unique)
        if set(config) != {"version", "complainant", "pdf_password", "archive_password", "delivery"}:
            raise ValueError
        if type(config["version"]) is not int or config["version"] != 2:
            raise ValueError
        if config["complainant"] != DUMMY_IDENTITY:
            raise ValueError
        passwords = [config["pdf_password"], config["archive_password"]]
        if any(not isinstance(p, str) or not 24 <= len(p) <= 127 for p in passwords):
            raise ValueError
        if passwords[0] == passwords[1]:
            raise ValueError
        delivery = config["delivery"]
        if set(delivery) != DELIVERY_KEYS:
            raise ValueError
        for k, v in delivery.items():
            if k != "smtp_port" and (not isinstance(v, str) or not v or "\r" in v or "\n" in v):
                raise ValueError
        if type(delivery["smtp_port"]) is not int or delivery["smtp_port"] != 587:
            raise ValueError
        from email.headerregistry import Address

        for address in (approved, delivery["recipient_email"], delivery["smtp_from"], delivery["smtp_username"]):
            if Address(addr_spec=address).addr_spec != address or "@" not in address:
                raise ValueError
        if delivery["recipient_email"] != approved:
            raise ValueError
        return config, approved
    except Exception:
        raise SyntheticError("Invalid testing configuration (values withheld)") from None


class LockedSMTP:
    """Last-boundary recipient check, including explicit SMTP envelope."""

    def __init__(self, server, approved):
        self.server = server
        self.approved = approved

    def __enter__(self):
        self.server.__enter__()
        return self

    def __exit__(self, *args):
        return self.server.__exit__(*args)

    def __getattr__(self, key):
        return getattr(self.server, key)

    def send_message(self, message):
        if message.get_all("To") != [self.approved] or any(
            message.get_all(h) for h in ("Cc", "Bcc", "Resent-To", "Resent-Cc", "Resent-Bcc")
        ):
            raise SyntheticError("Testing recipient mismatch")
        message.get_body(preferencelist=("plain",)).set_content(
            "Synthetic test only. All identity and case details are fictional.\n"
            "The test archive password is configured separately in TEST_FILING_BUNDLE.\n"
            "The PDFs inside are open; only the archive is encrypted.\n\nInstinct\n"
        )
        return self.server.send_message(message, to_addrs=[self.approved])


@contextmanager
def build_archives(password, *, archive_format, split):
    """Builder receives test encryption material, never SMTP settings."""
    person = Complainant(**DUMMY_IDENTITY)
    case = sample_case()
    case = replace(case, vehicle=replace(case.vehicle, number="00-000-00"))
    with tempfile.TemporaryDirectory(prefix="tcf-synthetic-") as tmp:
        root = Path(tmp)
        members = []
        for index in range(1, 5):
            path = root / f"complaint-{index:02d}.pdf"
            pages = html_to_pdf(render_form(case, person, test_mode=True), base_url=template_base_url(), out_path=path)
            if pages != 1:
                raise SyntheticError("Synthetic PDF page count mismatch")
            if split:
                with pikepdf.open(path) as pdf:
                    pdf.attachments["synthetic-padding.bin"] = os.urandom(350_000)
                    buffer = io.BytesIO()
                    pdf.save(buffer)
                path.write_bytes(buffer.getvalue())
            members.append((path.name, path))
        cap = (1 if split else 10) * 1024 * 1024
        groups = pack_members(members, password=password, fmt=archive_format, max_bytes=cap)
        archives = []
        for number, group in enumerate(groups, 1):
            archive = root / f"synthetic-{archive_format}-part{number}of{len(groups)}.zip"
            create_archive(group, archive, password=password, fmt=archive_format)
            verify_archive(archive, password=password, expected_members=len(group), max_bytes=cap)
            archives.append(archive)
        yield tuple(archives)


def deliver_archives(archives, delivery, approved, *, smtp_factory):
    """Sender receives SMTP-only settings and verified paths."""
    for number, archive in enumerate(archives, 1):
        send_encrypted_archive(
            smtp_host=delivery["smtp_host"],
            smtp_port=delivery["smtp_port"],
            smtp_username=delivery["smtp_username"],
            smtp_password=delivery["smtp_app_password"],
            from_address=delivery["smtp_from"],
            recipient=approved,
            archive_path=archive,
            case_count=4,
            batch_date="SYNTHETIC",
            test_mode=True,
            part=number,
            total_parts=len(archives),
            smtp_factory=lambda *a, **kw: LockedSMTP(smtp_factory(*a, **kw), approved),
        )
    logger.info("Synthetic SMTP exercise accepted (%s parts)", len(archives))


def run(config, approved, *, archive_format, split, smtp_factory):
    with build_archives(config["archive_password"], archive_format=archive_format, split=split) as archives:
        deliver_archives(archives, config["delivery"], approved, smtp_factory=smtp_factory)


def main(argv=None):
    import smtplib

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-format", choices=("zip-legacy", "zip-aes"), default="zip-legacy")
    parser.add_argument("--split", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING)
    try:
        config, approved = load_test_config(os.environ)
        run(config, approved, archive_format=args.archive_format, split=args.split, smtp_factory=smtplib.SMTP)
    except Exception:
        logger.error("Synthetic exercise failed (details withheld)")
        return 1
    print("Synthetic exercise: SMTP accepted all test parts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
