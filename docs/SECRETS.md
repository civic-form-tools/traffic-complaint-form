# Secrets specification

All values are loaded by the user into GitHub Secrets (Settings -> Secrets
and variables -> Actions -> the `filing` environment). Values are write-only
afterwards: nobody, including the automation, can read them back through the
API. The examples below are **invented** - never load or commit real values
into this repository.

| Secret | Invented example | Notes |
| --- | --- | --- |
| `COMPLAINANT_FIRST_NAME` | `משה` | Form field שם |
| `COMPLAINANT_LAST_NAME` | `כהן` | Form field משפחה |
| `COMPLAINANT_ID` | `123456782` | 9-digit ID; the pipeline logs a warning (never the value) if the checksum fails |
| `COMPLAINANT_ADDRESS` | `רחוב הדוגמה 1, ירושלים` | Form field כתובת |
| `COMPLAINANT_PHONE` | `050-0000000` | Form field טלפון |
| `PDF_PASSWORD` | `correct-horse-battery-staple` | Opens the encrypted PDF. **Primary for real data** - choose a hard-to-guess value. If unset, TEST_MODE falls back to `COMPLAINANT_ID` (see below) |
| `RECIPIENT_EMAIL` | `someone@example.com` | Where the filled form is emailed |
| `SMTP_USERNAME` | `assistant@example.com` | Gmail address of the sender account |
| `SMTP_APP_PASSWORD` | `abcd efgh ijkl mnop` | Google app password for the sender account (needs 2FA on that account) |
| `CASE_DATA_PRIVATE_KEY` | `kD8...base64...` | Sealed-box private key for encrypted case payloads. The matching public key is committed at `form/keys/case-data-public.key`. Not personal data. |

Repository/environment **variables** (non-secret):

| Variable | Default | Meaning |
| --- | --- | --- |
| `TEST_MODE` | `true` | Watermark + `[בדיקה]` subject. Set `false` only after real values are loaded. |
| `ENCRYPT_OUTPUT` | `true` | `false` allowed only during the dummy phase (`TEST_MODE=true`). |

## PDF password policy (user decision, 2026-10-26)

Encryption is the PDF's built-in AES-256 password (pikepdf). Resolution:

1. `PDF_PASSWORD` set -> used. This is the documented primary for real
   data; the user loads a hard-to-guess value himself.
2. Unset and `TEST_MODE=true` -> the complainant ID number opens the file.
   Accepted tradeoff: a 9-digit ID is low-entropy and offline-brute-forceable
   against a captured file, so this fallback exists for test data only.
3. Unset and `TEST_MODE=false` -> the run fails before any work, reporting
   the secret by NAME only. Real data never ships under the ID fallback.

The password value never appears in logs, the PDF filename or the email.

## Loading via the UI

Settings -> Secrets and variables -> Actions -> Environment secrets
(`filing` environment) -> New secret, one per row above. Variables go under
the Variables tab.

## Swapping dummy -> real

Replace each value in place; no code change is needed. After real values are
in: set `TEST_MODE=false` and `ENCRYPT_OUTPUT=true` (the CLI refuses
`ENCRYPT_OUTPUT=false` outside test mode).
