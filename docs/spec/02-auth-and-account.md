# 02 — Authentication & Account

**Module:** `apps/api/app/modules/auth`
**Track:** R1 except §4 and §8 (R2)
**Depends on:** `01-foundations.md`, `17-data-model.md` §2.1–2.3
**Requirements:** `AUTH-01` … `AUTH-10`
**Public API:** `AuthService.register`, `.login`, `.oauth_login`, `.refresh`, `.logout`, `.verify_email`, `.request_reset`, `.reset`, `.request_deletion`, `get_current_user` dependency, `require_role`
**Publishes:** `UserRegistered`, `UserDeletionRequested`. **Consumes:** none.

---

## 1. Registration and password policy — `AUTH-01`

**Objective.** Create an account from an email and a password that is not already known to be compromised, without revealing whether an email is registered.

**Constraints.**
- Password: minimum 10 characters, maximum 128 (bcrypt-style truncation bugs do not apply to Argon2, but a cap prevents a DoS via a 10 MB password). No composition rules — length and a breach check outperform character-class requirements.
- Breach check via the Pwned Passwords **k-anonymity** range API: send the first 5 hex characters of the SHA-1 hash, never the password or its full hash. A match rejects with `password_breached` and a count. If the service is unreachable, **allow** the registration and record a metric — a third-party outage must not close the front door.
- Hashing: Argon2id via `argon2-cffi`, `time_cost=3`, `memory_cost=65536` (64 MiB), `parallelism=1`, 16-byte salt. Parameters are stored with the hash so they can be raised later and old hashes rehashed on next successful login.
- Registration is **enumeration-safe**: the response for an existing email is identical to the response for a new one (202 with "check your email"). The existing-account case sends a "someone tried to register with your address" email instead of a verification link.
- Rate limited per IP and per email (§9).
- Consent is captured at registration, not after: the request body carries `consent_version` and the accepted item keys, and a version that is not the current one is rejected (`16-security-and-compliance.md` §4).
- `email_normalized` (`17-data-model.md` §2.1) is the uniqueness key.

**Inputs.** `RegisterRequest{email, password, consent_version, consent_items[], tz?}`.

**Outputs.** `users` document with `email_verified: false`; an `email_tokens` row of kind `verify_email`; a verification email; `UserRegistered` event; `202`.

**Acceptance criteria.**
- `AC-AUTH-01.1` A password of 9 characters is rejected `422 password_too_short`; 10 is accepted; 129 is rejected.
- `AC-AUTH-01.2` A known-breached password is rejected `422 password_breached`, and the request to the breach service contains only a 5-character hash prefix (asserted on the outbound request).
- `AC-AUTH-01.3` With the breach service returning 503, registration succeeds and `breach_check_unavailable` is incremented.
- `AC-AUTH-01.4` Registering an already-registered email returns a response byte-identical to a fresh registration (same status, same body, timing within 50 ms), and sends the "attempted registration" email rather than a verification link.
- `AC-AUTH-01.5` Two registrations for `a.b@gmail.com` and `ab@gmail.com` collide on `email_normalized`; `a.b@example.com` and `ab@example.com` do not.
- `AC-AUTH-01.6` A stored hash begins with `$argon2id$` and encodes `m=65536,t=3,p=1`.
- `AC-AUTH-01.7` A registration with a stale `consent_version` is rejected `422 consent_version_stale` and creates no user.

**Tests.**
- `T-AUTH-01.1` `tests/unit/test_password_policy.py`.
- `T-AUTH-01.2`/`.3` `tests/integration/test_breach_check.py` (respx).
- `T-AUTH-01.4` `tests/integration/test_registration_enumeration.py`.
- `T-AUTH-01.5` `tests/unit/test_email_normalization.py`.
- `T-AUTH-01.6` `tests/unit/test_argon2_params.py`.
- `T-AUTH-01.7` `tests/integration/test_consent_capture.py`.

---

## 2. Google sign-in — `AUTH-02`

**Objective.** Sign in with Google, linking to an existing account only when Google asserts the same address is verified.

