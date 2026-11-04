# Fully synthetic end-to-end batch delivery (design, #64)

Status: proposed. No workflow or settings change is implemented by this document.

## Outcome

A permanent manual test runs the same PDF renderer, archive backends, size
splitting, verifier and SMTP sender as a real batch. It sends only to the
owner's approved inbox. Identity AND cases are invented. It never files a
complaint or contacts an official. Legacy sample mode is not this mode:
legacy samples still use the complainant identity from the production bundle.

## Separate configuration

- A new workflow selects the protected `testing` environment, main branch
  only, with the owner as required reviewer. Production is untouched.
- `TEST_FILING_BUNDLE` is a testing-environment secret. It contains strict
  dummy identity, independent test-only PDF/archive passwords, archive format,
  cap and the approved SMTP delivery settings. No production bundle or case
  key is copied. Never store this JSON as an Actions variable.
- The approved sender may be the same SMTP account as production. Its
  credential is the sole necessary real-secret exception. A stored credential
  can be uploaded directly to GitHub without printing it. Do not put it in a
  comment, command argument, issue, log or shareable setup file.
- The recipient is checked against a separate owner-approved testing setting,
  not accepted as a workflow input. No CC/BCC or destination override.
- The synthetic command accepts only test choices such as archive backend
  and size-split exercise. No encrypted case, plaintext case, identity,
  recipient, production config or filesystem source input is accepted.
- Missing or malformed test configuration fails closed. There is no fallback
  to `FILING_BUNDLE`, `CASE_DATA_PRIVATE_KEY` or production files.

## Execution boundaries

1. A dedicated entry point branches before the production config loader.
2. It validates `TEST_FILING_BUNDLE` and requires the exact built-in dummy
   identity. Fictional cases are built in memory, not read from a caller file.
3. Rendering, open inner PDFs, encrypted archives, greedy splitting and
   every-member verification use the production modules. Split exercises
   add documented synthetic padding, never actual evidence or personal data.
4. SMTP delivery uses the existing sender with fixed TEST subject/body and
   the approved destination. It does not use an alternate mail API or claim
   dry-run generation is delivery. Each part gets a numbered email.
5. No artifact upload, cache of filing output, public preview or step summary
   containing private values. Temporary plaintext is cleaned on every exit.
   Logs report only mode, counts, sizes and delivery status.

A separate build/delivery job split is preferable if implementing it does not
require public artifact transfer. Otherwise use explicit in-process builder
and sender interfaces: builder receives dummy identity/data and test archive
password only; sender receives SMTP-only settings and verified dummy paths.
Never give the builder the full bundle when a smaller object suffices.

## Regression tests and their limits

Use offline invented fixtures and mocked SMTP. Plant unique production
canaries in env, fake bundle/key files and working-directory files. Track
access to filing env names, production config parsing, decryption and file
reads as well as scanning outputs. Mutating production canaries must not
change decrypted synthetic PDF semantics. Ciphertext equality is not expected
because encryption is randomized.

Assert no production canary reaches logs, errors, outer filenames, ZIP
metadata, decoded mail headers/body or decrypted synthetic PDFs. Correct
password opens every member; no/wrong password fails; inner PDFs are open.
Test both archive formats, multipart ordering, all failure exits and plaintext
cleanup. Reject mismatched test identity/destination and all real-data inputs.
Inject forbidden reads/leaks to prove tests fail, rather than counting skips
or expected failures as protection.

Workflow tests reject production environment/secret references, sensitive
`vars.*`, inherited secrets, publishing outputs, unprotected execution and
recipient dispatch inputs. Test delivery has exactly one approved envelope
recipient and fixed TEST wording. Existing privacy issues #59-#63 supply
shared guards where applicable.

This is application noninterference evidence, not an operating-system
sandbox guarantee: a process could read any file its OS account can read.
The primary boundary is a clean runner with NO production secret injection
and no production files. The SMTP send necessarily accesses its credential;
claims of zero real-secret access across the entire workflow would be false.

## Setup and acceptance

1. Review/merge this design, then implement through independently reviewed PRs.
2. Create testing environment with main-only branch policy, owner approval per
   run and no weaker production protection. Do not change production settings.
3. Upload TEST_FILING_BUNDLE directly from dummy config plus the approved
   vaulted SMTP credential. Set the approved testing recipient privately.
   List names only afterward; GitHub cannot return secret values for review.
4. Inspect workflow refs and a names-only test config validation before send.
5. Owner approves the testing deployment. Dispatch legacy, AES and split
   exercises; verify SMTP acceptance, then ask for receipt/opening confirmation.
   SMTP acceptance alone is not proof of inbox delivery.
6. Record run URLs, exact mode, recipient and safe subject lines privately.
   Never print a persistent password. Tests remain wholly offline in CI.

Only owner-only GitHub permissions or deployment approval should require an
owner click. If authenticated settings access permits setup, the authorized
setup can be performed directly. No request to paste a secret into chat.
