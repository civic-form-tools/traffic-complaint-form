# Offline security-contract matrix (#38)

This maps each invariant to an executable test on `main`, a strict `xfail`
(a known gap on `main`), or an explicit skip pending #34 or #35. Skipped rows
are **not executed** and don't count as coverage. A strict `xfail` turns into
a failure as soon as `main` changes, so its row has to be promoted then.

Tests live in `tests/test_security_matrix.py`. The fixtures in
`tests/fixtures_synthetic.py` are fully invented:
- names marked with `ZZ`
- `.invalid` addresses and hosts
- the checksum-valid placeholder ID from `conftest.py`
- an all-zero plate

An autouse guard blocks sockets, real `smtplib`, secret-named files and the
filing environment variables, and its self-tests plant each violation. So
every row runs offline.

| Invariant | Interface on main | Status | Test(s) |
|---|---|---|---|
| Offline: no socket, SMTP, secret file or env | guard | executable | `test_guard_*` |
| Fixture builders are fresh and invented | `fixtures_synthetic` | executable | `test_builders_*` |
| Missing or partial bundle sections fail with the section code | `FilingConfig.from_env` | executable | `test_partial_sections_rejected_with_section_code` (+ `test_config.py`) |
| Wrong-typed fields fail with the field code | `FilingConfig.from_env` | executable | `test_wrong_types_rejected_with_field_code` |
| Extra keys rejected | `FilingConfig.from_env` | executable | `test_extra_key_rejected` |
| Oversized bundle (>48 KiB) rejected before parsing | `FilingConfig.from_env` | executable | `test_oversized_bundle_rejected_before_parsing` |
| Per-field length caps for case/override fields | none on main | pending #34 | `test_oversized_case_fields_rejected` (skip) |
| Header injection (CR/LF/NUL, multi-address, display name, space) rejected in recipient/from/username | `_email` / `_text` | executable | `test_header_injection_rejected` |
| Malformed address stays inside `BundleError` | `_email` | **gap: strict xfail** | `test_malformed_address_stays_inside_bundle_error` |
| Bundle diagnostics never echo values | `BundleError` | executable | `test_bundle_diagnostics_never_echo_values`, `test_unknown_code_collapses_to_schema` |
| Config repr withholds secrets | `FilingConfig` | executable | `test_config_repr_withholds_secrets` |
| Case diagnostics name keys, not values | `CaseData.from_dict` | executable | `test_case_diagnostics_name_keys_not_values`, `test_case_incident_shapes_rejected_without_values` |
| Shape-valid impossible date is value-free | `parse_iso_date` | **gap: strict xfail** | `test_impossible_date_diagnostic_is_value_free` |
| Tri-state accepts only known tokens | `TriState.parse` | executable | `test_tristate_accepts_only_known_tokens`, `test_tristate_rejects_unknown_tokens` |
| Tri-state diagnostic is value-free | `TriState.parse` | **gap: strict xfail** (fixed in #34) | `test_tristate_diagnostic_is_value_free` |
| Fixed subject/body templates; no values in logs | `mail.send_encrypted_pdf` (SMTP mocked) | executable | `test_mail_uses_fixed_templates_and_logs_no_values` |
| Two parses and two sends share no state | `from_env` + `send_encrypted_pdf` | executable | `test_two_parses_and_sends_share_no_state` |
| Wrong-key decryption error is value-free | `crypto.decrypt_payload` | executable | `test_wrong_key_decryption_error_is_value_free` |
| `FilingOverride` all-or-nothing | none on main | pending #34 | skip |
| `PayloadError` / `validate_filing` value-free codes | none on main | pending #34 | skip |
| Plate-shaped `vehicle_number` | none on main | pending #34 | skip |
| Per-call body variant and nonce correlation | none on main | pending #34 | skip |
| HTTP bearer and toolset invariants | none on main | pending #35 | skip |

## Gaps found on main (protected files; reported, not fixed here)

1. **`config._email`** lets `email.errors.HeaderParseError` escape for
   addresses such as `zz@@example.invalid`, `@example.invalid` and `zz@`.
   That exception isn't a `ValueError`, so `from_env`'s handlers miss it,
   and `cli.main` catches only `BundleError`. The traceback message echoes
   part of the address (for example, `found '@example.invalid'`). The fix
   belongs in `config.py`, which is protected.
2. **`parse_iso_date`:** a shape-valid but impossible date such as
   `2026-13-01` reaches `strptime`, and its message echoes the value. The CLI
   withholds case-data messages today. #34's `validate_filing` must not
   surface them.
3. **`TriState.parse`** echoes its input. #34 fixes this.
