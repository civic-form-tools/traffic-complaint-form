# Design: traffic-complaint-form

## Context

The user photographs traffic offences (mostly sidewalk parking) and wants to
file police complaints (תלונה על עבירת תנועה, Jerusalem District Traffic
Department form). The form requires the complainant's identity (name, ID
number, address, phone) which must **never** be accessible to the automation
agent or present in the public repository. The filled form is delivered to
the user's email.

## Goals

- Public repo, no personal data anywhere: code, fixtures, docs, logs,
  workflow inputs, artifact storage (none is used).
- Identity and delivery configuration only in GitHub Secrets, loaded by the
  user; values are write-only afterwards.
- Filled form produced as a one-page RTL Hebrew PDF, emailed to the user.
- Everything on free tiers; runs fail fast before consuming minutes.
- Repo conventions: CI, tests (coverage floor 80%), pinned actions, CodeQL,
  Dependabot, secret scanning, issue + PR per change.

## Non-goals (phase 1)

- Submitting the complaint to the police (the user prints/signs/files).
- Witnesses beyond the single optional witness row.
- Asymmetric output encryption (phase 2, see below).

## Data flow

See README for the diagram. Channels:

1. **Complainant identity + delivery config**: GitHub Secrets, mapped to env
   only inside the `filing` environment job. GitHub masks them in logs; the
   code never prints them (missing config is reported by variable NAME).
2. **Case data (plates, locations, incident details)**: public workflow
   inputs and logs are world-readable, so real case data travels only as a
   **sealed-box ciphertext** (libsodium, PyNaCl). Callers encrypt with the
   repository public key (`form/keys/case-data-public.key`); the private key
   is the `CASE_DATA_PRIVATE_KEY` secret. Decryption happens in memory; the
   output filename uses a digest of the ciphertext, and no log line carries
   case values (covered by tests). Plaintext `--case-json` and `--sample`
   modes remain for local development and pipeline tests.
3. **Output**: one-page PDF (WeasyPrint), then:
   - `ENCRYPT_OUTPUT=true` (default): pikepdf AES-256 password encryption;
     the password is the `PDF_PASSWORD` secret. The file opens natively on
     iPhone/Mac after typing the password.
   - `ENCRYPT_OUTPUT=false`: allowed only while `TEST_MODE=true` (dummy
     phase, user decision 2026-10-26). The CLI hard-refuses otherwise.
4. **Delivery**: Gmail SMTP over STARTTLS with an app password. The SMTP 250
   accept is the delivery receipt; only status is logged.
5. **Gate**: the `filing` environment requires reviewer approval before any
   secret is exposed to a run.

## Key decisions and alternatives

### Case-data privacy: sealed box (chosen) vs private caller repo vs plaintext
- Plaintext inputs: rejected - public inputs/logs would leak plates.
- Private caller repo dispatching with a plaintext payload: rejected as the
  sole mechanism - the payload still lands in the public repo's run event.
- Sealed box: caller needs only the public key (committed); any caller
  (parking automation, a manual script) can encrypt; only the workflow can
  decrypt. Chosen.

### Output encryption phase 1: PDF password (chosen) vs age/GPG
The deliverable must open easily on iPhone/Mac. A password-protected PDF
opens in every native PDF viewer; age and GPG need extra tooling on iOS.

### Output encryption phase 2 (planned): asymmetric to the user's public key
User decision 2026-10-26: after the basic pipeline works, encrypt the output
to a public key so only the user (private key holder) can open it.
Options:
- **S/MIME envelope (recommended)**: encrypt the whole email with the user's
  S/MIME certificate (public cert committed; private key stays in his Apple
  Mail). iPhone and Mac Mail decrypt S/MIME natively - no apps, no passwords.
  Requires him to hold a personal S/MIME certificate (free Actalis certs
  exist; the assistant mailbox already uses one).
- **GPG-encrypted attachment**: solid, but iPhone decryption needs a
  third-party app (worse UX).
- **age**: best CLI ergonomics on desktop, no practical iOS path.
Open question for the user: does he already hold an S/MIME certificate or
PGP key for his email? If not, we set up a free Actalis S/MIME cert and
install it in Apple Mail. Implementation hook: `mail.py` gains an envelope
step (openssl smime -encrypt) behind `ENCRYPTION_METHOD=smime|password|none`.

### Rendering: HTML/CSS -> WeasyPrint (chosen) vs AcroForm overlay vs reportlab
The form is a redesigned layout (a Google Doc replica of the photographed
original), not an official AcroForm PDF, so there is nothing to overlay.
HTML/CSS gives precise RTL control and easy iteration; reportlab would mean
hand-placing every string. The one-page invariant is enforced in code and
covered by tests (overflow -> exit 3).

