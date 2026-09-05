# 14 — Mobile Client (Flutter)

**Module:** `apps/mobile`
**Track:** R1 (Android) except §5.2 (push, R2), §7 (offline, R2), §8 (iOS, R3)
**Depends on:** `packages/contracts/dart` (generated)
**Requirements:** `MOB-01` … `MOB-08`

Mobile is the checking device: the feed on a commute, a status change after a call, a reminder that arrives while away from the laptop. It is not where a cover letter gets written. Building it as a smaller copy of the web app would waste the phone's advantages and inherit the desktop's assumptions, so the screen set is deliberately narrower and the interactions are deliberately different.

---

## 1. Stack and structure — `MOB-01`

**Objective.** A feature-first Flutter app with generated API models and no hand-maintained duplication of the backend contract.

**Constraints.**
- Flutter 3.x stable, Dart 3, pinned via `.fvmrc`. Riverpod for state and dependency injection. `go_router` for navigation and deep links. `dio` with interceptors for auth. `freezed` + `json_serializable` for models. The API client is **generated** from `openapi.json` via `openapi-generator` (dart-dio) into `packages/contracts/dart` (`01-foundations.md` §13) — never hand-written.
- `flutter_secure_storage` for the refresh token. `flutter_local_notifications` for local prompts. `firebase_messaging` in R2.
- Structure:

```
apps/mobile/lib/
├─ app/            router, theme, bootstrap, flavors
├─ core/           network, auth, storage, errors, deep_links
├─ features/<name>/{data/, domain/, presentation/}
│                  auth onboarding profile matches job_detail apply tracker notifications settings
└─ shared/         widgets, extensions, formatters
```

- `domain/` holds entities and thin use-cases; `data/` holds repositories over the generated client; `presentation/` holds screens, widgets, and providers. A `presentation` file never imports the generated client directly.
- **No admin surface exists in this app** (`AC-ADMIN-06.3`) — nothing to gate, and nothing awkward in a store review.
- Flavors: `dev`, `staging`, `prod`, each with its own API base URL, app id, and (in R2) Firebase configuration. A build cannot be produced without a flavor.
- `flutter analyze` runs with the repo's `analysis_options.yaml` at a strict setting; warnings fail CI.

**Acceptance criteria.**
- `AC-MOB-01.1` `flutter analyze` reports zero issues at the configured strictness.
- `AC-MOB-01.2` The generated Dart client compiles and regenerating from an unchanged spec produces no diff.
- `AC-MOB-01.3` No file under `presentation/` imports the generated client.
- `AC-MOB-01.4` All three flavors build; a build without a flavor fails.
- `AC-MOB-01.5` No admin screen, route, or admin API call exists in the app.

**Tests.**
- `T-MOB-01.1` `.github/workflows/mobile-ci.yml` step `analyze`.
- `T-MOB-01.2` `.github/workflows/contracts.yml` (shared).
- `T-MOB-01.3` `apps/mobile/test/architecture_test.dart` (import check).
- `T-MOB-01.4` `mobile-ci` step `build-flavors`.
- `T-MOB-01.5` `tests/spec/test_no_admin_in_mobile.py` (shared).

---

## 2. Auth and session — `MOB-02`

**Objective.** Stay signed in across app restarts without leaving a token anywhere weak.

**Constraints.**
- Refresh token in `flutter_secure_storage` (Keystore on Android, Keychain on iOS). Access token **in memory only** — never in shared preferences, never in a file, never in a log.
- A `dio` interceptor performs **single-flight refresh** on 401, queuing concurrent failures behind one refresh, for the same reason as the web client (`13-web-client.md` §2): parallel refreshes trigger reuse detection and log the user out (`02-auth-and-account.md` §4).
- A failed refresh clears secure storage and routes to sign-in once.
- Google sign-in uses the server-side code exchange with a custom-scheme redirect; the app holds no client secret.
- Biometric re-lock is **not** in R1 — it implies a local data store worth protecting, which the app does not have until offline caching (R2).
- The app is excluded from Android cloud backup (`allowBackup=false`), so a device backup cannot carry the token off the device.