**Constraints.**
- OIDC authorization-code flow with PKCE. The **server** exchanges the code; the client never holds the client secret. `authlib` in `modules/auth` only — and `ai/*` is forbidden from importing it (HR-6, `01-foundations.md` §4).
- The ID token is verified: signature against Google's JWKS (cached, refreshed on unknown `kid`), `iss`, `aud` equal to our client id, `exp`, and `nonce` matching the one we issued.
- Linking rule: if `email_verified` is true in the ID token **and** an account exists with that `email_normalized`, link the `oauth` entry to it. If `email_verified` is false, never link — create nothing and return `409 oauth_email_unverified`. An unverified Google email is an account-takeover vector.
- A linked account's `email_verified` becomes true (Google has verified it) and `AUTH-03`'s gate opens.
- A user who registered with a password and then signs in with Google keeps the password. Unlinking Google is allowed only if a password is set.
- Mobile uses the same server-side exchange via a custom scheme redirect; there is no separate mobile client secret.

**Inputs.** `authorization_code`, `code_verifier`, `nonce`, `redirect_uri`.

**Outputs.** Token pair; `users.oauth[]` entry; `UserRegistered` on first sign-in.

**Acceptance criteria.**
- `AC-AUTH-02.1` A tampered ID token signature, a wrong `aud`, an expired `exp`, or a mismatched `nonce` each return `401 oauth_invalid_token` and create nothing (four cases).
- `AC-AUTH-02.2` `email_verified: false` returns `409 oauth_email_unverified` and creates no user and no link.
- `AC-AUTH-02.3` Signing in with Google using the address of an existing password account links to it rather than creating a second account, and the password still works afterwards.
- `AC-AUTH-02.4` An unknown `kid` triggers exactly one JWKS refresh, and a second unknown `kid` within 60 s does not refresh again.
- `AC-AUTH-02.5` Unlinking the only credential (Google, no password) is refused `409 last_credential`.
- `AC-AUTH-02.6` The client secret appears in no response, no log line, and neither built client artifact.

**Tests.**
- `T-AUTH-02.1`–`.5` `tests/integration/test_google_oidc.py` (fake JWKS + signed fixtures).
- `T-AUTH-02.6` shared with `T-AI-05.5` artifact secret scan.

---

## 3. Email verification — `AUTH-03`

**Objective.** Prove the address before spending money on the account's behalf.

**Constraints.**
- A single-use token, 32 bytes from a CSPRNG, base64url; stored only as `sha256("verify:" || token)`; 24-hour expiry; 5 attempts.
- The gate is enforced **server-side** on: resume upload, pack generation, and any AI-spending endpoint. Not on login, not on profile editing — a user who mistyped their address should still be able to fix it.
- Resend is rate limited to 3 per hour per account and invalidates prior unused tokens for that kind.
- Verification is idempotent: a used token returns the same success shape rather than an error, because users double-click links.

**Inputs.** `token`.

**Outputs.** `users.email_verified: true`; `email_tokens.used_at`.

**Acceptance criteria.**
- `AC-AUTH-03.1` `POST /profile/resumes` and `POST /applications/{id}/pack` return `403 email_not_verified` for an unverified user; `PATCH /profile` succeeds.
- `AC-AUTH-03.2` The plaintext token appears nowhere in the database and nowhere in logs.
- `AC-AUTH-03.3` A token used twice returns success both times and marks the address verified once.
- `AC-AUTH-03.4` An expired token returns `410 token_expired`; a 6th wrong attempt returns `429`.
- `AC-AUTH-03.5` Requesting a resend invalidates the previous token (using it afterwards returns `410`).

**Tests.** `T-AUTH-03.1`–`.5` `tests/integration/test_email_verification.py`; `T-AUTH-03.2` also `tests/integration/test_log_privacy.py`.

---

## 4. Sessions and token lifecycle — `AUTH-04`

**Objective.** A stolen refresh token is detectable and its theft revokes the whole family; a stolen access token is short-lived.

**Constraints.**
- Access token: RS256 JWT, 15-minute TTL, claims `sub`, `iss`, `aud`, `iat`, `exp`, `jti`, `role`. **No email, no name, no PII** — a JWT is readable by anyone holding it.
- Refresh token: 32 random bytes, opaque, stored as `sha256(pepper || token)` with the pepper from config (not the DB, so a database dump alone is not enough). 30-day TTL.
- **Rotation on every use.** The presented token is marked `revoked_at` with `revoked_reason: rotated` and `replaced_by` set; a new token is issued in the same family.
- **Reuse detection.** Presenting an already-revoked token revokes the **entire family** with reason `reuse_detected`, and returns `401 refresh_reused`. A user whose family is revoked must log in again. This is the single most valuable control in this module: it converts a silent theft into a visible logout.
- Web: refresh token in a `Secure; HttpOnly; SameSite=Lax` cookie scoped to the API host; access token held in memory only, never in `localStorage`. Because a cookie is used, every state-changing route requires a double-submit CSRF token (`16-security-and-compliance.md` §2).
- Mobile: refresh in `flutter_secure_storage`; access in memory.
- Password change, deletion request, and reuse detection each revoke all families.
- Clock skew tolerance on `exp` is 30 s, no more.
- Key rotation: `JWT_PUBLIC_KEY_PEM` accepts a list so a new key can be published before it signs; documented in the runbook.

