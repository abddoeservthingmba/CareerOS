# 13 — Web Client (React + TypeScript)

**Module:** `apps/web`
**Track:** R1 except §7 (the accessibility audit, R2) and features marked R2/R3 elsewhere
**Depends on:** `packages/contracts/ts` (generated), every API module's contract
**Requirements:** `WEB-01` … `WEB-08`

The web client is where applying actually happens — a desktop with two tabs open, the posting in one and the pack in the other. Mobile is where checking happens. That difference drives every layout decision here.

---

## 1. Stack and structure — `WEB-01`

**Objective.** A typed client that cannot disagree with the server, and a directory layout where a feature's code is in one place.

**Constraints.**
- Vite, React 19, TypeScript in `strict` mode with `noUncheckedIndexedAccess`. React Router v7. TanStack Query for all server state. Zustand for the small amount of genuine UI state (panel open, board filters). React Hook Form + Zod for forms. Tailwind with a small primitive layer (Radix under the hood). Vitest + Testing Library, Playwright for end-to-end, MSW for API mocking.
- **The API client is generated**, not written: `openapi-typescript` types plus `openapi-fetch`, from `packages/contracts/openapi.json` (`01-foundations.md` §13). A hand-written fetch call to an API route fails a lint rule. Response types are never re-declared by hand.
- Zod schemas in the client validate **forms**, not API responses — the generated types are the contract for responses, and duplicating them as runtime schemas is two sources of truth.
- `any` is banned (lint error). `unknown` plus a narrow is the escape hatch.
- Structure:

```
apps/web/src/
├─ app/            providers, router, layouts, error boundaries
├─ features/<name>/{api.ts, components/, hooks/, pages/, schemas.ts}
│                  auth profile resume jobs matches apply tracker notifications settings admin
├─ components/ui/  primitives: Button Input Select Dialog Sheet Chip Card Skeleton Toast
├─ lib/            api client, sse, auth store, formatting, deep links
└─ styles/
```

- A feature never imports another feature's internals; shared pieces move to `components/ui` or `lib`. Enforced by an ESLint import-boundary rule mirroring the backend's contracts (`01-foundations.md` §4).
- Route-level code splitting on every page. The admin route group is a separate lazy chunk containing no product code and, crucially, no admin code in the product chunks (`AC-ADMIN-06.2`).

**Acceptance criteria.**
- `AC-WEB-01.1` `tsc --noEmit` passes in strict mode with `noUncheckedIndexedAccess`; `any` appears nowhere outside generated files.
- `AC-WEB-01.2` A hand-written `fetch` to an `/api/` path fails lint; every API call goes through the generated client.
- `AC-WEB-01.3` Regenerating the client from an unchanged OpenAPI document produces no diff.
- `AC-WEB-01.4` The import-boundary rule fails on a cross-feature internal import.
- `AC-WEB-01.5` Every page is a lazy route; the initial bundle is under 250 KB gzipped excluding fonts.
- `AC-WEB-01.6` No admin component appears in any non-admin chunk.

**Tests.**
- `T-WEB-01.1`/`.2`/`.4` `apps/web` ESLint and `tsc` in `web-ci`.
- `T-WEB-01.3` `.github/workflows/contracts.yml` (shared).
- `T-WEB-01.5` `apps/web/scripts/check-bundle-size.mjs`.
- `T-WEB-01.6` `apps/web/scripts/check-admin-chunk.mjs` (shared with `T-ADMIN-06.2`).

---

## 2. Auth handling — `WEB-02`

**Objective.** Session handling that survives a refresh, a reload, and two tabs, without ever putting a token where a script can read it.

