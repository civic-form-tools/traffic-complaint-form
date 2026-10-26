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
| `PDF_PASSWORD` | `correct-horse-battery-staple` | Opens the encrypted PDF; required unless `ENCRYPT_OUTPUT=false` |
| `RECIPIENT_EMAIL` | `someone@example.com` | Where the filled form is emailed |
| `SMTP_USERNAME` | `assistant@example.com` | Gmail address of the sender account |
| `SMTP_APP_PASSWORD` | `abcd efgh ijkl mnop` | Google app password for the sender account (needs 2FA on that account) |
| `CASE_DATA_PRIVATE_KEY` | `kD8...base64...` | Sealed-box private key for encrypted case payloads. The matching public key is committed at `form/keys/case-data-public.key`. Not personal data. |
| `SMIME_PUBLIC_CERT` | `-----BEGIN CERTIFICATE----- ...` | Phase 2 (optional): the recipient's PUBLIC S/MIME certificate in PEM. When loaded, every email is S/MIME-encrypted to it (AES-256) - only the holder of the matching private key can open the mail. See below. |

Repository/environment **variables** (non-secret):

| Variable | Default | Meaning |
| --- | --- | --- |
| `TEST_MODE` | `true` | Watermark + `[בדיקה]` subject. Set `false` only after real values are loaded. |
| `ENCRYPT_OUTPUT` | `true` | `false` allowed only during the dummy phase (`TEST_MODE=true`). |

## Loading via the UI

Settings -> Secrets and variables -> Actions -> Environment secrets
(`filing` environment) -> New secret, one per row above. Variables go under
the Variables tab.

## Swapping dummy -> real

Replace each value in place; no code change is needed. After real values are
in: set `TEST_MODE=false` and `ENCRYPT_OUTPUT=true` (the CLI refuses
`ENCRYPT_OUTPUT=false` outside test mode).

## S/MIME public certificate (phase 2)

Load **only the public certificate** - never the private key, never a `.p12`
/ `.pfx` bundle (those contain the private key). The certificate itself is
public material, but it carries the holder's name and email, so it lives in
Secrets like the rest of the identity data and is never committed to this
public repository.

Expected format: PEM text, one block:

```
-----BEGIN CERTIFICATE-----
MIID...base64...
-----END CERTIFICATE-----
```

Exporting the public part only:

- **macOS Keychain Access**: select the certificate line (not the key line
  under it), File -> Export Items, format **Certificate (.cer)** or PEM. If
  offered `.p12`, stop - that is the private-key bundle.
- **From a `.cer`/DER file**: `openssl x509 -inform der -in cert.cer -out cert.pem`
- **From a received signed email**: most mail clients can show/export the
  sender's certificate; export certificate only.

Loading: the `filing` environment -> New secret -> name `SMIME_PUBLIC_CERT`,
paste the full PEM block. With the secret present the runner encrypts the
whole message with `openssl smime -encrypt -aes256` before SMTP; iPhone/Mac
Mail and Gmail decrypt natively for the private-key holder. A malformed
value fails the run fast and is reported by NAME only.
