"""Deliver the encrypted PDF over SMTP (STARTTLS + app password).

Host, port, username, password and From are all secret-driven; nothing is
hardcoded to a provider. Only delivery status is logged, never credentials,
recipients or content.
"""

from __future__ import annotations

import logging
import smtplib
from collections.abc import Callable
from email.message import EmailMessage
from pathlib import Path

logger = logging.getLogger(__name__)

ENCRYPTION_NOTE = (
    "שים לב: הקובץ מוצפן בכוונה, ולכן שירותי דואר (למשל וואלה) עשויים "
    "לסמן אזהרת 'unscannable' עליו - זה צפוי ואינו תקלה.\n\n"
)

BODY_BATCH_REAL = (
    "מצורף קובץ ZIP אחד מוצפן ובו מספר טופסי תלונה ממולאים.\n"
    "הסיסמה היא הסיסמה שהוגדרה בשדה archive_password של FILING_BUNDLE.\n"
    "הטפסים בתוך קובץ ה-ZIP אינם נעולים בנפרד - ההצפנה היא על קובץ ה-ZIP עצמו.\n\n"
    + ENCRYPTION_NOTE
    + "הודעה אוטומטית ממערכת traffic-complaint-form."
)

BODY_BATCH_PART_REAL = (
    "מצורף חלק {part} מתוך {total} של קובצי ZIP מוצפנים עם טופסי התלונה הממולאים.\n"
    "כל החלקים מוצפנים באותה סיסמה - השדה archive_password של FILING_BUNDLE.\n"
    "הטפסים בתוך קובצי ה-ZIP אינם נעולים בנפרד - ההצפנה היא על קובצי ה-ZIP עצמם.\n\n"
    + ENCRYPTION_NOTE
    + "הודעה אוטומטית ממערכת traffic-complaint-form."
)

BODY_BATCH_TEST = (
    "מצורף קובץ ZIP לדוגמה, מוצפן בסיסמה.\n"
    "הסיסמה הוגדרה בשדה archive_password של FILING_BUNDLE.\n\n"
    + ENCRYPTION_NOTE
    + "הודעה אוטומטית ממערכת traffic-complaint-form."
)

BODY_REAL = (
    "מצורף טופס התלונה הממולא, מוצפן בסיסמה.\n"
    "הסיסמה היא הסיסמה הייעודית שהוגדרה בשדה pdf_password של FILING_BUNDLE.\n\n"
    + ENCRYPTION_NOTE
    + "הודעה אוטומטית ממערכת traffic-complaint-form."
)

BODY_TEST = (
    "מצורף טופס תלונה לדוגמה, מוצפן בסיסמה.\n"
    "הסיסמה הוגדרה בשדה pdf_password של FILING_BUNDLE.\n\n"
    + ENCRYPTION_NOTE
    + "הודעה אוטומטית ממערכת traffic-complaint-form."
)


def send_encrypted_pdf(
    *,
    smtp_host: str,
    smtp_port: int,
    smtp_username: str,
    smtp_password: str,
    from_address: str,
    recipient: str,
    attachment_path: Path,
    vehicle_number: str,
    offence_date: str,
    test_mode: bool = False,
    smtp_factory: Callable[..., smtplib.SMTP] = smtplib.SMTP,
) -> None:
    message = EmailMessage()
    message["From"] = from_address
    message["To"] = recipient
    # ASCII-only subject: some receiving gateways (e.g. walla) prepend a
    # warning to the Subject when they cannot scan the encrypted attachment,
    # which breaks RFC 2047 decoding of a non-ASCII subject.
    prefix = "[TEST] " if test_mode else ""
    message["Subject"] = f"{prefix}Traffic complaint form - vehicle {vehicle_number} - {offence_date}"
    message.set_content(BODY_TEST if test_mode else BODY_REAL)
    message.add_attachment(
        attachment_path.read_bytes(),
        maintype="application",
        subtype="pdf",
        filename=attachment_path.name,
    )
    _deliver(message, smtp_host, smtp_port, smtp_username, smtp_password, smtp_factory)


def _deliver(
    message: EmailMessage,
    smtp_host: str,
    smtp_port: int,
    smtp_username: str,
    smtp_password: str,
    smtp_factory: Callable[..., smtplib.SMTP],
) -> None:
    with smtp_factory(smtp_host, smtp_port, timeout=60) as server:
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.login(smtp_username, smtp_password)
        refused = server.send_message(message)
    if refused:
        raise RuntimeError(f"SMTP server refused {len(refused)} recipient(s)")
    logger.info("SMTP accepted the message for delivery")


def send_encrypted_archive(
    *,
    smtp_host: str,
    smtp_port: int,
    smtp_username: str,
    smtp_password: str,
    from_address: str,
    recipient: str,
    archive_path: Path,
    case_count: int,
    batch_date: str,
    test_mode: bool = False,
    part: int = 1,
    total_parts: int = 1,
    smtp_factory: Callable[..., smtplib.SMTP] = smtplib.SMTP,
) -> None:
    """Deliver one encrypted ZIP holding several open complaint PDFs (batch mode).

    An over-cap batch is split into parts (user decision 2026-11-04): each
    part is its own encrypted ZIP and email, all with the same password.
    """
    message = EmailMessage()
    message["From"] = from_address
    message["To"] = recipient
    # ASCII-only subject, same walla-gateway reason as the single-form mail.
    prefix = "[TEST] " if test_mode else ""
    part_text = f" - part {part} of {total_parts}" if total_parts > 1 else ""
    message["Subject"] = f"{prefix}Traffic complaint forms - batch of {case_count}{part_text} - {batch_date}"
    if test_mode:
        body = BODY_BATCH_TEST
    elif total_parts > 1:
        body = BODY_BATCH_PART_REAL.replace("{part}", str(part)).replace("{total}", str(total_parts))
    else:
        body = BODY_BATCH_REAL
    message.set_content(body)
    message.add_attachment(
        archive_path.read_bytes(),
        maintype="application",
        subtype="zip",
        filename=archive_path.name,
    )
    _deliver(message, smtp_host, smtp_port, smtp_username, smtp_password, smtp_factory)