**Constraints.**
- Access token **in memory only**. Never `localStorage`, never `sessionStorage`, never a non-httpOnly cookie. A reload therefore starts with no access token and silently refreshes from the httpOnly cookie.
- **Single-flight refresh**: a 401 triggers one refresh; concurrent 401s wait on the same promise and then retry. Without this, five parallel queries on a stale token produce five refreshes, four of which are reuse-detected and revoke the family (`02-auth-and-account.md` §4) — logging the user out for doing nothing wrong. This is the single most important line in this file.
- A failed refresh clears state and routes to login **once**, without a redirect loop, preserving the intended destination.
- CSRF: because refresh uses a cookie, every state-changing request carries the double-submit token (`16-security-and-compliance.md` §2).
- Two tabs share the cookie; a logout in one broadcasts over `BroadcastChannel` so the other clears its in-memory token rather than discovering it on the next 401.
- The Google sign-in flow uses PKCE with the code exchanged server-side; the client holds no secret.

**Acceptance criteria.**
- `AC-WEB-02.1` No token appears in `localStorage`, `sessionStorage`, or a readable cookie at any point (asserted in an end-to-end test that inspects storage after login, refresh, and reload).
- `AC-WEB-02.2` Five concurrent requests on an expired access token produce exactly one refresh call and five successful retries.
- `AC-WEB-02.3` A failed refresh routes to login once, with no loop, and returns to the intended page after re-login.
- `AC-WEB-02.4` Every mutating request carries the CSRF token; one without it is rejected by the API.
- `AC-WEB-02.5` Logging out in one tab clears the other tab's session without a network round trip.

**Tests.**
- `T-WEB-02.1` `apps/web/e2e/auth-storage.spec.ts`.
- `T-WEB-02.2` `apps/web/src/lib/__tests__/refresh-single-flight.test.ts`.
- `T-WEB-02.3` `apps/web/e2e/auth-redirect.spec.ts`.
- `T-WEB-02.4` `apps/web/src/lib/__tests__/csrf.test.ts`.
- `T-WEB-02.5` `apps/web/e2e/multi-tab-logout.spec.ts`.

---

## 3. Screens — `WEB-03`

**Objective.** Nine screens that cover the R1 exit sentence, each with its loading, empty, and error state specified rather than improvised.

**Constraints.** Every screen below has all four states designed and tested: **loading** (skeleton matching the eventual layout, never a spinner on a full page), **empty** (what to do next, not "no data"), **error** (what failed and a retry), **populated**.

| Screen | Purpose | Notes that matter |
|---|---|---|
| **Onboarding wizard** | Sign up → verify → upload → review → preferences | Progress is resumable: a user who closes the tab mid-upload returns to the same step. The review step is the product's first impression and shows evidence per extracted field (`03-profile.md` §2) |
| **Matches feed** | Scored jobs, score chip, top three reasons, filters, threshold slider | Infinite scroll on the cursor. The threshold slider re-queries, never rescores. Cards show attribution (`06-connectors.md` §4) |
| **Job detail** | Full explain payload, actions | Renders all six explain sections (`08-matching.md` §3) from the stored payload with no second request |
| **Profile editor** | Sections, per-field confirm, confidence flags | Unconfirmed fields are visually distinct and confirmable inline and in bulk |
| **Answer Bank** | Q&A list, tags, suggest | Sensitive questions marked and never suggested (`09-apply.md` §1) |
| **Apply panel** | Pack editor, fabrication flags, approve, copy panel | The copy panel is a persistent side panel, not a modal — the user is switching between two tabs and a modal blocks the rest of the app |
| **Tracker** | Kanban, list, (R2) calendar | Optimistic drag with revert on failure |
| **Application detail** | Timeline, notes, contacts, documents, interviews, salary | Notes rendered with the scheme allowlist (`10-tracker.md` §4) |
| **Settings** | Preferences, notifications, data, danger zone | Deletion requires typing the word, shows exactly what will be deleted and when |
| **Admin** | Separate route group | `12-admin.md`; separate chunk |

- Long operations (resume processing, pack generation) use the SSE hook with a **polling fallback** (`01-foundations.md` §11), and the fallback is exercised in tests, not assumed.
- Optimistic updates for: shortlist/save, hide, status transition, mark-as-read. Each with a defined rollback and a toast on failure.
- Every destructive action has a confirmation naming what it affects. Deletion of an account requires typing a word.

