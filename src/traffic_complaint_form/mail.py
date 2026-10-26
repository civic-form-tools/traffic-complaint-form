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
    prefix = "[בדיקה] " if test_mode else ""
    message["Subject"] = f"{prefix}תלונה על עבירת תנועה - רכב {vehicle_number} - {offence_date}"
    message.set_content(BODY_TEST if test_mode else BODY_REAL)
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
