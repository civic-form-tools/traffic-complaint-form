import re

from traffic_complaint_form.fill import build_mapping, render_form, yes_no_html
from traffic_complaint_form.models import TriState
from traffic_complaint_form.sample import sample_case


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
    assert mapping["OFFENCE_DESCRIPTION"]  # non-empty
    case2 = case.__class__(
        **{**case.__dict__, "offence": case.offence.__class__(**{**case.offence.__dict__, "description": "א\nב"})}
    )
    mapping2 = build_mapping(case2, complainant)
    assert "א<br>" in mapping2["OFFENCE_DESCRIPTION"]


def test_test_mode_adds_watermark(complainant):
    assert "בדיקה - לא לשליחה" in render_form(sample_case(), complainant, test_mode=True)
    assert "בדיקה - לא לשליחה" not in render_form(sample_case(), complainant, test_mode=False)