**Acceptance criteria.**
- `AC-MOB-02.1` After a cold restart the user is still signed in, and a filesystem and preferences dump contains no access token.
- `AC-MOB-02.2` Five concurrent 401s produce one refresh call.
- `AC-MOB-02.3` A failed refresh clears secure storage and routes to sign-in exactly once.
- `AC-MOB-02.4` `allowBackup` is false in the release manifest.
- `AC-MOB-02.5` No client secret is present in the APK (asserted by the artifact secret scan, `AC-AI-05.5`).

**Tests.**
- `T-MOB-02.1` `apps/mobile/integration_test/session_persistence_test.dart`.
- `T-MOB-02.2` `apps/mobile/test/refresh_single_flight_test.dart`.
- `T-MOB-02.3` `apps/mobile/test/auth_failure_test.dart`.
- `T-MOB-02.4` `apps/mobile/test/manifest_test.dart`.
- `T-MOB-02.5` `mobile-ci` step `secret-scan-artifacts` (shared).

---

## 3. Screens — `MOB-03`

**Objective.** The exit-sentence journey on a phone, with the pack flow adapted rather than shrunk.

**Constraints.** Screen set, narrower than web by design:

| Screen | Notes |
|---|---|
| **Auth** | Sign in, register, verify prompt, reset |
| **Onboarding** | Upload (file picker), review extraction, preferences. The review screen is a card-per-field flow with confirm/edit, which works better on a phone than the web's dense editor |
| **Matches feed** | Pull-to-refresh, infinite scroll, score chip, top reasons, attribution, threshold in a filter sheet |
| **Job detail** | All six explain sections (`08-matching.md` §3), actions in a bottom bar |
| **Apply sheet** | Copy chips per pack item, "Open posting" (external browser), "I applied" |
| **Tracker** | List with status sections and swipe actions; **no Kanban** — a horizontal board on a phone is worse than a grouped list, and pretending otherwise costs a week |
| **Application detail** | Timeline, notes, interviews, documents |
| **Notifications** | In-app inbox with deep links |
| **Settings** | Preferences, notification prefs, account, deletion |

- **Pack editing is deliberately limited on mobile**: the user can read the pack, copy items, and make short edits, but the full editor with fabrication-flag resolution is a web experience. If a pack has open fabrication flags, the mobile app says so plainly and offers "finish on desktop" with a deep link rather than an inadequate editor. Approving a pack with unresolved flags is impossible on either client (`AC-APPLY-03.2`).
- Resume upload runs in the background with a completion notification; the user can leave the screen.
- Every screen has loading (skeleton), empty (next action), and error (cause plus retry) states.
- Optimistic status changes with rollback and a snackbar on failure.
- Deep links resolve from the same shared table as web (`AC-NOTIF-02.4`).

**Acceptance criteria.**
- `AC-MOB-03.1` Every screen has tests for loading, empty, error, and populated states.
- `AC-MOB-03.2` The job detail renders all six explain sections from a fixture payload offline.
- `AC-MOB-03.3` A pack with open fabrication flags shows the "finish on desktop" path and no approve action.
- `AC-MOB-03.4` Resume upload completes with the app backgrounded and posts a local notification.
- `AC-MOB-03.5` "Open posting" launches the external browser, never an in-app webview (`AC-APPLY-05.4` shared).
- `AC-MOB-03.6` Every deep link opens the equivalent screen to the web route.
- `AC-MOB-03.7` A failed optimistic status change reverts with a snackbar.

**Tests.**
- `T-MOB-03.1` `apps/mobile/test/features/**/*_states_test.dart`.
- `T-MOB-03.2` `apps/mobile/test/match_explain_test.dart` (shared).
- `T-MOB-03.3` `apps/mobile/test/pack_gate_test.dart`.
- `T-MOB-03.4` `apps/mobile/integration_test/background_upload_test.dart`.
- `T-MOB-03.5` `apps/mobile/test/apply_sheet_test.dart` (shared).
- `T-MOB-03.6` `apps/mobile/test/deep_links_test.dart`.
- `T-MOB-03.7` `apps/mobile/test/tracker_card_test.dart` (shared).

---

## 4. Files and permissions — `MOB-04`

**Objective.** Ask for as little as possible, as late as possible.

