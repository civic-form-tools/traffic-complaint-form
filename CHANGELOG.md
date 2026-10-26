# Changelog

## 0.2.0 - 2026-10-26

- MCP server (`traffic-complaint-form-mcp`, optional `mcp` extra):
  `validate_filing` / `seal_filing` / `dispatch_filing` / `filing_status`
  tools. A caller supplies the complainant identity, delivery email and PDF
  password per call; they stay in process memory, travel only inside the
  sealed-box payload and are never persisted, logged or committed.
- Payload schema v2: optional all-or-nothing per-call override
  (`complainant` + `recipient_email` + `pdf_password`) applied in memory for
  one run; FILING_BUNDLE unchanged (SMTP sender and classic defaults).
  Validation diagnostics use allowlisted codes, never values.
- fill-form workflow enforces a daily dispatch cap (default 10,
  `vars.MCP_DAILY_CAP`), counted over the UTC day, fail closed.
- Email body gains a per-call variant (the recipient's own chosen password,
  plus an abuse-report pointer); subject/body remain fixed templates with no
  caller free text.
- CODEOWNERS now covers `mcp_server.py`; design and threat model in
  docs/MCP.md.
- Review hardening: `vehicle_number` must be plate-shaped (digits and
  hyphens) - it interpolates into the delivery email subject, and in
  per-call mode free text there would be a phishing channel; tri-state
  validation messages no longer echo the supplied value; dispatch runs are
  correlated by a random `dispatch_nonce` in the run name, so a concurrent
  dispatch cannot be misreported as ours; `_email` parse failures can no
  longer leak values (see below).

- `CASE_DATA_PRIVATE_KEY` moved out of repository secrets into the protected
  `production` environment; the keypair was rotated in the process (GitHub
  secrets are unreadable, and no outside copy existed). Payloads sealed with
  the retired public key must be re-encrypted with the new committed key.
- Branch protection on main now requires one approving review with required
  code-owner review, stale-review dismissal and last-push approval;
  CODEOWNERS assigns the workflow files, CODEOWNERS itself and the
  secret-reading modules (cli.py, config.py, crypto.py, mail.py) to @reihl.
- Workflow regression guards: every action pinned to a full commit SHA, the
  gated job runs only first-party actions, and `CASE_DATA_PRIVATE_KEY` may be
  referenced only inside the gated job's single secret-exposed step.

## 0.1.0 - 2026-10-26

Initial release.

- Fill the Jerusalem District traffic complaint form (RTL Hebrew, one page,
  header band and footer logo from the blank original form) to PDF with
  WeasyPrint.
- Complainant identity, PDF password, recipient email and SMTP credentials
  loaded from GitHub Secrets only; values never printed (missing config is
  reported by variable name).
- Real case data arrives as a libsodium sealed-box payload
  (`encrypted_case`); the public key is committed, the private key is a
  secret, and logs/filenames carry no case values (test-covered).
- Output AES-256 password-protected (pikepdf), verified before delivery;
  `ENCRYPT_OUTPUT=false` allowed only in `TEST_MODE` (dummy phase).
- Delivery over Gmail SMTP (STARTTLS, app password); every run gated by the
  `filing` environment's required reviewer.
- `police_station` is optional and defaults to `ירושלים` (nothing is
  submitted anywhere - the PDF is only emailed to the complainant).
- Merged complaints: an optional `incidents[]` payload list renders one PDF
  per vehicle with an incidents table (date/day/time/location/description/
  municipal case ref) and a continuation page when needed; page-count
  verification relaxes to 1-3 pages only in multi-incident mode.
- Validation errors no longer echo rejected date/time values (log privacy).
- Caller-side `traffic-complaint-form-encrypt-case` console script wired in
  `pyproject.toml`; full payload schema documented in `docs/CASE_DATA.md`.
- CI: ruff + pytest (Python 3.10-3.13) with an 80% coverage floor and a
  per-test report, pip-audit, CodeQL, dependency review; Dependabot for pip
  and actions; all actions pinned to SHAs.

## Unreleased - atomic filing bundle

- Replace split identity/password/delivery configuration with mandatory, strict
  FILING_BUNDLE JSON; no partial or legacy fallback.
- Require PDF encryption in all modes and suppress sensitive exception details.
- Scope credentials to the application step; reject non-main filing dispatches.
- Document migration, old-secret removal and remaining admin/code-author risks.