**Acceptance criteria.**
- `AC-WEB-03.1` Every screen in the table has tests for all four states.
- `AC-WEB-03.2` Onboarding resumes at the correct step after a reload at each step.
- `AC-WEB-03.3` The job detail view renders every explain section from a fixture payload with the network disabled (`AC-MATCH-02.2` shared).
- `AC-WEB-03.4` The threshold slider changes the feed with no scoring request issued.
- `AC-WEB-03.5` Each optimistic action rolls back and shows a toast when the API rejects it.
- `AC-WEB-03.6` The apply copy panel remains usable while the posting is open in another tab (it is not a modal and does not block navigation).
- `AC-WEB-03.7` Account deletion requires the typed confirmation and displays the 7-day clock and the data categories.
- `AC-WEB-03.8` Both long operations complete with SSE blocked.

**Tests.**
- `T-WEB-03.1` `apps/web/src/features/**/__tests__/*.states.test.tsx`.
- `T-WEB-03.2` `apps/web/e2e/onboarding-resume.spec.ts`.
- `T-WEB-03.3` `apps/web/.../match-explain.test.tsx` (shared).
- `T-WEB-03.4` `apps/web/.../threshold.test.tsx`.
- `T-WEB-03.5` `apps/web/.../optimistic.test.tsx`.
- `T-WEB-03.6` `apps/web/.../apply-panel.test.tsx` (shared).
- `T-WEB-03.7` `apps/web/e2e/account-deletion.spec.ts`.
- `T-WEB-03.8` `apps/web/e2e/sse-fallback.spec.ts`.

---

## 4. AI labelling and untrusted content — `WEB-04`, HR-9, HR-11

**Objective.** The user always knows which words a machine wrote, and no content from a job posting can execute.

**Constraints.**
- One `<AiBadge>` component, used on every AI-generated artifact: extraction results before confirmation, match rationale, pack items not yet edited, quality feedback, answer suggestions, follow-up drafts. An item with `edited_by_user: true` loses the badge — the user wrote it.
- A generated artifact is never rendered without either the badge or a user-edited marker. Enforced by a lint rule on the components that render generated fields.
- **All external and model-produced text is escaped.** `dangerouslySetInnerHTML` is banned by lint with exactly one allowed call site: the sanitized job description (`description_html_sanitized`, server-sanitized by allowlist, `07-ingestion-and-jobs.md` §1), and even there the client re-sanitizes with DOMPurify as a second layer.
- A URL that came from a model is rendered as text, never as an anchor (HR-11, `AC-AI-06.5`).
- User markdown (notes) uses the scheme allowlist renderer; an unknown scheme degrades to text.
- CSP is set by the host and is strict: no inline script, no `eval`, connect only to the API origin and the allowed CDNs. Any construct requiring `unsafe-inline` is a design error to be fixed rather than allowed.

**Acceptance criteria.**
- `AC-WEB-04.1` Every component rendering a generated field renders `<AiBadge>` unless `edited_by_user`; a lint rule and a component test cover each.
- `AC-WEB-04.2` `dangerouslySetInnerHTML` appears at exactly one call site, and that site passes its input through DOMPurify.
- `AC-WEB-04.3` A job description containing a script tag, an event handler, an `iframe`, and a `javascript:` link renders inert.
- `AC-WEB-04.4` A model-produced URL renders as text with no `href`.
- `AC-WEB-04.5` The app runs with no CSP violation under the production policy (checked in an end-to-end run that fails on any violation report).

**Tests.**
- `T-WEB-04.1` `apps/web/.../ai-label.test.tsx` (shared) + ESLint rule.
- `T-WEB-04.2` ESLint `react/no-danger` with a single documented override, checked by `apps/web/scripts/check-danger-sites.mjs`.
- `T-WEB-04.3` `apps/web/.../job-description.test.tsx`.
- `T-WEB-04.4` `apps/web/.../ai-content.test.tsx` (shared).
- `T-WEB-04.5` `apps/web/e2e/csp.spec.ts`.