**Inputs.** Credentials, or a refresh token.

**Outputs.** Access token, refresh token, `refresh_tokens` rows.

**Acceptance criteria.**
- `AC-AUTH-04.1` A decoded access token contains no email, name, phone, or any claim beyond the seven listed.
- `AC-AUTH-04.2` Refreshing returns a **new** refresh token and the old one is unusable; using the old one revokes the family and returns `401 refresh_reused`.
- `AC-AUTH-04.3` After family revocation, every token in that family fails, and tokens in another family for the same user still work (until they are also revoked by a password change).
- `AC-AUTH-04.4` The web refresh cookie has `Secure`, `HttpOnly`, `SameSite=Lax`, and a host-scoped `Domain`; no response body contains the refresh token for web clients.
- `AC-AUTH-04.5` An access token expired by 31 s is rejected; by 29 s, accepted.
- `AC-AUTH-04.6` A concurrent double refresh (two requests with the same token, in flight together) results in one new token issued and one `401`, never two valid families.
- `AC-AUTH-04.7` Changing the password revokes every family and the next request with an old access token still succeeds until its 15 minutes elapse (documented, deliberate — access tokens are not revocable in R1; `16-security-and-compliance.md` §2 records the accepted risk).

**Tests.**
- `T-AUTH-04.1` `tests/unit/test_jwt_claims.py`.
- `T-AUTH-04.2`/`.3`/`.6` `tests/integration/test_refresh_rotation.py`.
- `T-AUTH-04.4` `tests/integration/test_cookie_flags.py`.
- `T-AUTH-04.5` `tests/unit/test_clock_skew.py`.
- `T-AUTH-04.7` `tests/integration/test_password_change_revocation.py`.

### 4.1 Session list and global sign-out — `AUTH-06` — **Track: R2**

**Objective.** Show where the account is signed in and end all of it.

**Constraints.** Lists refresh-token families, not access tokens. Shows `device.ua` parsed to a coarse label and `ip_prefix`, never a full IP. "Sign out everywhere" revokes all families with reason `logout`.

**Acceptance criteria.** `AC-AUTH-06.1` The list shows one row per live family and none for revoked ones. `AC-AUTH-06.2` Revoking one family leaves others working. `AC-AUTH-06.3` "Sign out everywhere" revokes all and the current session's next refresh fails. `AC-AUTH-06.4` No full IP address is returned.
**Tests.** `T-AUTH-06.1`–`.4` `tests/integration/test_sessions.py`.

---

## 5. Password reset — `AUTH-05`

**Objective.** Recover access without a support ticket, without becoming a takeover vector.

**Constraints.**
- Enumeration-safe: the same 202 whether or not the address exists.
- Token: 32 CSPRNG bytes, `sha256("reset:" || token)`, 60-minute expiry, single use, 5 attempts.
- Using a reset token revokes all refresh families (an attacker who had a session loses it).
- The new password goes through the full `AUTH-01` policy including the breach check.
- Requesting a reset does **not** invalidate the current session — a user resetting from another device should not be logged out mid-task until the reset completes.
- Rate limited: 3 per hour per address, 10 per hour per IP.

**Inputs.** `email`, then `token` + `new_password`.

**Outputs.** New `password_hash`; all families revoked; a confirmation email.

**Acceptance criteria.**
- `AC-AUTH-05.1` Requesting a reset for an unknown address returns the same status and body as for a known one.
- `AC-AUTH-05.2` A used, expired, or wrong-kind token returns `410`/`401` and does not change the password.
- `AC-AUTH-05.3` A completed reset revokes every refresh family.
- `AC-AUTH-05.4` A breached new password is rejected and the token remains usable.
- `AC-AUTH-05.5` A confirmation email is sent on success and mentions no password material.

