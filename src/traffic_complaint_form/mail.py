"""Deliver the encrypted PDF over Gmail SMTP (STARTTLS + app password).

Only delivery status is logged, never credentials, recipients or content.
"""

from __future__ import annotations

import logging
import smtplib
from collections.abc import Callable
from email.message import EmailMessage
from pathlib import Path

logger = logging.getLogger(__name__)

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587

BODY_REAL = (
    "מצורף טופס התלונה הממולא, מוצפן בסיסמה.\n"
    "הסיסמה היא הסיסמה הייעודית שהוגדרה ב-GitHub Secret בשם PDF_PASSWORD.\n\n"
    "הודעה אוטומטית ממערכת traffic-complaint-form."
)

BODY_TEST = (
    "מצורף טופס תלונה לדוגמה, מוצפן בסיסמה.\n"
    "אם הוגדר PDF_PASSWORD - זו הסיסמה; אחרת (ברירת מחדל במצב בדיקה) - מספר תעודת הזהות.\n\n"
    "הודעה אוטומטית ממערכת traffic-complaint-form."
)


def send_encrypted_pdf(
    *,
    smtp_username: str,
    smtp_password: str,
    recipient: str,
    attachment_path: Path,
    vehicle_number: str,
    offence_date: str,
    test_mode: bool = False,
    smtp_factory: Callable[..., smtplib.SMTP] = smtplib.SMTP,
) -> None:
    message = EmailMessage()
    message["From"] = smtp_username
    message["To"] = recipient
    prefix = "[בדיקה] " if test_mode else ""
    message["Subject"] = f"{prefix}תלונה על עבירת תנועה - רכב {vehicle_number} - {offence_date}"
    message.set_content(BODY_TEST if test_mode else BODY_REAL)
    message.add_attachment(
        attachment_path.read_bytes(),
        maintype="application",
        subtype="pdf",
        filename=attachment_path.name,
    )
    with smtp_factory(SMTP_HOST, SMTP_PORT, timeout=60) as server:
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.login(smtp_username, smtp_password)
        refused = server.send_message(message)
    if refused:
        raise RuntimeError(f"SMTP server refused {len(refused)} recipient(s)")
    logger.info("SMTP accepted the message for delivery")
