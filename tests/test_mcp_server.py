"""MCP server tools: validation codes, sealed roundtrip, dispatch mapping.

All values are invented fixtures (see docs/SECRETS.md). The GitHub API and
network are always mocked; no real dispatch happens in tests.
"""

import json

import pytest

from traffic_complaint_form import mcp_server
from traffic_complaint_form.crypto import decrypt_payload, generate_keypair

CASE = {
    "vehicle_number": "98-765-43",
    "vehicle_manufacturer": "טויוטה",
    "vehicle_color": "לבן",
    "offence_date": "2026-01-15",
    "offence_time": "14:30",
    "offence_street": "רחוב הדוגמה",
    "offence_city": "ירושלים",
    "offence_description": "הרכב חנה על המדרכה.",
}

OVERRIDE_ARGS = {
    "complainant": {
        "first_name": "דנה",
        "last_name": "לוי",
        "id_number": "000000018",
        "address": "רחוב המבחן 2",
        "phone": "050-1111111",
    },
    "recipient_email": "caller@example.com",
    "pdf_password": "invented-per-call-password",
}


@pytest.fixture(autouse=True)
def _public_key(monkeypatch):
    public_b64, _ = generate_keypair()
    monkeypatch.setenv(mcp_server.PUBLIC_KEY_ENV, public_b64)
    monkeypatch.delenv(mcp_server.TOKEN_ENV, raising=False)


class FakeGitHub:
    """Records calls; serves canned dispatch/list/status responses."""

    def __init__(self, *, post_status=204, runs=None, run=None):
        self.calls = []
        self.post_status = post_status
        self.runs = runs or []
        self.run = run or {}

    def __call__(self, method, path, *, token, json_body=None, params=None):
        self.calls.append({"method": method, "path": path, "json": json_body, "params": params, "token": token})
        if method == "POST":
            return self.post_status, ({} if self.post_status == 204 else {"message": "Forbidden"})
        if "/actions/runs/" in path:
            return 200, self.run
        return 200, {"workflow_runs": self.runs}


# --- validate_filing ---


def test_validate_ok_with_and_without_override():
    assert mcp_server.validate_filing(CASE, **OVERRIDE_ARGS) == {"ok": True, "codes": []}
    assert mcp_server.validate_filing(CASE) == {"ok": True, "codes": []}


def test_validate_partial_override_is_all_or_nothing():
    result = mcp_server.validate_filing(CASE, recipient_email="caller@example.com")
    assert result == {"ok": False, "codes": ["partial_override"]}
    result = mcp_server.validate_filing(CASE, complainant=OVERRIDE_ARGS["complainant"])
    assert result["ok"] is False and result["codes"] == ["partial_override"]


def test_validate_bad_case_and_non_dict():
    assert mcp_server.validate_filing({"vehicle_number": "x"})["ok"] is False
    assert mcp_server.validate_filing(["not", "a", "dict"])["ok"] is False
    bad_id = dict(OVERRIDE_ARGS)
    bad_id["complainant"] = dict(OVERRIDE_ARGS["complainant"], id_number="123456789")
    result = mcp_server.validate_filing(CASE, **bad_id)
    assert result == {"ok": False, "codes": ["complainant.id_number"]}


# --- seal_filing ---


def test_seal_roundtrip_and_randomized_ciphertext(monkeypatch):
    public_b64, private_b64 = generate_keypair()
    monkeypatch.setenv(mcp_server.PUBLIC_KEY_ENV, public_b64)
    result = mcp_server.seal_filing(CASE, **OVERRIDE_ARGS)
    assert result["ok"] is True and result["input_name"] == "encrypted_case"
    payload = json.loads(decrypt_payload(private_b64, result["ciphertext"]).decode("utf-8"))
    assert payload["complainant"]["id_number"] == "000000018"
    assert payload["recipient_email"] == "caller@example.com"
    assert payload["vehicle_number"] == "98-765-43"
    again = mcp_server.seal_filing(CASE, **OVERRIDE_ARGS)
    assert again["ciphertext"] != result["ciphertext"]  # sealed boxes are randomized


def test_seal_refuses_invalid_payload():
    result = mcp_server.seal_filing(CASE, pdf_password="short")
    assert result["ok"] is False and result["codes"]


# --- dispatch_filing / filing_status ---


def test_dispatch_requires_token():
    result = mcp_server.dispatch_filing(CASE, **OVERRIDE_ARGS)
    assert result["ok"] is False and result["error"] == "missing_token"


def test_dispatch_happy_path(monkeypatch):
    monkeypatch.setenv(mcp_server.TOKEN_ENV, "invented-token")
    fake = FakeGitHub(runs=[{"id": 42, "html_url": "https://example.com/run/42", "status": "queued"}])
    monkeypatch.setattr(mcp_server, "_github_request", fake)
    result = mcp_server.dispatch_filing(CASE, **OVERRIDE_ARGS, wait_seconds=0)
    assert result["ok"] is True and result["run_id"] == 42
    assert result["run_url"] == "https://example.com/run/42"
    assert "gate" in result
    post = fake.calls[0]
    assert post["method"] == "POST"
    assert post["path"].endswith("/actions/workflows/fill-form.yml/dispatches")
    assert post["json"]["ref"] == "main"
    assert set(post["json"]["inputs"]) == {"encrypted_case"}
    # Only ciphertext crosses to GitHub - never per-call values
    blob = json.dumps(post["json"])
    for value in ("invented-per-call-password", "caller@example.com", "000000018"):
        assert value not in blob


def test_dispatch_github_error(monkeypatch):
    monkeypatch.setenv(mcp_server.TOKEN_ENV, "invented-token")
    fake = FakeGitHub(post_status=403)
    monkeypatch.setattr(mcp_server, "_github_request", fake)
    result = mcp_server.dispatch_filing(CASE, **OVERRIDE_ARGS, wait_seconds=0)
    assert result["ok"] is False and result["error"] == "github_http_403"


def test_dispatch_run_not_yet_visible(monkeypatch):
    monkeypatch.setenv(mcp_server.TOKEN_ENV, "invented-token")
    fake = FakeGitHub(runs=[])
    monkeypatch.setattr(mcp_server, "_github_request", fake)
    result = mcp_server.dispatch_filing(CASE, **OVERRIDE_ARGS, wait_seconds=0)
    assert result["ok"] is True and result["run_id"] is None and result["status"] == "unknown"


def test_filing_status(monkeypatch):
    monkeypatch.setenv(mcp_server.TOKEN_ENV, "invented-token")
    fake = FakeGitHub(run={"status": "completed", "conclusion": "success", "html_url": "https://example.com/run/7"})
    monkeypatch.setattr(mcp_server, "_github_request", fake)
    result = mcp_server.filing_status(7)
    assert result == {
        "ok": True,
        "run_id": 7,
        "status": "completed",
        "conclusion": "success",
        "run_url": "https://example.com/run/7",
    }
    assert mcp_server.filing_status.__doc__


def test_filing_status_requires_token():
    assert mcp_server.filing_status(7)["error"] == "missing_token"


# --- server construction ---


def test_build_server_registers_all_tools():
    server = mcp_server.build_server()
    assert server.name == "traffic-complaint-form"
    assert "never" in server.instructions and "stored" in server.instructions