**Tests.** `T-AUTH-05.1`–`.5` `tests/integration/test_password_reset.py`.

---

## 6. Authorization model — `AUTH-10` (shared with `ADMIN-06`)

**Objective.** One rule for who may see what, applied in the service layer, that leaks nothing about what exists.

**Constraints.**
- Authorization is **ownership**, not roles, for everything a user touches. Every query on a user-owned collection carries `user_id` (`17-data-model.md` §1). The single role boolean (`role: operator`) gates `/admin` only.
- **A failed ownership check answers 404, never 403.** A 403 confirms the resource exists, turning every id-addressed endpoint into an enumeration oracle. The same rule governs `/admin/*`: a non-operator receives 404, not 403, so the admin surface is not discoverable.
- Ownership is checked **before** any field of the resource is read, so timing does not distinguish "exists but not yours" from "does not exist".
- This is not left to review. A dedicated suite creates every kind of resource as user A, then attempts **every id-addressed operation** as user B, requiring 404 from all of them, and asserts A's data is unchanged afterwards.

**Inputs.** Auth context; a resource id.

**Outputs.** `get_current_user`, `require_role("operator")`, `assert_owned(resource, user)`.

**Acceptance criteria.**
- `AC-AUTH-10.1` Every id-addressed route, enumerated from the OpenAPI document, returns 404 when called by a non-owner. No route returns 403 for an ownership failure.
- `AC-AUTH-10.2` Every `/admin` route returns 404 for a non-operator.
- `AC-AUTH-10.3` After the cross-tenant sweep, user A's document count and content hashes are unchanged.
- `AC-AUTH-10.4` A route added without an ownership check fails the sweep (the sweep is generated from the OpenAPI document, so a new route is covered automatically).
- `AC-AUTH-10.5` Response time for "not yours" and "does not exist" differ by less than 20 ms at p95.

**Tests.**
- `T-AUTH-10.1`–`.4` `tests/integration/test_cross_tenant_sweep.py` — generated from `openapi.json`.
- `T-AUTH-10.5` `tests/integration/test_ownership_timing.py`.

---

## 7. Account deletion — `AUTH-07`

**Objective.** A user can delete everything, verifiably, on a clock, without a support ticket.

**Constraints.**
- Two-phase: `DELETE /me` sets `status: pending_deletion` and `deletion_requested_at`, revokes every refresh family, immediately stops all processing (no ingestion scoring, no reminders, no digests), and sends a confirmation email with a cancel link. The account is inaccessible during the grace period except to cancel.
- Cancel is possible for 7 days via a token in that email.
- After 7 days, `account.purge_deleted` hard-deletes: every document carrying that `user_id` in every collection (`17-data-model.md` §2), and every object under `u/{user_id}/` including noncurrent versions (§4 of that file).
- `jobs` are shared and are never deleted (`AC-DATA-05.5`).
- The purge writes a `deletion_completed` audit row **keyed by a salted hash of the user id**, not the id itself, so the record that a deletion happened survives without retaining an identifier.
- The purge **verifies**: it re-lists the storage prefix and re-counts each collection, and fails loudly (alert) rather than reporting success on a partial delete.
- Backups older than the request still contain the data until they age out at 14 days; this is disclosed in the consent text.

**Inputs.** An authenticated request; then the cron.

**Outputs.** Purged data; audit row; two emails (requested, completed).

**Acceptance criteria.**
- `AC-AUTH-07.1` After a request, every authenticated route returns `403 account_pending_deletion` except the cancel endpoint, and no reminder, digest, or score is produced for that user.
- `AC-AUTH-07.2` Cancelling within 7 days restores full access and re-enables processing.
- `AC-AUTH-07.3` With a frozen clock at +7 days, the purge removes every document with that `user_id` across all collections — asserted by a per-collection count of zero, enumerated from the collection registry so a new collection cannot be forgotten.
- `AC-AUTH-07.4` Listing `u/{user_id}/` after the purge, including versions, returns zero objects.
- `AC-AUTH-07.5` A `deletion_completed` audit row exists and contains no recoverable user identifier.
- `AC-AUTH-07.6` A purge that cannot delete an object leaves the user in `pending_deletion`, alerts, and does not write the completion row.
- `AC-AUTH-07.7` No `jobs` document is modified or removed.

