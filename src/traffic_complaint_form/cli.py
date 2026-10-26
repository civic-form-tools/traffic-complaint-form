"""Fill, encrypt and email a form using one mandatory FILING_BUNDLE secret.

Sample/test mode only adds a watermark. Encryption and the complete bundle
remain mandatory in every mode. Separate legacy secrets are never consulted.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import tempfile
from pathlib import Path

from .config import BundleError, FilingConfig
from .encrypt import encrypt_pdf, verify_encrypted_pdf
from .fill import render_form, template_base_url
from .mail import send_encrypted_pdf
from .models import CaseData
from .pdf import html_to_pdf
from .sample import sample_case

logger = logging.getLogger("traffic_complaint_form")

EXIT_MISSING_CONFIG = 2
EXIT_OVERFLOW = 3
EXIT_FAILED = 1
EXIT_UNSAFE = 4


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="traffic-complaint-form", description=__doc__)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--case-json", type=Path, help="Path to a JSON object with the case data (workflow inputs)")
    source.add_argument(
        "--case-encrypted",
        type=Path,
        help="Path to a sealed-box encrypted case payload (base64). Requires CASE_DATA_PRIVATE_KEY. "
        "Use this on the public repo so plates and incident data never appear in public inputs or logs.",
    )
    source.add_argument("--sample", action="store_true", help="Use invented sample case data")
    parser.add_argument("--out-dir", type=Path, default=Path("out"), help="Directory for the encrypted PDF")
    parser.add_argument("--dry-run", action="store_true", help="Build, encrypt and verify, but skip the email")
    parser.add_argument("--validate-config", action="store_true", help="Validate bundle only; no PDF or email")
    return parser


def is_test_mode(environ: dict[str, str] | None = None) -> bool:
    env = os.environ if environ is None else environ
    return env.get("TEST_MODE", "true").strip().lower() not in {"false", "0", "no"}


def is_encrypt_output(environ: dict[str, str] | None = None) -> bool:
    env = os.environ if environ is None else environ
    return env.get("ENCRYPT_OUTPUT", "true").strip().lower() not in {"false", "0", "no"}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    encrypt_output = is_encrypt_output()
    if args.case_encrypted and not os.environ.get("CASE_DATA_PRIVATE_KEY", "").strip():
        logger.error("Missing required secret environment variables (names only): CASE_DATA_PRIVATE_KEY")
        return EXIT_MISSING_CONFIG
    test_mode = is_test_mode()
    if not encrypt_output:
        logger.error("PDF encryption is mandatory in every mode - refusing to run")
        return EXIT_UNSAFE
    try:
        config = FilingConfig.from_env(os.environ)
    except BundleError as exc:
        logger.error("%s", exc)
        return EXIT_MISSING_CONFIG
    if args.validate_config:
        logger.info("FILING_BUNDLE validation OK (values withheld); no PDF or email")
        return 0
    complainant = config.complainant
    pdf_password = config.pdf_password

    private_case = bool(args.case_encrypted)
    if args.case_encrypted:
        from .crypto import CaseDecryptionError, decrypt_payload

        try:
            payload = decrypt_payload(
                os.environ["CASE_DATA_PRIVATE_KEY"], args.case_encrypted.read_text(encoding="utf-8")
            )
            case = CaseData.from_dict(json.loads(payload.decode("utf-8")))
        except (CaseDecryptionError, ValueError, json.JSONDecodeError):
            logger.error("Invalid encrypted case data (contents withheld)")
            return EXIT_MISSING_CONFIG
        logger.info("Case data decrypted in memory (contents stay out of logs)")
    elif args.sample or not args.case_json:
        if not args.sample and not args.case_json:
            logger.info("No --case-json given; using invented sample data")
        case = sample_case()
    else:
        try:
            case = CaseData.from_dict(json.loads(args.case_json.read_text(encoding="utf-8")))
        except (ValueError, json.JSONDecodeError):
            logger.error("Invalid case data (contents withheld)")
            return EXIT_MISSING_CONFIG

    args.out_dir.mkdir(parents=True, exist_ok=True)
    if private_case:
        import hashlib

        digest = hashlib.sha256(args.case_encrypted.read_bytes()).hexdigest()[:8]
        outfile = args.out_dir / f"traffic-complaint-{case.offence.date.isoformat()}-{digest}.pdf"
    else:
        outfile = args.out_dir / f"traffic-complaint-{case.offence.date.isoformat()}-{case.vehicle.number}.pdf"

    with tempfile.TemporaryDirectory(prefix="tcf-") as tmp:
        plain_pdf = Path(tmp) / "form.pdf"
        try:
            html_text = render_form(case, complainant, test_mode=test_mode)
            pages = html_to_pdf(html_text, base_url=template_base_url(), out_path=plain_pdf)
        except Exception:
            logger.error("Failed to render the form PDF (details withheld)")
            return EXIT_FAILED
        max_pages = 3 if len(case.incidents) > 1 else 1
        if not 1 <= pages <= max_pages:
            logger.error(
                "Rendered form is %s pages, expected %s - shorten the description(s)",
                pages,
                "1" if max_pages == 1 else f"1-{max_pages}",
            )
            return EXIT_OVERFLOW
        try:
            encrypt_pdf(plain_pdf, outfile, password=pdf_password)
            multi = len(case.incidents) > 1
            verify_encrypted_pdf(outfile, password=pdf_password, expected_pages=None if multi else 1)
        except Exception:
            logger.error("Encryption or post-encryption verification failed (details withheld)")
            outfile.unlink(missing_ok=True)
            return EXIT_FAILED
        logger.info("Encrypted PDF verified (%s bytes)", outfile.stat().st_size)

    if args.dry_run:
        logger.info("Dry run: email skipped. Encrypted file kept at %s", outfile.name)
        return 0

    try:
        send_encrypted_pdf(
            smtp_host=config.delivery["smtp_host"],
            smtp_port=config.delivery["smtp_port"],
            smtp_username=config.delivery["smtp_username"],
            smtp_password=config.delivery["smtp_app_password"],
            from_address=config.delivery["smtp_from"],
            recipient=config.delivery["recipient_email"],
            attachment_path=outfile,
            vehicle_number=case.vehicle.number,
            offence_date=case.offence.date.strftime("%d/%m/%Y"),
            test_mode=test_mode,
        )
    except Exception:
        logger.error("Email delivery failed (details withheld)")
        return EXIT_FAILED
    logger.info("Done: encrypted PDF delivered to the configured recipient (test_mode=%s)", test_mode)
    return 0


if __name__ == "__main__":
    sys.exit(main())
