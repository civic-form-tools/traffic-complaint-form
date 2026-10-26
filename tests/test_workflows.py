"""Guard the GitHub workflow files against schema errors GitHub rejects.

A rejected workflow file surfaces only as a 0-second failed run with no
jobs, long after merge. These checks run inside the normal pytest suite so
the mistake fails CI before merge instead.

Covers the two failures this repo already hit:
- unquoted yes/no in choice options parsed as YAML booleans (issue #1)
- more than 25 workflow_dispatch inputs (issue #6)
"""

from pathlib import Path

import yaml

WORKFLOWS = sorted(Path(".github/workflows").glob("*.yml"))
MAX_DISPATCH_INPUTS = 25


def load(path):
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    # YAML 1.1 parses the bare key `on:` as boolean True
    return data.get("on", data.get(True)) or {}


def test_workflow_files_parse_and_have_triggers():
    assert WORKFLOWS, "no workflow files found"
    for path in WORKFLOWS:
        assert load(path), f"{path.name}: missing trigger section"


def test_dispatch_inputs_within_github_limit():
    for path in WORKFLOWS:
        inputs = (load(path).get("workflow_dispatch") or {}).get("inputs") or {}
        assert len(inputs) <= MAX_DISPATCH_INPUTS, (
            f"{path.name}: {len(inputs)} inputs, GitHub allows {MAX_DISPATCH_INPUTS}"
        )


def test_choice_options_and_defaults_are_strings():
    for path in WORKFLOWS:
        inputs = (load(path).get("workflow_dispatch") or {}).get("inputs") or {}
        for name, spec in inputs.items():
            if not isinstance(spec, dict):
                continue
            if spec.get("type") == "choice":
                for option in spec.get("options", []):
                    assert isinstance(option, str), f"{path.name}:{name} non-string option {option!r}"
            default = spec.get("default")
            if default is not None and spec.get("type") != "boolean":
                assert isinstance(default, str), f"{path.name}:{name} non-string default {default!r}"


def test_filing_boundary_and_secret_scope():
    workflow = yaml.safe_load(Path(".github/workflows/fill-form.yml").read_text())
    job = workflow["jobs"]["fill"]
    assert job["environment"] == "production"
    assert job["if"] == "github.ref == 'refs/heads/main'"
    assert "env" not in job  # credentials must not reach checkout, pip or package setup
    steps = job["steps"]
    secret_steps = [s for s in steps if "secrets." in str(s)]
    assert len(secret_steps) == 1
    assert secret_steps[0]["name"] == "Fill, verify and send"
    assert secret_steps[0]["env"]["FILING_BUNDLE"] == "${{ secrets.FILING_BUNDLE }}"
    text = Path(".github/workflows/fill-form.yml").read_text()
    for name in ["COMPLAINANT_ID", "PDF_PASSWORD", "SMTP_APP_PASSWORD", "RECIPIENT_EMAIL"]:
        assert "secrets." + name not in text
    assert "'${{ inputs.encrypted_case }}'" not in text


def test_sample_verification_always_watermarked():
    workflow = yaml.safe_load(Path(".github/workflows/fill-form.yml").read_text())
    step = next(s for s in workflow["jobs"]["fill"]["steps"] if s.get("name") == "Fill, verify and send")
    assert step["env"]["TEST_MODE"] == "${{ inputs.encrypted_case == '' && 'true' || vars.TEST_MODE }}"
