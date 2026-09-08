# Error codes — generated from `app/core/errors.py`

Do not edit. Regenerate with `make error-codes`.

`code` is the client's contract (`01-foundations.md` §12). Clients switch on it,
never on `detail` or on the status alone.

| Code | Status | Meaning |
|---|---|---|
| `internal_error` | 500 | An unhandled failure. The response carries no detail; the log does. |
| `validation_error` | 422 | The request body failed validation. `details.fields` names each. |
| `not_found` | 404 | No such resource, or it is not yours (`02` §6: 404, never 403). |
| `conflict` | 409 | The request conflicts with the resource's current state. |
| `rate_limited` | 429 | Too many requests. `Retry-After` says when to try again. |
| `not_implemented` | 501 | A reserved route with no implementation behind it (`01` §15). |
| `service_unavailable` | 503 | A dependency the request needs is down. |
| `password_too_short` | — | Passwords are at least 10 characters. |
| `password_too_long` | — | Passwords are at most 128 characters. |
| `password_breached` | — | The password appears in a known breach corpus. |
| `consent_version_stale` | — | The accepted consent version is not the current one. |
| `invalid_credentials` | — | Identical for a wrong password and an unknown account. |
| `oauth_invalid_token` | — | The Google ID token failed verification. |
| `oauth_email_unverified` | — | Google did not assert the address is verified. |
| `last_credential` | — | Unlinking would leave the account with no way to sign in. |
| `email_not_verified` | — | The address must be verified before this operation. |
| `token_expired` | — | The token is past its expiry. |
| `token_invalid` | — | The token is malformed, used, or of the wrong kind. |
| `refresh_reused` | — | A revoked refresh token was presented; the family is revoked. |
| `account_pending_deletion` | — | The account is in its deletion grace period. |
| `signups_closed` | — | Registration is closed (`FLAG_SIGNUP_ENABLED`, D10). |
| `invalid_cursor` | — | The pagination cursor is malformed or was tampered with. |
| `idempotency_in_progress` | — | A request with this key is still running. |
| `idempotency_key_reuse` | — | This key was used with a different body. |
| `profile_version_conflict` | — | The profile changed since this edit was started. |
| `unmappable_title` | — | The title maps to no family, so it would yield no feed. |
| `file_too_large` | — | The upload exceeds the 5 MB cap. |
| `unsupported_file_type` | — | Magic bytes say this is not a PDF or DOCX. |
| `file_rejected_suspicious` | — | The archive has zip-bomb characteristics. |
| `ai_budget_exceeded` | — | The daily AI cap is reached. `Retry-After` gives the reset. |
| `ai_unavailable` | — | The AI provider could not be reached. |
| `pack_not_approvable` | — | Open fabrication flags or unresolved answers remain. |
| `pack_immutable` | — | An approved pack cannot be edited; revise it into a new one. |
| `answer_type_mismatch` | — | The answer does not match the question's declared type. |
| `invalid_transition` | — | `details.allowed` lists the transitions that are possible. |
