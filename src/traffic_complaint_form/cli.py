"""Fill the complaint form, encrypt the PDF and email it.

Secrets arrive only via environment variables mapped from GitHub Secrets.
Missing configuration is reported by variable NAME only; values are never
printed. The run fails fast on missing configuration before any real work.

TEST_MODE (GitHub Actions variable, default "true") watermarks the PDF and
tags the email subject so a test deliverable can never be confused with a
real complaint. Set it to "false" only after real secrets are loaded.

ENCRYPT_OUTPUT (GitHub Actions variable, default "true") controls PDF
encryption. It may be "false" only while TEST_MODE is "true" (dummy data);
with real values the CLI refuses to deliver an unencrypted form.

PDF password resolution (user decision, 2026-10-26): the dedicated
PDF_PASSWORD secret is the documented primary for real data. When it is
unset, TEST_MODE falls back to the complainant ID number - convenient for
pipeline tests but low-entropy (9 digits, offline-brute-forceable), an
explicitly accepted tradeoff for test data only. Outside test mode a
missing PDF_PASSWORD fails the run before any work, by NAME only.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import tempfile
from pathlib import Path

from .encrypt import encrypt_pdf, verify_encrypted_pdf
from .fill import render_form, template_base_url
from .mail import send_encrypted_pdf
from .models import COMPLAINANT_ENV_VARS, DELIVERY_ENV_VARS, OPTIONAL_DELIVERY_ENV_VARS, CaseData, Complainant
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
    return parser


def is_test_mode(environ: dict[str, str] | None = None) -> bool:
    env = os.environ if environ is None else environ
    return env.get("TEST_MODE", "true").strip().lower() not in {"false", "0", "no"}


def is_encrypt_output(environ: dict[str, str] | None = None) -> bool:
    env = os.environ if environ is None else environ
    return env.get("ENCRYPT_OUTPUT", "true").strip().lower() not in {"false", "0", "no"}


def required_secret_names(*, dry_run: bool, encrypt_output: bool = True, test_mode: bool = True) -> list[str]:
    names = list(COMPLAINANT_ENV_VARS)
    if encrypt_output and not test_mode:
        # Real data: the dedicated secret is mandatory. Test mode may fall
        # back to the complainant ID (already required above).
        names.append("PDF_PASSWORD")
    if not dry_run:
        names += [
            name for name in DELIVERY_ENV_VARS if name != "PDF_PASSWORD" and name not in OPTIONAL_DELIVERY_ENV_VARS
        ]
    return names


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    encrypt_output = is_encrypt_output()
    if args.case_encrypted and not os.environ.get("CASE_DATA_PRIVATE_KEY", "").strip():
        logger.error("Missing required secret environment variables (names only): CASE_DATA_PRIVATE_KEY")
        return EXIT_MISSING_CONFIG
    test_mode = is_test_mode()
    if not encrypt_output and not test_mode:
        logger.error("ENCRYPT_OUTPUT=false is allowed only while TEST_MODE=true (dummy data) - refusing to run")
        return EXIT_UNSAFE

    def _is_set(name: str) -> bool:
        # Value stays inside this helper; only the boolean leaves, so the
        # names-only error below can never carry a secret into the logs.
        return bool(os.environ.get(name, "").strip())

    missing = [
        name
        for name in required_secret_names(dry_run=args.dry_run, encrypt_output=encrypt_output, test_mode=test_mode)
        if not _is_set(name)
    ]
    if missing:
        logger.error("Missing required secret environment variables (names only): %s", ", ".join(missing))
        return EXIT_MISSING_CONFIG

    complainant, complainant_missing = Complainant.from_env()
    if complainant is None:
        logger.error("Missing complainant secrets: %s", ", ".join(complainant_missing))
        return EXIT_MISSING_CONFIG
    for warning in complainant.checksum_warnings():
        logger.warning("%s", warning)

    pdf_password = None
    if encrypt_output:
        pdf_password = os.environ.get("PDF_PASSWORD", "").strip() or None
        if pdf_password is None and test_mode:
            pdf_password = complainant.id_number
            logger.info(
                "TEST_MODE: PDF_PASSWORD unset - encrypting with the complainant ID "
                "(low entropy, accepted for test data only)"
            )

    private_case = bool(args.case_encrypted)
    if args.case_encrypted:
        from .crypto import CaseDecryptionError, decrypt_payload

        try:
            payload = decrypt_payload(
                os.environ["CASE_DATA_PRIVATE_KEY"], args.case_encrypted.read_text(encoding="utf-8")
            )
            case = CaseData.from_dict(json.loads(payload.decode("utf-8")))
        except (CaseDecryptionError, ValueError, json.JSONDecodeError) as exc:
            logger.error("Invalid encrypted case data: %s", exc)
            return EXIT_MISSING_CONFIG
        logger.info("Case data decrypted in memory (contents stay out of logs)")
    elif args.sample or not args.case_json:
        if not args.sample and not args.case_json:
            logger.info("No --case-json given; using invented sample data")
        case = sample_case()
    else:
        try:
            case = CaseData.from_dict(json.loads(args.case_json.read_text(encoding="utf-8")))
        except (ValueError, json.JSONDecodeError) as exc:
            logger.error("Invalid case data: %s", exc)
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
            logger.exception("Failed to render the form PDF")
            return EXIT_FAILED
        max_pages = 3 if len(case.incidents) > 1 else 1
        if not 1 <= pages <= max_pages:
            logger.error(
                "Rendered form is %s pages, expected %s - shorten the description(s)",
                pages,
                "1" if max_pages == 1 else f"1-{max_pages}",
            )
            return EXIT_OVERFLOW
        if encrypt_output:
            if pdf_password is None:
                logger.error("PDF_PASSWORD is required outside TEST_MODE (name only) - refusing to run")
                return EXIT_MISSING_CONFIG
            try:
                encrypt_pdf(plain_pdf, outfile, password=pdf_password)
                multi = len(case.incidents) > 1
                verify_encrypted_pdf(outfile, password=pdf_password, expected_pages=None if multi else 1)
            except Exception:
                logger.exception("Encryption or post-encryption verification failed")
                outfile.unlink(missing_ok=True)
                return EXIT_FAILED
            logger.info("Encrypted PDF verified: password required, exactly 1 page (%s bytes)", outfile.stat().st_size)
        else:
            plain_pdf.replace(outfile)
            logger.info(
                "ENCRYPT_OUTPUT=false (test mode): delivering the PDF unencrypted, %s bytes", outfile.stat().st_size
            )

    if args.dry_run:
        logger.info("Dry run: email skipped. Encrypted file kept at %s", outfile.name)
        return 0

    try:
        send_encrypted_pdf(
            smtp_host=os.environ["SMTP_HOST"],
            smtp_port=int(os.environ.get("SMTP_PORT", "").strip() or "587"),
            smtp_username=os.environ["SMTP_USERNAME"],
            smtp_password=os.environ["SMTP_APP_PASSWORD"],
            from_address=os.environ["SMTP_FROM"],
            recipient=os.environ["RECIPIENT_EMAIL"],
            attachment_path=outfile,
            vehicle_number=case.vehicle.number,
            offence_date=case.offence.date.strftime("%d/%m/%Y"),
            test_mode=test_mode,
        )
    except Exception:
        logger.exception("Email delivery failed; encrypted file kept at %s", outfile)
        return EXIT_FAILED
    logger.info("Done: encrypted PDF delivered to the configured recipient (test_mode=%s)", test_mode)
    return 0


if __name__ == "__main__":
    sys.exit(main())
