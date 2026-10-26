"""Render the filled HTML form to PDF and report its page count."""

from __future__ import annotations

from pathlib import Path

import pikepdf
import weasyprint


def html_to_pdf(html_text: str, *, base_url: str, out_path: Path) -> int:
    """Write the PDF to out_path and return the number of pages."""
    weasyprint.HTML(string=html_text, base_url=base_url).write_pdf(str(out_path))
    with pikepdf.open(str(out_path)) as pdf:
        return len(pdf.pages)