---

## 5. Performance — `WEB-05`

**Objective.** The feed feels instant on a mid-range laptop and acceptable on a phone browser.

**Constraints.**
- Budgets: initial JS under 250 KB gzipped; LCP under 2.5 s and CLS under 0.1 on a simulated Fast 3G / 4× CPU throttle; a feed of 50 cards renders in under 100 ms after data arrives.
- Feed cards are memoized and the list is virtualized above 100 items. Images (company logos) are lazy, sized to prevent layout shift, and fall back to a generated initial-avatar — a missing logo must never shift the layout or leave a hole.
- TanStack Query settings are explicit per query rather than global guesses: the feed and search are `staleTime` 60 s; profile and settings 5 min; tracker 30 s; notifications 0 with SSE invalidation.
- No waterfall on any screen: a page's queries are issued in parallel from the route loader, not nested inside child components.
- Fonts are self-hosted and preloaded with `font-display: swap`.

**Acceptance criteria.**
- `AC-WEB-05.1` The bundle budget holds in CI (`AC-WEB-01.5` shared).
- `AC-WEB-05.2` Lighthouse under throttling meets the LCP and CLS budgets on the feed and the tracker.
- `AC-WEB-05.3` No screen issues a dependent request that could have been parallel (asserted by counting request waterfalls in an end-to-end trace).
- `AC-WEB-05.4` A missing logo causes zero layout shift.
- `AC-WEB-05.5` A 500-item tracker list virtualizes and scrolls at 60 fps in the profiling test.

**Tests.**
- `T-WEB-05.1` `apps/web/scripts/check-bundle-size.mjs` (shared).
- `T-WEB-05.2` `.github/workflows/web-ci.yml` step `lighthouse`.
- `T-WEB-05.3` `apps/web/e2e/waterfall.spec.ts`.
- `T-WEB-05.4` `apps/web/.../logo-fallback.test.tsx`.
- `T-WEB-05.5` `apps/web/e2e/virtualization.spec.ts`.

---

## 6. Error handling and observability — `WEB-06`

**Objective.** A failure shows the user something true and gives you enough to debug it.

**Constraints.**
- Error boundaries per route group, not one at the root — a broken tracker must not blank the whole app.
- The API's `problem+json` `code` (`01-foundations.md` §12) drives the message. A copy table maps every `ErrorCode` to user-facing text; an unmapped code falls back to a generic message **and reports itself**, so the gap is discovered.
- The `request_id` from the response is shown in the error UI and included in the Sentry report, so a user's screenshot is traceable to a log line.
- Sentry with `before_send` redaction matching the backend's rules (`01-foundations.md` §14): no email, no token, no pack content, no resume text, no job description.
- Offline detection: a banner, queries paused, and mutations refused with a clear message rather than optimistically applied and lost.

**Acceptance criteria.**
- `AC-WEB-06.1` A thrown error in one route group leaves the rest of the app navigable.
- `AC-WEB-06.2` Every `ErrorCode` has copy; an unmapped code renders the fallback and reports it (a test enumerates the enum from the generated types).
- `AC-WEB-06.3` The error UI shows `request_id` and Sentry carries the same value.
- `AC-WEB-06.4` A Sentry payload from a session containing a resume and a pack contains none of their text.
- `AC-WEB-06.5` Offline mutations are refused with a message and no optimistic state is left behind.

**Tests.**
- `T-WEB-06.1` `apps/web/.../error-boundary.test.tsx`.
- `T-WEB-06.2` `apps/web/src/lib/__tests__/error-copy.test.ts`.
- `T-WEB-06.3` `apps/web/e2e/error-request-id.spec.ts`.
- `T-WEB-06.4` `apps/web/src/lib/__tests__/sentry-redaction.test.ts`.
- `T-WEB-06.5` `apps/web/e2e/offline.spec.ts`.

---

## 7. Accessibility — `WEB-07` — **build to it in R1, audit in R2**