**Tests.**
- `T-AUTH-07.1`/`.2` `tests/integration/test_deletion_request.py`.
- `T-AUTH-07.3` `tests/integration/test_account_purge.py` (shared with `T-DATA-05.3`), enumerating collections from the registry.
- `T-AUTH-07.4` `tests/integration/test_deletion_sweep.py`.
- `T-AUTH-07.5` `tests/integration/test_deletion_audit.py`.
- `T-AUTH-07.6` `tests/integration/test_purge_failure.py`.
- `T-AUTH-07.7` `tests/integration/test_purge_isolation.py`.

---

## 8. Data export — `AUTH-08` — **Track: R2**

**Objective.** Give the user everything the product holds about them, in a form another tool can read.

**Constraints.** Async, idempotent (`Idempotency-Key`), rate limited to 1 per 24 h. Produces a zip at `u/{user_id}/exports/{export_id}.zip` containing `profile.json`, `resumes/` (original files), `applications.json`, `packs.json`, `answer_bank.json`, `match_scores.json` (score, components, explain — not embeddings), `audit_log.json`, `consent.json`, and a `README.txt` explaining each file. Delivered as a presigned link, valid 24 h, emailed; the object is deleted after 7 days. The export enumerates collections from the same registry the purge uses, so the two cannot diverge.

**Acceptance criteria.** `AC-AUTH-08.1` The zip contains one entry per collection in the registry that holds user data, plus the README. `AC-AUTH-08.2` Every JSON file parses and IDs cross-reference correctly. `AC-AUTH-08.3` The link expires in 24 h and the object is gone after 7 days. `AC-AUTH-08.4` A second request within 24 h returns the existing export rather than building another. `AC-AUTH-08.5` No other user's data appears in any file (verified with two seeded users).
**Tests.** `T-AUTH-08.1`–`.5` `tests/integration/test_data_export.py`.

---

## 9. Rate limiting — `AUTH-09`

**Objective.** Make credential stuffing and email-bombing expensive without locking out a legitimate user behind a shared IP.

**Constraints.**
- Redis token bucket. Two dimensions on auth routes, both enforced: **per IP** and **per account identifier** (the submitted email, hashed). An attacker rotating IPs is caught by the account dimension; one hitting many accounts from one IP is caught by the IP dimension.
- R1 limits: login 10/min and 60/hour per IP, 5/min and 20/hour per email; registration 5/hour per IP; reset request 10/hour per IP, 3/hour per email; verification resend 3/hour per account; refresh 30/min per IP.
- Failures return `429` with `Retry-After`. The response is identical for "wrong password" and "no such account" (§1 enumeration rule) and rate-limit state must not differ between them either — otherwise the limiter itself becomes the oracle.
- Behind Cloudflare, the client IP comes from `CF-Connecting-IP` and only when the request arrives from a Cloudflare address; otherwise from the socket. A spoofable `X-Forwarded-For` is never trusted.
- Redis unavailable: **fail closed** on auth routes (503), fail open on read-only routes. An unprotected login endpoint is worse than a brief outage.
- Limits are config, not literals, so they can be tuned in R2 without a deploy.

**Inputs.** Request IP, submitted identifier.

**Outputs.** `core/ratelimit.py`; `429` responses; a `rate_limited` metric by route.

**Acceptance criteria.**
- `AC-AUTH-09.1` 11 logins in a minute from one IP: the 11th returns 429 with `Retry-After`.
- `AC-AUTH-09.2` 6 logins in a minute for one email from six different IPs: the 6th returns 429.
- `AC-AUTH-09.3` Rate-limit counters increment identically for a wrong password and a nonexistent account.
- `AC-AUTH-09.4` A request carrying a forged `X-Forwarded-For` from a non-Cloudflare source is limited by its socket IP.
- `AC-AUTH-09.5` With Redis down, `POST /auth/login` returns 503 and `GET /jobs` still returns 200.
- `AC-AUTH-09.6` Every limit is read from config; no numeric literal for a limit exists in the limiter.

**Tests.**
- `T-AUTH-09.1`–`.3` `tests/integration/test_rate_limits.py`.
- `T-AUTH-09.4` `tests/integration/test_client_ip_resolution.py`.
- `T-AUTH-09.5` `tests/integration/test_ratelimit_redis_down.py`.
- `T-AUTH-09.6` `tests/spec/test_ratelimit_config.py`.
