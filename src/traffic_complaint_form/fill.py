"""Render the form HTML template with case data and complainant identity.

All dynamic values are HTML-escaped. Yes/no fields are pre-rendered as HTML
(the unselected option is struck through, mirroring the paper form's
"למחוק את המיותר" instruction).
"""

from __future__ import annotations

import html
from importlib import resources
from string import Template

from .models import CaseData, Complainant, TriState, Witness

PACKAGE = "traffic_complaint_form"
TEMPLATE_NAME = "templates/form.html"


def template_text() -> str:
    return resources.files(PACKAGE).joinpath(TEMPLATE_NAME).read_text(encoding="utf-8")


def template_base_url() -> str:
    return str(resources.files(PACKAGE).joinpath("templates"))


def _escape(value: str) -> str:
    return html.escape(value, quote=True)


def yes_no_html(value: TriState) -> str:
    yes_class = ""
    no_class = ""
    if value is TriState.YES:
        no_class = ' class="strike"'
    elif value is TriState.NO:
        yes_class = ' class="strike"'
    return f"<span{yes_class}>כן</span> / <span{no_class}>לא</span>"


def bool_yes_no_html(value: bool) -> str:
    return yes_no_html(TriState.YES if value else TriState.NO)


WATERMARK_HTML = '<div class="watermark">בדיקה - לא לשליחה</div>'


def _effective_witness(case: CaseData, complainant: Complainant) -> Witness:
    """Witness section: an explicitly given witness wins; when the case names
    no witness, the complainant himself is the witness (form requirement,
    user decision 2026-10-26).
    """
    if not case.witness.is_empty:
        return case.witness
    return Witness(
        name=f"{complainant.first_name} {complainant.last_name}",
        id_number=complainant.id_number,
        phone=complainant.phone,
        address=complainant.address,
    )


def build_mapping(case: CaseData, complainant: Complainant, *, test_mode: bool = False) -> dict[str, str]:
    witness = _effective_witness(case, complainant)
    description = "<br>\n".join(_escape(line) for line in case.offence.description.splitlines())
    return {
        "STATION": _escape(case.police_station),
        "COMPLAINT_DATE": case.complaint_date.strftime("%d/%m/%Y"),
        "VEHICLE_NUMBER": _escape(case.vehicle.number),
        "VEHICLE_MANUFACTURER": _escape(case.vehicle.manufacturer),
        "VEHICLE_COLOR": _escape(case.vehicle.color),
        "VEHICLE_TYPE": _escape(case.vehicle.type),
        "DRIVER_NAME": _escape(case.driver_name),
        "DRIVER_ADDRESS": _escape(case.driver_address),
        "CAN_IDENTIFY_DRIVER": yes_no_html(case.can_identify_driver),
        "DRIVER_MARKS": _escape(case.driver_identifying_marks),
        "KNOWS_DRIVER": yes_no_html(case.knows_driver),
        "OFFENCE_DATE": case.offence.date.strftime("%d/%m/%Y"),
        "OFFENCE_DAY": _escape(case.offence.day),
        "OFFENCE_TIME": _escape(case.offence.time),
        "OFFENCE_STREET": _escape(case.offence.street),
        "OFFENCE_JUNCTION": _escape(case.offence.junction_or_house),
        "OFFENCE_CITY": _escape(case.offence.city),
        "OFFENCE_DESCRIPTION": description,
        "C_FIRST_NAME": _escape(complainant.first_name),
        "C_LAST_NAME": _escape(complainant.last_name),
        "C_ID": _escape(complainant.id_number),
        "C_ADDRESS": _escape(complainant.address),
        "C_PHONE": _escape(complainant.phone),
        "WILLING_TO_TESTIFY": bool_yes_no_html(case.willing_to_testify),
        "WITNESS_NAME": _escape(witness.name),
        "WITNESS_ID": _escape(witness.id_number),
        "WITNESS_PHONE": _escape(witness.phone),
        "WITNESS_ADDRESS": _escape(witness.address),
        "WATERMARK": WATERMARK_HTML if test_mode else "",
    }


def render_form(case: CaseData, complainant: Complainant, *, test_mode: bool = False) -> str:
    """Return the filled form as a standalone HTML document.

    test_mode adds a diagonal בדיקה watermark so a test deliverable can never
    be mistaken for a real complaint.
    """
    return Template(template_text()).substitute(build_mapping(case, complainant, test_mode=test_mode))
