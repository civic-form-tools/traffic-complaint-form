"""Invented sample case data for pipeline testing.

All values are fictional. Used with --sample or the sample_data workflow
input so the full pipeline can be exercised before real secrets are loaded.
"""

from __future__ import annotations

from datetime import date

from .models import CaseData, Incident, Offence, TriState, Vehicle, hebrew_weekday


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


def sample_multi_case() -> CaseData:
    """Invented merged complaint: one vehicle, three incidents. Fictional values."""
    base = sample_case()
    incidents = (
        Incident(
            date=date(2026, 1, 5),
            day=hebrew_weekday(date(2026, 1, 5)),
            time="07:50",
            street="רחוב הדוגמה",
            junction_or_house="מס' 7",
            city="ירושלים",
            description="חניה על המדרכה, חסימה מלאה של מעבר הולכי רגל.",
            municipal_case="2610-0000001",
        ),
        Incident(
            date=date(2026, 1, 12),
            day=hebrew_weekday(date(2026, 1, 12)),
            time="16:05",
            street="רחוב הדוגמה",
            junction_or_house="מס' 7",
            city="ירושלים",
            description="חניה כפולה, חסימת נתיב תנועה.",
            municipal_case="2610-0000002",
        ),
        Incident(
            date=date(2026, 1, 19),
            day=hebrew_weekday(date(2026, 1, 19)),
            time="15:40",
            street="שדרות הדוגמה",
            junction_or_house="פינת רחוב המבחן",
            city="ירושלים",
            description="חניה על מעבר חציה.",
            municipal_case="2610-0000003",
        ),
    )
    return CaseData(
        police_station=base.police_station,
        complaint_date=base.complaint_date,
        vehicle=base.vehicle,
        offence=Offence(
            date=incidents[0].date,
            day=incidents[0].day,
            time=incidents[0].time,
            street=incidents[0].street,
            junction_or_house=incidents[0].junction_or_house,
            city=incidents[0].city,
            description=incidents[0].description,
        ),
        can_identify_driver=TriState.UNKNOWN,
        knows_driver=TriState.UNKNOWN,
        willing_to_testify=True,
        incidents=incidents,
    )
