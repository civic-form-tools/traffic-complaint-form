"""Fill, encrypt and email complaint forms using one mandatory FILING_BUNDLE secret.

Single mode fills one form and emails it as an individually locked PDF.
Batch mode (--batch-encrypted/--batch-sample) fills several forms as OPEN
PDFs and emails them inside one password-encrypted archive; the archive is
the encryption layer (FILING_BUNDLE v2: archive_password, archive_format).

Sample/test mode only adds a watermark. Encryption and the complete bundle
remain mandatory in every mode. Separate legacy secrets are never consulted.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from .archive import ArchiveVerificationError, OversizedMemberError, create_archive, pack_members, verify_archive
from .config import BundleError, FilingConfig
from .encrypt import encrypt_pdf, verify_encrypted_pdf
from .fill import render_form, template_base_url
from .mail import send_encrypted_archive, send_encrypted_pdf
from .models import JERUSALEM_TZ, CaseBatch, CaseData
from .pdf import html_to_pdf
from .sample import sample_batch, sample_case

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
    source.add_argument(
        "--batch-encrypted",
        type=Path,
        help='Path to a sealed-box encrypted BATCH payload ({"cases": [...]}, base64). '
        "Requires CASE_DATA_PRIVATE_KEY and a version-2 FILING_BUNDLE (archive_password).",
    )
    source.add_argument(
        "--batch-sample",
        action="store_true",
        help="Batch mode with invented sample cases (pipeline test)",
    )
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
    if (args.case_encrypted or args.batch_encrypted) and not os.environ.get("CASE_DATA_PRIVATE_KEY", "").strip():
        logger.error("Missing required secret environment variables (names only): CASE_DATA_PRIVATE_KEY")
        return EXIT_MISSING_CONFIG
    test_mode = is_test_mode()
    if not encrypt_output:
        logger.error("PDF encryption is mandatory in every mode - refusing to run")
        return EXIT_UNSAFE
    batch_mode = bool(args.batch_encrypted or args.batch_sample)
    try:
        config = FilingConfig.from_env(os.environ, require_archive=batch_mode)
    except BundleError as exc:
        logger.error("%s", exc)
        return EXIT_MISSING_CONFIG
    if batch_mode:
        return _run_batch(args, config, test_mode)
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


def _run_batch(args: argparse.Namespace, config: FilingConfig, test_mode: bool) -> int:
    """Fill N cases as OPEN PDFs, pack into one encrypted archive, email it.

    Fail-fast (user decision 2026-11-04): all cases are validated before any
    rendering, and any failure aborts the run - no partial archive is mailed.
    Per-PDF encryption stays ON for single mode only; batch members are open
    by design and the archive is the encryption layer.
    """
    if args.batch_encrypted:
        from .crypto import CaseDecryptionError, decrypt_payload

        try:
            payload = decrypt_payload(
                os.environ["CASE_DATA_PRIVATE_KEY"], args.batch_encrypted.read_text(encoding="utf-8")
            )
            batch = CaseBatch.from_dict(json.loads(payload.decode("utf-8")))
        except (CaseDecryptionError, ValueError, json.JSONDecodeError):
            logger.error("Invalid encrypted batch data (contents withheld)")
            return EXIT_MISSING_CONFIG
        digest = hashlib.sha256(args.batch_encrypted.read_bytes()).hexdigest()[:8]
        logger.info("Batch payload decrypted in memory (%s cases, contents stay out of logs)", len(batch.cases))
    else:
        batch = sample_batch()
        digest = "sample"

    args.out_dir.mkdir(parents=True, exist_ok=True)
    today = datetime.now(JERUSALEM_TZ).date()

    with tempfile.TemporaryDirectory(prefix="tcf-batch-") as tmp:
        members: list[tuple[str, Path]] = []
        for index, case in enumerate(batch.cases, start=1):
            member_path = Path(tmp) / f"complaint-{index:02d}.pdf"
            try:
                html_text = render_form(case, config.complainant, test_mode=test_mode)
                pages = html_to_pdf(html_text, base_url=template_base_url(), out_path=member_path)
            except Exception:
                logger.error("Failed to render case #%s (details withheld)", index)
                return EXIT_FAILED
            max_pages = 3 if len(case.incidents) > 1 else 1
            if not 1 <= pages <= max_pages:
                logger.error(
                    "Case #%s rendered %s pages, expected %s - shorten the description(s)",
                    index,
                    pages,
                    "1" if max_pages == 1 else f"1-{max_pages}",
                )
                return EXIT_OVERFLOW
            members.append((f"complaint-{index:02d}.pdf", member_path))
        cap_bytes = config.max_archive_mb * 1024 * 1024
        try:
            groups = pack_members(
                members, max_bytes=cap_bytes, password=config.archive_password, fmt=config.archive_format
            )
        except OversizedMemberError as exc:
            # Message carries a neutral member name and byte counts only.
            logger.error("%s - a single document cannot be split; shrink the case's PDF", exc)
            return EXIT_OVERFLOW
        archives: list[Path] = []
        total = len(groups)
        for part, group in enumerate(groups, start=1):
            suffix = f"-part{part}of{total}" if total > 1 else ""
            out_path = args.out_dir / f"traffic-complaints-batch-{today.isoformat()}-{digest}{suffix}.zip"
            try:
                create_archive(group, out_path, password=config.archive_password, fmt=config.archive_format)
                verify_archive(
                    out_path, password=config.archive_password, expected_members=len(group), max_bytes=cap_bytes
                )
            except ArchiveVerificationError as exc:
                # Verification messages carry counts, sizes and neutral names only.
                logger.error("Archive verification failed: %s", exc)
                for path in archives + [out_path]:
                    path.unlink(missing_ok=True)
                return EXIT_FAILED
            except Exception:
                logger.error("Archive creation failed (details withheld)")
                for path in archives + [out_path]:
                    path.unlink(missing_ok=True)
                return EXIT_FAILED
            archives.append(out_path)
            logger.info(
                "Encrypted archive part %s/%s verified (%s cases, %s bytes)",
                part,
                total,
                len(group),
                out_path.stat().st_size,
            )

    if args.dry_run:
        logger.info("Dry run: email skipped. %s encrypted archive(s) kept in %s", len(archives), args.out_dir)
        return 0

    for part, archive_path in enumerate(archives, start=1):
        try:
            send_encrypted_archive(
                smtp_host=config.delivery["smtp_host"],
                smtp_port=config.delivery["smtp_port"],
                smtp_username=config.delivery["smtp_username"],
                smtp_password=config.delivery["smtp_app_password"],
                from_address=config.delivery["smtp_from"],
                recipient=config.delivery["recipient_email"],
                archive_path=archive_path,
                case_count=len(batch.cases),
                batch_date=today.strftime("%d/%m/%Y"),
                test_mode=test_mode,
                part=part,
                total_parts=len(archives),
            )
        except Exception:
            logger.error("Email delivery failed for part %s/%s (details withheld)", part, len(archives))
            return EXIT_FAILED
    logger.info(
        "Done: %s encrypted archive(s) delivered to the configured recipient (test_mode=%s)",
        len(archives),
        test_mode,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