**Objective.** WCAG 2.1 AA, which is also the cheapest way to get the keyboard interactions right.

**Constraints.**
- R1 builds to the conventions: semantic landmarks; one `h1` per page and a correct heading order; every form control labelled; visible focus on every interactive element; a skip-to-content link; `aria-live` for async status (the resume stages, toasts); a keyboard path for **every** action, including the Kanban drag (arrow-key move with an explicit "move to" menu — a drag-only board is unusable without a mouse); dialogs and the apply panel trap and restore focus; colour contrast at 4.5:1 for text and 3:1 for UI, measured rather than eyeballed; `prefers-reduced-motion` honoured.
- Score, band, and fabrication flags must not rely on colour alone — each carries a label or an icon.
- R2 runs the audit: axe in CI on every page state, a manual keyboard pass, and a screen-reader pass on the four screens of the exit sentence.

**Acceptance criteria.**
- `AC-WEB-07.1` axe reports zero critical or serious violations on every screen in all four states.
- `AC-WEB-07.2` Every action in the exit sentence is completable with the keyboard alone, including moving a Kanban card.
- `AC-WEB-07.3` Contrast is verified programmatically for every token pair in use.
- `AC-WEB-07.4` Score bands and fabrication flags are distinguishable without colour.
- `AC-WEB-07.5` Async status changes are announced via `aria-live`.
- `AC-WEB-07.6` (R2) The screen-reader pass is recorded with findings and fixes in `docs/runbooks/a11y-audit.md`.

**Tests.**
- `T-WEB-07.1` `apps/web/e2e/a11y.spec.ts` (axe integration).
- `T-WEB-07.2` `apps/web/e2e/keyboard-journey.spec.ts`.
- `T-WEB-07.3` `apps/web/src/styles/__tests__/contrast.test.ts`.
- `T-WEB-07.4` `apps/web/.../non-color-indicators.test.tsx`.
- `T-WEB-07.5` `apps/web/.../live-region.test.tsx`.
- `T-WEB-07.6` `tests/spec/test_a11y_audit_doc.py` (R2).

---

## 8. End-to-end coverage — `WEB-08`

**Objective.** One Playwright run that is the R1 gate's web evidence.

**Constraints.**
- The exit-sentence journey as a single spec against a seeded backend with the fake AI provider: sign up → verify (via the mail catcher) → upload → review and correct → preferences → feed with ≥50 scored jobs → shortlist 5 → generate pack → edit → approve → open posting (intercepted) → confirm applied → assert the follow-up reminder row and the in-app notification.
- Runs against `docker compose` in CI with real Mongo and Redis, the fake AI provider, recorded connector fixtures, and mailpit. No live external call (`AC-CONN-06.5`).
- Also specified: the cross-tenant check from the browser (a second user cannot see the first's application by URL), the SSE-blocked run, and the CSP run.
- Deterministic: seeded data, frozen clock where timing matters, no `sleep`-based waits.

**Acceptance criteria.**
- `AC-WEB-08.1` The exit-sentence spec passes headless in CI and is the R1 gate's web evidence.
- `AC-WEB-08.2` The suite makes no request to any external host (asserted by a request interceptor that fails the run).
- `AC-WEB-08.3` Navigating directly to another user's application URL shows a not-found page.
- `AC-WEB-08.4` The suite is deterministic: 20 consecutive runs with no flake.
- `AC-WEB-08.5` No spec contains a fixed-duration wait.

**Tests.**
- `T-WEB-08.1` `apps/web/e2e/exit-sentence.spec.ts`.
- `T-WEB-08.2` `apps/web/e2e/fixtures/no-external.ts`.
- `T-WEB-08.3` `apps/web/e2e/cross-tenant.spec.ts`.
- `T-WEB-08.4` `.github/workflows/web-ci.yml` step `e2e-repeat` (nightly, 20 runs).
- `T-WEB-08.5` `apps/web/scripts/check-no-sleep.mjs`.
