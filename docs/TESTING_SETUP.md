# Synthetic SMTP setup (#64)

Create protected environment `testing`, required reviewer the owner, deployment
branch `main` only. Keep production unchanged. Add environment secrets:

- TEST_FILING_BUNDLE: the JSON below, replacing only credential/delivery/test
  password placeholders. Never save the filled JSON in the repo or chat.
- TEST_APPROVED_RECIPIENT: the single privately approved test inbox, identical
  to delivery.recipient_email. The final SMTP envelope is checked against it.

Generate PDF and archive passwords independently for testing. Do not copy
production encryption credentials. Enter SMTP credentials directly in GitHub
or upload through authorized secret-setting automation; never print them.

```json
{
  "version": 2,
  "complainant": {
    "first_name": "ZZ-SYNTHETIC-NOT-A-PERSON",
    "last_name": "ZZ-TEST-ONLY",
    "id_number": "TEST-NOT-A-VALID-ID",
    "address": "ZZ-FICTIONAL-NOT-A-DELIVERY-ADDRESS",
    "phone": "NOT-A-PHONE"
  },
  "pdf_password": "<independent test password, 24-127 characters>",
  "archive_password": "<different independent test password, 24-127 characters>",
  "delivery": {
    "recipient_email": "<approved test inbox>",
    "smtp_host": "<SMTP host>",
    "smtp_port": 587,
    "smtp_username": "<approved SMTP login email>",
    "smtp_app_password": "<SMTP app password>",
    "smtp_from": "<approved sender email>"
  }
}
```

Synthetic identity is deliberately invalid for real use and must match exactly.
The test-only parser accepts it; production schema remains unchanged. The test
command does not consult FILING_BUNDLE, CASE_DATA_PRIVATE_KEY or real-data inputs.
The workflow maps ONLY the two testing secrets, on one gated application step.
Repository secret values are not automatically injected into processes; never
add production references or secrets inheritance to this workflow.

After reviewed implementation merges, dispatch `Synthetic batch SMTP exercise`
on main, select zip-legacy or zip-aes and optionally split. Approve the testing
deployment. This sends real SMTP mail, not a dry run, always marked TEST. No
artifacts are uploaded. Confirm SMTP acceptance AND inbox receipt separately.
The archive password is a test secret, not printed in logs or mail; the owner
must retain it privately. Wrong-password ZipCrypto failures can surface as a
CRC, decompression or password error, all of which mean no valid member data.
