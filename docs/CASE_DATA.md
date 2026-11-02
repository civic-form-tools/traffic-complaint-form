# Case data payload (`encrypted_case`)

This is the exact contract for the JSON payload a caller seals into the
`encrypted_case` workflow input. It exists so a caller (for example a
parking-monitor agent) can encrypt case data with the repository public key
and never send plaintext through this public repository.

**Channel rules**

- Plaintext case data (plates, locations, incident details) must never
  appear in workflow inputs, logs, issues, PRs or this file's examples.
- The payload is encrypted with a libsodium **sealed box**
  (ephemeral X25519 + XSalsa20-Poly1305) against
  [`form/keys/case-data-public.key`](../form/keys/case-data-public.key).
  Only the workflow, holding the private key from Secrets, can open it.
- Every encryption produces a different ciphertext; that is expected.
- The ciphertext is a single line of base64. Paste it whole into the
  `encrypted_case` dispatch input.
- Nothing is submitted to any police station or other third party. The
  filled PDF is emailed only to the configured recipient (the complainant)
  for review.

## JSON schema

One JSON object per complaint. Keys not listed here are ignored.

### Required keys

| Key | Format | Notes |
| --- | --- | --- |
| `vehicle_number` | string | Plate, e.g. `"12-345-67"`. |
| `vehicle_manufacturer` | string | Hebrew, e.g. `"טויוטה"`. |
| `vehicle_color` | string | Hebrew, e.g. `"לבן"`. |
| `offence_date` | `YYYY-MM-DD` | Date of the incident. |
| `offence_time` | `HH:MM` | 24-hour clock. |
| `offence_street` | string | Street name. |
| `offence_city` | string | City. |
| `offence_description` | string | Free text (Hebrew). Must stay short enough for the form to fit on **one page** - the run fails verification otherwise. |

### Optional keys

| Key | Default | Notes |
| --- | --- | --- |
| `police_station` | `"ירושלים"` | Station line printed on the form. Nothing is filed there; blank/missing falls back to the default. |
| `complaint_date` | run date (Asia/Jerusalem) | `YYYY-MM-DD`. |
| `vehicle_type` | `""` | e.g. `"פרטי"`. |
| `offence_day` | derived from `offence_date` | Hebrew weekday; only set to override. |
| `offence_junction_or_house` | `""` | Junction or house number. |
| `can_identify_driver` | `unknown` | `yes` / `no` / `unknown` (also accepts `כן`/`לא`, `true`/`false`, `1`/`0`, `לא ידוע`). |
| `knows_driver` | `unknown` | Same value set. |
| `willing_to_testify` | `yes` | `yes` / `no`. |
| `driver_name`, `driver_address`, `driver_identifying_marks` | `""` | Free text. |
| `witness_name`, `witness_id`, `witness_phone`, `witness_address` | complainant | When all four are blank, the witness section is filled with the complainant's own details (from Secrets). An explicit witness always wins. |
| `incidents` | - | Optional non-empty list of incident objects (schema below). When present with 2+ entries, the form becomes a **merged complaint**: one PDF for the vehicle with an incidents table (continuation page allowed). A single-entry list renders exactly like the classic form. |
| `municipal_case` | `""` | Only inside an incident object: municipal report reference (אסמכתא), printed in the table's ref column. |

### Per-call identity override (payload v2, optional)

Three keys let a caller (for example the MCP server) supply the complainant's
own details for this run only. They are **all-or-nothing**: include all three
or none; a partial override fails closed with the code `partial_override`.
When present they override the `FILING_BUNDLE` identity, recipient and PDF
password **in memory, for that run only** - they are never written to any
secret, file, log or output. When absent, the bundle defaults apply (v1
behaviour, unchanged).

| Key | Format | Notes |
| --- | --- | --- |
| `complainant` | object | Exactly `first_name`, `last_name`, `id_number`, `address`, `phone` - same rules as the bundle (9-digit ID with Israeli checksum, no line breaks). |
| `recipient_email` | string | Where the encrypted PDF is emailed for this run. |
| `pdf_password` | string | This filing's PDF password: 16+ characters, at most 127 UTF-8 bytes, not equal to the ID number. Chosen by the person filing; never stored. |

```json
{
  "vehicle_number": "12-345-67",
  "...": "case keys as above (all values invented)",
  "complainant": {
    "first_name": "דנה",
    "last_name": "כהן",
    "id_number": "000000018",
    "address": "רחוב הדוגמה 2, ירושלים",
    "phone": "050-1111111"
  },
  "recipient_email": "caller@example.com",
  "pdf_password": "invented-per-call-password"
}
```

Validation diagnostics use allowlisted codes only (`partial_override`,
`complainant.id_number`, `recipient_email`, `pdf_password`, ...) and never
echo supplied values.

### Incident object (inside `incidents`)

| Key | Required | Format |
| --- | --- | --- |
| `offence_date` | yes | `YYYY-MM-DD` |
| `offence_time` | yes | `HH:MM` |
| `offence_street` | yes | string |
| `offence_city` | yes | string |
| `offence_description` | yes | short free text (one row of the table) |
| `offence_junction_or_house` | no | string |
| `offence_day` | no | Hebrew weekday; derived from the date when blank |
| `municipal_case` | no | municipal (106) report reference; the table labels it "דיווח לעירייה", never a police ticket number |

With `incidents`, the top-level `offence_*` keys are not required. Keep
descriptions short: the merged form allows at most 3 pages.

## Example (all values invented)

```json
{
  "police_station": "מוריה",
  "vehicle_number": "12-345-67",
  "vehicle_manufacturer": "טויוטה",
  "vehicle_color": "לבן",
  "vehicle_type": "פרטי",
  "offence_date": "2026-01-15",
  "offence_time": "14:30",
  "offence_street": "רחוב הדוגמה",
  "offence_junction_or_house": "מס' 7",
  "offence_city": "ירושלים",
  "offence_description": "הרכב חנה על המדרכה וחסם לחלוטין את המעבר להולכי רגל.",
  "can_identify_driver": "unknown",
  "knows_driver": "unknown",
  "willing_to_testify": "yes"
}
```

## Encrypt and dispatch

```bash
# once, in a checkout of this repository:
pip install -e .

# per complaint (case.json = the payload above):
traffic-complaint-form-encrypt-case --in case.json --out case.enc
```

Then run **Actions -> Fill and send complaint form** with
`encrypted_case` = the single-line contents of `case.enc`, and approve the
`filing` environment gate. Delete `case.json` and `case.enc` afterwards -
the ciphertext is safe to paste, the plaintext file is not safe to keep.
