# Changelog

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
