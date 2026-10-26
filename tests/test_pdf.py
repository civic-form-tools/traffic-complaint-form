from traffic_complaint_form.fill import render_form, template_base_url
from traffic_complaint_form.pdf import html_to_pdf
from traffic_complaint_form.sample import sample_case


def test_form_renders_exactly_one_page(tmp_path, complainant):
    out = tmp_path / "form.pdf"
    pages = html_to_pdf(render_form(sample_case(), complainant), base_url=template_base_url(), out_path=out)
    assert pages == 1
    assert out.stat().st_size > 10_000


def test_text_is_extractable_and_contains_case_data(tmp_path, complainant):
    from pypdf import PdfReader

    out = tmp_path / "form.pdf"
    html_to_pdf(render_form(sample_case(), complainant), base_url=template_base_url(), out_path=out)
    text = PdfReader(str(out)).pages[0].extract_text()
    assert "12-345-67" in text  # sample plate
    assert "תלונה על עבירת תנועה" in text


def test_long_description_overflows_to_second_page(tmp_path, complainant):
    case = sample_case()
    long = case.__class__(
        **{
            **case.__dict__,
            "offence": case.offence.__class__(**{**case.offence.__dict__, "description": "שורה ארוכה מאוד. " * 400}),
        }
    )
    out = tmp_path / "form.pdf"
    pages = html_to_pdf(render_form(long, complainant), base_url=template_base_url(), out_path=out)
    assert pages > 1