**Constraints.**
- **The Android manifest is audited and minimal.** Transitive libraries routinely pull in permissions nobody asked for (badge providers, install referrers, boot receivers). The permission list is reviewed on every dependency change, each remaining entry has a written justification in `apps/mobile/PERMISSIONS.md`, and CI fails on an undeclared addition. R1 target: internet plus notifications, nothing more.
- File picking uses the system picker with type filters, requiring no storage permission on modern Android.
- Notification permission (Android 13+) is requested **contextually** — after the user's first application, when a reminder is about to become useful — never at launch. A launch-time prompt is how permission gets denied permanently, and a denied notification permission removes the last clause of the exit sentence.
- The permission rationale text explains what will be sent and when, and a denial is handled gracefully: reminders continue by email and the in-app inbox, and the app says so rather than silently doing nothing.
- No analytics SDK, no advertising SDK, no third-party telemetry in R1. Sentry only, with the redaction rules of `01-foundations.md` §14.

**Acceptance criteria.**
- `AC-MOB-04.1` The release manifest contains only justified permissions; each has an entry in `PERMISSIONS.md`.
- `AC-MOB-04.2` CI fails when a dependency introduces a new permission without a justification entry.
- `AC-MOB-04.3` No notification prompt appears before the first application is confirmed.
- `AC-MOB-04.4` Denying notifications leaves reminders working by email and in-app, with an in-app explanation.
- `AC-MOB-04.5` The APK contains no analytics or advertising SDK (dependency scan).

**Tests.**
- `T-MOB-04.1`/`.2` `mobile-ci` step `permission-audit` + `apps/mobile/test/manifest_test.dart`.
- `T-MOB-04.3` `apps/mobile/integration_test/permission_timing_test.dart`.
- `T-MOB-04.4` `apps/mobile/test/notification_denied_test.dart`.
- `T-MOB-04.5` `mobile-ci` step `sdk-scan`.

---

## 5. Notifications — `MOB-05`

### 5.1 Local notifications — **R1**

Background-upload completion and the 10-minute "did you apply?" prompt (`09-apply.md` §5). Scheduled locally, cancelled when the app observes the corresponding state change, so a user who confirms in the app does not get asked again.

### 5.2 Push (FCM) — `NOTIF-02b` — **Track: R2**

Token registered after the first application, stored in `devices`, invalidated on failure (`11-notifications.md` §4.2). Payload carries a deep link and no content beyond title and company. Foreground, background, and terminated states all route to the same screen — the terminated case is the one that gets skipped and the one users notice.

**Acceptance criteria.**
- `AC-MOB-05.1` The upload-completion notification fires when the app is backgrounded and not when it is foregrounded and already showing the result.
- `AC-MOB-05.2` The "did you apply?" prompt is cancelled when the user confirms in-app first.
- `AC-MOB-05.3` (R2) A push received in the foreground, the background, and from a terminated state each opens the correct screen.
- `AC-MOB-05.4` (R2) An invalid token is invalidated server-side on the first failure.

**Tests.**
- `T-MOB-05.1`/`.2` `apps/mobile/integration_test/local_notifications_test.dart`.
- `T-MOB-05.3` `apps/mobile/integration_test/push_routing_test.dart` (R2).
- `T-MOB-05.4` `tests/integration/test_fcm_token_lifecycle.py` (shared, R2).

---

## 6. Performance and quality on real devices — `MOB-06`

**Objective.** Usable on a mid-range Android phone on a slow connection, which is the actual target device.

**Constraints.**
- Budgets, measured on a mid-range profile: cold start to first frame under 2 s; feed scroll with no frame over 16 ms in the profiling run; APK under 30 MB (R1, before OCR or Firebase); memory under 200 MB on the feed.
- Lists are lazily built (`ListView.builder`), images cached and sized, and the feed's card widget is `const`-constructible where possible.
- No blocking work on the UI isolate: JSON decoding of a large feed page happens in an isolate.
- Text scales with the OS setting up to 200% without clipping — a layout that breaks at large text is a layout that excludes people.
- Semantic labels on every interactive widget; the app is navigable with TalkBack for the exit-sentence journey.

