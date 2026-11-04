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


GATED = {
    ".github/workflows/fill-form.yml": ("fill", "Fill, verify and send", "encrypted_case"),
    ".github/workflows/fill-batch.yml": ("fill-batch", "Fill, archive, verify and send", "encrypted_batch"),
}


def test_filing_boundary_and_secret_scope():
    for path, (job_name, step_name, input_name) in GATED.items():
        _check_gated_workflow(path, job_name, step_name, input_name)


def _check_gated_workflow(path, job_name, step_name, input_name):
    workflow = yaml.safe_load(Path(path).read_text())
    job = workflow["jobs"][job_name]
    assert job["environment"] == "production"
    assert job["if"] == "github.ref == 'refs/heads/main'"
    assert "env" not in job  # credentials must not reach checkout, pip or package setup
    steps = job["steps"]
    secret_steps = [s for s in steps if "secrets." in str(s)]
    assert len(secret_steps) == 1
    assert secret_steps[0]["name"] == step_name
    assert secret_steps[0]["env"]["FILING_BUNDLE"] == "${{ secrets.FILING_BUNDLE }}"
    text = Path(path).read_text()
    for name in ["COMPLAINANT_ID", "PDF_PASSWORD", "SMTP_APP_PASSWORD", "RECIPIENT_EMAIL", "ARCHIVE_PASSWORD"]:
        assert "secrets." + name not in text
    assert "'${{ inputs." + input_name + " }}'" not in text


def test_sample_verification_always_watermarked():
    for path, (job_name, step_name, input_name) in GATED.items():
        workflow = yaml.safe_load(Path(path).read_text())
        step = next(s for s in workflow["jobs"][job_name]["steps"] if s.get("name") == step_name)
        assert step["env"]["TEST_MODE"] == ("${{ inputs." + input_name + " == '' && 'true' || vars.TEST_MODE }}")


FIRST_PARTY_ACTION_PREFIXES = ("actions/", "github/")
SHA_PIN_LENGTH = 40


def _all_step_uses(workflow):
    for job in workflow["jobs"].values():
        for step in job.get("steps", []):
            if "uses" in step:
                yield step["uses"]


def test_every_action_is_pinned_to_a_full_commit_sha():
    """Tags/branches are mutable; only a full SHA pins the reviewed code."""
    for path in WORKFLOWS:
        workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
        for uses in _all_step_uses(workflow):
            ref = uses.rsplit("@", 1)[-1]
            assert len(ref) == SHA_PIN_LENGTH and all(c in "0123456789abcdef" for c in ref), (
                f"{path.name}: action {uses!r} is not pinned to a full commit SHA"
            )


def test_gated_job_runs_only_first_party_actions():
    """The job exposed to FILING_BUNDLE/CASE_DATA_PRIVATE_KEY must not run
    third-party action code (checkout/setup-python are GitHub-owned)."""
    for path, (job_name, _step, _input) in GATED.items():
        workflow = yaml.safe_load(Path(path).read_text())
        for step in workflow["jobs"][job_name]["steps"]:
            uses = step.get("uses")
            if uses:
                assert uses.startswith(FIRST_PARTY_ACTION_PREFIXES), f"gated job uses third-party action {uses!r}"


def test_case_key_referenced_only_inside_the_gated_job():
    """CASE_DATA_PRIVATE_KEY must exist only as a production environment
    secret and be referenced only by the single gated step of each gated
    workflow (single fill and batch fill)."""
    for path in WORKFLOWS:
        text = path.read_text(encoding="utf-8")
        if "CASE_DATA_PRIVATE_KEY" not in text:
            continue
        assert path.name in ("fill-form.yml", "fill-batch.yml"), f"{path.name} references CASE_DATA_PRIVATE_KEY"
    for path, (job_name, step_name, _input) in GATED.items():
        workflow = yaml.safe_load(Path(path).read_text())
        for name, job in workflow["jobs"].items():
            if name == job_name:
                continue
            assert "CASE_DATA_PRIVATE_KEY" not in str(job), f"job {name} references CASE_DATA_PRIVATE_KEY"
        step = next(s for s in workflow["jobs"][job_name]["steps"] if s.get("name") == step_name)
        assert step["env"]["CASE_DATA_PRIVATE_KEY"] == "${{ secrets.CASE_DATA_PRIVATE_KEY }}"
        others = [s for s in workflow["jobs"][job_name]["steps"] if s is not step]
        for s in others:
            assert "CASE_DATA_PRIVATE_KEY" not in str(s)
