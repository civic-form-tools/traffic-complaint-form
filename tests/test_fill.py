import re

from traffic_complaint_form.fill import build_mapping, render_form, yes_no_html
from traffic_complaint_form.models import CaseData, TriState
from traffic_complaint_form.sample import sample_case, sample_multi_case


def test_render_has_no_unfilled_placeholders(complainant):
    rendered = render_form(sample_case(), complainant)
    assert not re.search(r"\$[A-Z_]+", rendered), "unfilled $PLACEHOLDER left in the form"


def test_values_are_escaped(complainant):
    case = sample_case()
    hostile = case.__class__(**{**case.__dict__, "driver_name": "<script>alert(1)</script>"})
    rendered = render_form(hostile, complainant)
    assert "<script>alert(1)</script>" not in rendered
    assert "&lt;script&gt;" in rendered


def test_yes_no_html_strikes_unselected():
    assert 'class="strike">לא' in yes_no_html(TriState.YES)
    assert 'class="strike">כן' in yes_no_html(TriState.NO)
    assert "strike" not in yes_no_html(TriState.UNKNOWN)


def test_description_multiline_becomes_br(complainant):
    case = sample_case()
    mapping = build_mapping(case, complainant)
    assert mapping["DESCRIPTION_BLOCK"]  # non-empty
    case2 = case.__class__(
        **{**case.__dict__, "offence": case.offence.__class__(**{**case.offence.__dict__, "description": "א\nב"})}
    )
    mapping2 = build_mapping(case2, complainant)
    assert "א<br>" in mapping2["DESCRIPTION_BLOCK"]


def test_test_mode_adds_watermark(complainant):
    assert "בדיקה - לא לשליחה" in render_form(sample_case(), complainant, test_mode=True)
    assert "בדיקה - לא לשליחה" not in render_form(sample_case(), complainant, test_mode=False)


def test_witness_defaults_to_complainant(complainant):
    case = sample_case()
    assert case.witness.is_empty
    html_text = render_form(case, complainant)
    full_name = f"{complainant.first_name} {complainant.last_name}"
    witness_line = next(line for line in html_text.splitlines() if "עדים" in line)
    assert full_name in witness_line
    assert complainant.id_number in witness_line
    assert complainant.phone in witness_line
    assert complainant.address in witness_line


def test_explicit_witness_wins(complainant):
    from traffic_complaint_form.models import Witness

    case = sample_case()
    explicit = Witness(name="עד ראייה", id_number="000000018", phone="0521111111", address="רחוב העד 1")
    case2 = case.__class__(**{**case.__dict__, "witness": explicit})
    witness_line = next(line for line in render_form(case2, complainant).splitlines() if "עדים" in line)
    assert "עד ראייה" in witness_line
    assert "000000018" in witness_line
    assert complainant.id_number not in witness_line


def test_multi_incident_renders_table(complainant):
    case = sample_multi_case()
    html_text = render_form(case, complainant)
    assert 'class="incidents"' in html_text
    assert html_text.count("<tr>") == len(case.incidents) + 1  # body rows + header row
    assert "2610-0000002" in html_text  # synthetic municipal case ref
    assert "3 עבירות" in html_text
    assert "$" not in html_text


def test_multi_incident_values_are_escaped(complainant):
    case = sample_multi_case()
    evil = CaseData.from_dict(
        {
            "vehicle_number": "12-345-67",
            "vehicle_manufacturer": "<b>x</b>",
            "vehicle_color": "לבן",
            "incidents": [
                {
                    "offence_date": "2026-01-10",
                    "offence_time": "08:00",
                    "offence_street": "<script>alert(1)</script>",
                    "offence_city": "ירושלים",
                    "offence_description": "א",
                },
                {
                    "offence_date": "2026-01-12",
                    "offence_time": "19:30",
                    "offence_street": "ב",
                    "offence_city": "ירושלים",
                    "offence_description": "ב",
                },
            ],
        }
    )
    html_text = render_form(evil, complainant)
    assert "<script>" not in html_text
    assert "&lt;script&gt;" in html_text
    assert case.incidents  # silence unused-variable style complaints