**Acceptance criteria.**
- `AC-MOB-06.1` Cold start under 2 s on the reference device profile.
- `AC-MOB-06.2` No dropped frames beyond the threshold in the feed-scroll profiling test.
- `AC-MOB-06.3` Release APK under 30 MB.
- `AC-MOB-06.4` Every screen renders correctly at 200% text scale (golden tests at two scales).
- `AC-MOB-06.5` The exit-sentence journey is completable with TalkBack.

**Tests.**
- `T-MOB-06.1`/`.2` `apps/mobile/integration_test/perf_test.dart`.
- `T-MOB-06.3` `mobile-ci` step `apk-size`.
- `T-MOB-06.4` `apps/mobile/test/golden/*_test.dart`.
- `T-MOB-06.5` `apps/mobile/integration_test/a11y_test.dart`.

---

## 7. Offline cache — `MOB-07` — **Track: R2**

**Objective.** A commute with no signal still shows the feed and the tracker.

**Constraints.** Read-only cache of the last feed page and the tracker list in a local store (`drift` or `hive`), with an explicit "last updated" timestamp shown to the user — a stale list presented as current is worse than an empty one. **Mutations are never queued offline**: a status change or an approval made offline and replayed later against changed server state produces surprises, so offline mutations are refused with a clear message. Introducing a local store also introduces something worth protecting, which is when biometric re-lock becomes worth considering.

**Acceptance criteria.** `AC-MOB-07.1` The feed and tracker render offline with a visible "last updated" time. `AC-MOB-07.2` Mutations offline are refused with a message and no local state change. `AC-MOB-07.3` The cache is cleared on sign-out and on account deletion. `AC-MOB-07.4` The cache holds no pack content and no resume text.
**Tests.** `T-MOB-07.1`–`.4` `apps/mobile/integration_test/offline_test.dart`.

---

## 8. Release — `MOB-08`

**Objective.** An installable build in testers' hands, and a store listing that does not misdescribe the product.

**Constraints.**
- R1 ships **Android only** (D8). `mobile-release` on a `mobile-v*` tag builds a signed AAB and uploads to Play Internal Testing.
- The signing key lives outside the repo; its certificate fingerprint is recorded in `docs/runbooks/mobile-release.md` and **asserted identical on every release** — a changed signing identity is discovered either in a pull request or by a user whose update refuses to install, and the first is better.
- Store listing constraints that follow from HR-1: the description must not claim the app applies to jobs on the user's behalf, auto-applies, or submits applications. It says "assisted" and means it. Screenshots must not show a submission the app does not perform. A Play policy question about automation is answered by the honest description, and the extension (R3) will need its own review of these claims.
- Data-safety declaration matches reality: what is collected (email, resume content, application data), what is shared (resume and job text with the AI provider), retention, and deletion. It is generated from the same source as the consent copy (`16-security-and-compliance.md` §4) so the two cannot drift.
- Version code is derived from the tag; a duplicate upload fails rather than silently replacing.
- iOS (R3) needs a Mac and a paid account; nothing in the codebase may become Android-only in a way that blocks it, and `mobile-ci` builds for iOS as an analysis target from the start.

**Acceptance criteria.**
- `AC-MOB-08.1` A `mobile-v*` tag produces a signed AAB in Play Internal Testing.
- `AC-MOB-08.2` The signing certificate fingerprint matches the recorded value; a mismatch fails the release.
- `AC-MOB-08.3` The store description contains none of the prohibited automation claims (a wordlist check on the listing file in the repo).
- `AC-MOB-08.4` The data-safety declaration is generated from the consent source and matches it.
- `AC-MOB-08.5` The full exit-sentence journey passes on a physical Android device (the R1 gate's mobile evidence).
- `AC-MOB-08.6` The iOS target still compiles.

**Tests.**
- `T-MOB-08.1`/`.2` `.github/workflows/mobile-release.yml`.
- `T-MOB-08.3` `tests/spec/test_store_listing_claims.py`.
- `T-MOB-08.4` `tests/spec/test_data_safety_parity.py`.
- `T-MOB-08.5` `apps/mobile/integration_test/exit_sentence_test.dart`.
- `T-MOB-08.6` `mobile-ci` step `ios-analyze`.
