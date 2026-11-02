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

BODY_REAL = (
    "מצורף טופס התלונה הממולא, מוצפן בסיסמה.\n"
    "הסיסמה היא הסיסמה הייעודית שהוגדרה בשדה pdf_password של FILING_BUNDLE.\n\n"
    + ENCRYPTION_NOTE
    + "הודעה אוטומטית ממערכת traffic-complaint-form."
)

BODY_REAL_PER_CALL = (
    "מצורף טופס התלונה הממולא, מוצפן בסיסמה.\n"
    "הסיסמה היא הסיסמה האישית שבחרת בעת שליחת הטופס.\n\n"
    + ENCRYPTION_NOTE
    + "הודעה אוטומטית ממערכת traffic-complaint-form. "
    "אם לא ביקשת הודעה זו, ניתן לדווח דרך דף האבטחה של המאגר ב-GitHub.\n"
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
    per_call_password: bool = False,
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
    # Fixed templates only: caller free text never reaches subject or body.
    body = BODY_TEST if test_mode else (BODY_REAL_PER_CALL if per_call_password else BODY_REAL)
    message.set_content(body)
    message.add_attachment(
        attachment_path.read_bytes(),
        maintype="application",
        subtype="pdf",
        filename=attachment_path.name,
    )
    with smtp_factory(smtp_host, smtp_port, timeout=60) as server:
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.login(smtp_username, smtp_password)
        refused = server.send_message(message)
    if refused:
        raise RuntimeError(f"SMTP server refused {len(refused)} recipient(s)")
    logger.info("SMTP accepted the message for delivery")