### Email route: Gmail SMTP + app password (chosen) vs SendGrid/Brevo/Resend
Gmail SMTP is free, needs no new third-party account or terms review, and
Gmail-to-Gmail delivery is reliable. An app password is a Secret loaded by
the user. Sender account: see open decisions.

### No artifacts
The filled PDF is never uploaded as a workflow artifact: artifacts of a
public repo are public. Email is the only delivery channel.

### Fail fast + verification
Secret presence is validated (names only) before checkout/setup to save
minutes. After building, the workflow verifies: exactly one PDF, sane size,
password required (when encryption is on), exactly one page. Failed runs get
a `bug` issue with evidence per convention.

## Secrets specification

See docs/SECRETS.md. All values are loaded by the user; examples there are
invented. The `CASE_DATA_PRIVATE_KEY` is a random key (not personal data); the
public half is committed. It was rotated on 2026-10-26 when it moved into the
protected production environment; rotation is safe because the key protects
only in-transit payloads, never data at rest.

## Testing strategy

- Unit: models (validation, ID checksum, weekday derivation), template
  rendering (escaping, tri-state, watermark), crypto roundtrip.
- Functional: full CLI dry-runs (sample, JSON, encrypted payload), page-count
  invariant, overflow rejection, mail flow against a mocked SMTP (TLS before
  login, no credentials/recipient in logs), log-privacy tests for the
  encrypted path.
- e2e: first real pipeline run with `sample_data` + dummy secrets, approved
  through the environment gate; the emailed PDF is the evidence.
- Coverage floor 80% (currently ~91%).

## Cost

Public repo: unlimited Actions minutes. A filing run: ~2-3 minutes
(dependency install dominates). CI runs only on code paths. Fail-fast secret
check runs before any setup.

## Future work (tracked as issues)

- Phase 2: S/MIME envelope to the user's certificate (replaces/shared with
  the PDF password).
- `repository_dispatch` trigger from the private parking automation with an
  encrypted payload per repeat-offence plate (also the answer for batches
  beyond the dispatch-input size cap).
- Witness rows beyond one.
- CodeRabbit enablement (public repo, per user convention).

## Batch mode (2026-11-04, #42)

Several complaints are filled in one run and delivered as ONE encrypted
archive; the PDFs inside are open - the archive is the only encryption layer
(user decision, unlike single mode's locked PDF). Format and password come
from FILING_BUNDLE v2 (`archive_format`, `archive_password`).

```mermaid
flowchart LR
    A["dispatch input: sealed-box<br>{"cases": [case, ...]}"] --> D["decrypt in memory"]
    D --> V["validate ALL cases (fail-fast,<br>per-index diagnostics, no values)"]
    V --> F["render N OPEN PDFs<br>(temp dir, neutral names<br>complaint-NN.pdf)"]
    B[("FILING_BUNDLE v2<br>archive_password + archive_format")] --> Z
    F --> Z["archive.py (pluggable)<br>zip-legacy default / zip-aes"]
    Z --> W["verify: password required, N members,<br>each an open well-formed PDF, page caps"]
    W --> M["one email, one ZIP attachment"]
```

Key decisions:

- **zip-legacy (ZipCrypto) is the default despite being weak crypto**: the
  2026-11-04 device test showed AES-256 ZIP does not open on the owner's
  iPhone/Mac. The risk (Biham-Kocher known-plaintext over shared template
  boilerplate) is accepted and documented in SECRETS.md; mitigations are a
  long random password and neutral member names (ZIP never encrypts
  filenames). `archive_format = "zip-aes"` swaps to WinZip AES-256
  (pyzipper) with a one-field secret edit once devices support it. The
  ZipCrypto writer is pure Python (pyzipper does not write it); interop is
  pinned by tests against pyzipper, stdlib zipfile and Info-ZIP.
- **Fail-fast**: any invalid case, render failure, page overflow or archive
  failure aborts before any email; no partial archive is mailed. All cases
  are validated before rendering; diagnostics cite case index only.
- **Payload**: one sealed-box JSON `{"cases": [...]}` (each case = the
  single-mode schema), capped at 20 cases so the ciphertext fits the
  dispatch input. Larger batches need the future repository_dispatch
  channel.
- **Batch mail**: ASCII subject "Traffic complaint forms - batch of N -
  DD/MM/YYYY" (same gateway rule), Hebrew body naming archive_password.
- The `production` environment gate covers `fill-batch.yml` exactly as
  `fill-form.yml`; workflow-structure tests enforce the same invariants on
  both.

## Atomic filing configuration (2026-10-26)

FILING_BUNDLE replaces all individual identity, PDF-password and SMTP/delivery
secrets. The strict, versioned JSON object is loaded atomically, never merged
with separate fields. Encryption is mandatory even in test mode. The current
configuration contract and residual trust risks supersede the earlier
individual-secret design: see [SECRETS.md](SECRETS.md).
