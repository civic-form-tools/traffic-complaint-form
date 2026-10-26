# Atomic filing secret

Create **FILING_BUNDLE** under Settings -> Environments -> **production** ->
Environment secrets. Do not create a repository-level copy. The parser
requires the complete version-1 JSON object, including delivery settings,
even for dry runs. There is no fallback to the old individual secrets.

Replace every placeholder locally or directly in GitHub. Never put real
values in an issue, PR, repository file, command argument or chat.

```json
{
  "version": 1,
  "complainant": {
    "first_name": "YOUR_FIRST_NAME",
    "last_name": "YOUR_LAST_NAME",
    "id_number": "YOUR_9_DIGIT_ID",
    "address": "YOUR_ADDRESS",
    "phone": "YOUR_PHONE"
  },
  "pdf_password": "YOUR_STRONG_PDF_PASSWORD",
  "delivery": {
    "recipient_email": "YOUR_RECIPIENT_EMAIL",
    "smtp_host": "smtp.gmail.com",
    "smtp_port": 587,
    "smtp_username": "YOUR_SENDER_EMAIL",
    "smtp_app_password": "YOUR_APP_PASSWORD",
    "smtp_from": "YOUR_SENDER_EMAIL"
  }
}
```

All fields are required. Unknown keys, duplicates, arrays, missing/empty
fields, wrong types and line breaks in field values are rejected with a
fixed diagnostic that echoes neither supplied names nor values. The ID
must be nine ASCII digits with a valid Israeli checksum. The PDF password
must have at least 16 characters and at most 127 UTF-8 bytes. Choose a long,
random password; length validation is not an entropy guarantee. SMTP port
is a JSON integer, not a quoted string (normally 587 for STARTTLS).

The bundle stays in process memory; it is not split into GITHUB_ENV,
outputs, command arguments or temporary plaintext configuration files.
Runtime exception details are withheld because a library can echo secrets.
Sample workflow runs always force a test watermark without changing the
production variable. Test mode only watermarks the form; it is not proof that identity is fake.
PDF encryption is therefore mandatory in every mode, without an ID fallback.

`CASE_DATA_PRIVATE_KEY` remains a separate secret for encrypted incident
payloads. Its existing repository scope is a residual risk described below;
it has not been migrated automatically. `TEST_MODE` is a non-secret variable
(default true). `ENCRYPT_OUTPUT=false` now fails closed in every mode.

## Cutover and removal

1. Load the complete FILING_BUNDLE into production directly in GitHub.
2. Merge the bundle-only workflow after green CI. If merged before loading,
   filing fails closed until the bundle is present. No dual-source period.
3. Make an owner-authorized verification run and confirm delivery/decryption.
4. Only after that succeeds, delete the old filing environment (which removes
   its individual secrets) and the repository SMTP_APP_PASSWORD. These are
   the old individual secrets, including any copies elsewhere:
   
   COMPLAINANT_FIRST_NAME, COMPLAINANT_LAST_NAME, COMPLAINANT_ID,
   COMPLAINANT_ADDRESS, COMPLAINANT_PHONE, PDF_PASSWORD, RECIPIENT_EMAIL,
   SMTP_HOST, SMTP_PORT, SMTP_USERNAME, SMTP_APP_PASSWORD, SMTP_FROM.
5. Verify deletion by listing names only. Keep FILING_BUNDLE and
   CASE_DATA_PRIVATE_KEY. Cancel or do not approve old queued runs: runs on
   old commits still use the old workflow. Do not rerun those after cutover.

Existing PDFs keep their original passwords; replacing the bundle does not
re-encrypt previous files. GitHub secrets cannot be read back for migration.

## Threat model and trust boundary

Bundling prevents a person who can **only replace a secret** from changing
just the PDF password or delivery destination while keeping an unknown old
identity. Replacing the bundle replaces all those fields. Strict validation
rejects partial replacements rather than combining them with legacy values.
It is not cryptographic protection against code authors or administrators.

At the October 26 audit, both repository collaborators (`reihl` and
`reihlinstinct`) have admin rights. main requires green CI but zero approving
reviews; CODEOWNERS alone is not enforced review. filing lists both accounts
as reviewers: **either one** can approve, not both; self-review is permitted
and admin bypass enabled. These choices are retained, not represented as
separation of duties. Admins can also change the protection rules themselves.

The production environment is restricted to the main branch, and the checked-in
workflow also refuses non-main refs. The environment branch rule is the
real protection against a rewritten workflow on another branch. A malicious
change merged into main can still read and exfiltrate the entire bundle
when approved. An independent owner review of every workflow/runtime change,
restricted admin access, no admin bypass and independent deployment approval
are needed if distrust of the code author is a requirement.

At audit time SMTP_APP_PASSWORD and CASE_DATA_PRIVATE_KEY are repository
secrets, while the ten other configured individual fields are in filing.
Repository secrets are not protected by an environment gate. The old SMTP
password is removed after the bundle test. Moving the case-data private key
requires a separate owner-controlled migration; it remains a known risk.

Ordinary fork PRs do not receive Actions secrets; CI approval is not approval
to expose secrets. Never run untrusted PR code in a privileged context (for
example pull_request_target with PR checkout). Same-repository writers may
change workflows or reference repository secrets, so require code review and
keep sensitive credentials in production. Steps receiving the bundle are scoped
to the application invocation, not checkout/dependency installation. This
reduces accidental exposure but does not sandbox malicious runtime code or
dependencies. CI tests check known logging paths, not arbitrary future code;
GitHub masking of a JSON blob is not reliable masking of extracted fields.

Official references:
- https://docs.github.com/en/actions/security-for-github-actions/security-guides/using-secrets-in-github-actions
- https://docs.github.com/en/actions/reference/workflows-and-actions/deployments-and-environments

## Environment name migration

The owner loaded FILING_BUNDLE into production. Before the workflow switches,
production is configured with the same required reviewers (reihl OR
reihlinstinct), permitted self-review/admin bypass, and main-only branch
policy as filing. The workflow now targets production, not filing. The old
filing environment remains until the new run succeeds and its output is
confirmed, then it is removed. The case-data key remains untouched.

## Safe validation diagnostics

The validate_only dispatch input checks the bundle with no PDF or email.
Validation failures report only a fixed, allowlisted schema path (for example
pdf_password, complainant.id_number, delivery.smtp_port, root, json). They
never echo supplied keys or values. root/complainant/delivery means a wrong
object shape or missing/extra keys; compare against the template. The parser
does not expose the contents to operators. After correction by the owner,
run the authorized sample delivery to complete cutover verification.
