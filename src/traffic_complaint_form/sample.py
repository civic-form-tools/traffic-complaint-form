"""Invented sample case data for pipeline testing.

All values are fictional. Used with --sample or the sample_data workflow
input so the full pipeline can be exercised before real secrets are loaded.
"""

from __future__ import annotations

from datetime import date

from .models import CaseData, Offence, TriState, Vehicle, hebrew_weekday


def sample_case() -> CaseData:
    offence_date = date(2026, 1, 15)
    return CaseData(
        police_station="מוריה",
        complaint_date=date(2026, 1, 16),
        vehicle=Vehicle(number="12-345-67", manufacturer="טויוטה", color="לבן", type="פרטי"),
        offence=Offence(
            date=offence_date,
            day=hebrew_weekday(offence_date),
            time="14:30",
            street="רחוב הדוגמה",
            junction_or_house="מס' 7",
            city="ירושלים",
            description=(
                "הרכב חנה על המדרכה וחסם לחלוטין את המעבר להולכי רגל. "
                "עוברי אורח נאלצו לרדת לכביש. זוהי דוגמה בדייקנית לצורך בדיקת הצינור בלבד."
            ),
        ),
        can_identify_driver=TriState.UNKNOWN,
        knows_driver=TriState.UNKNOWN,
        willing_to_testify=True,
    )
