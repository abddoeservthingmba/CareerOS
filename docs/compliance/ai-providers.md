# AI providers — procurement and data-use statement

**Requirement:** `AC-AI-05.1` — "`docs/compliance/ai-providers.md` exists, states
the dedicated Cloud project and billing account, names the budget-alert
threshold, and carries a review date within 90 days. (R1 gate: signed
statement.)"

**Verified by:** `tests/spec/test_compliance_docs.py`. The test checks that this
document exists, has every required heading, carries a review date inside the
window, and that no field is still `UNFILLED`. It cannot check whether the
statements are *true* — `05-ai-layer.md` §5.2 says so directly: "This is a
manual control with a documented owner; the code cannot verify it, so the gate
item is a signed statement, not a test."

> **STATUS: NOT YET SIGNED.** Every `UNFILLED` below is a fact only the owner
> can supply. The test fails while any remain, which is deliberate: an unsigned
> statement should block the R1 gate rather than sit here looking official.

---

## 1. Provider inventory

| Provider | Role | State | Credential |
|---|---|---|---|
| Gemini (Developer API) | R1 production default | configured | `GEMINI_API_KEY` — a Developer API key string, injected at construction |
| Ollama | local development (ADR-011) | configured | **none** — runs on the developer's own machine |
| Fake | every test, and local development with no model | built-in | none |
| OpenAI | stub | not configured | — |
| Anthropic | stub | not configured | — |

Ollama needs no entry in the sections below. It has no credential, no billing
account and no third-party data transfer: prompts do not leave the machine. That
is the whole reason ADR-011 promoted it.

---

## 2. The dedicated Cloud project

`05-ai-layer.md` §5.2, the procurement rule:

> the key belongs to a Cloud project created solely for this product, with its
> own billing account, and a project-level budget alert set at twice
> `AI_DAILY_COST_CAP_USD` × 30. The project has no other API enabled.

The rule is not bureaucracy. §5.1 gives the reason: "An API key created inside a
Cloud project that shares a billing account with other personal work makes
JobPilot's spend indistinguishable from everything else, which defeats the cost
tracking in §4 and makes a spend alert unactionable." Every mechanism in `AI-03`
and `AI-04` — the daily caps, the per-feature attribution, the dashboard, the
unpriced-model alert — is downstream of being able to say what this product
spent. A shared billing account makes all of it approximate.

| Field | Value |
|---|---|
| Cloud project name | `UNFILLED` |
| Cloud project id | `UNFILLED` |
| Billing account (label, not the number) | `UNFILLED` |
| Billing account is used by this product only | `UNFILLED` (yes / no) |
| Other APIs enabled in the project | `UNFILLED` (expected: none) |
| Owner accountable for this control | `UNFILLED` |

### Budget alert

`AI_DAILY_COST_CAP_USD` is currently **2.00**, so the required project-level
alert threshold is **2 × 2.00 × 30 = $120.00 per month**.

| Field | Value |
|---|---|
| Alert threshold configured | `UNFILLED` (expected: $120.00/month) |
| Alert recipients | `UNFILLED` |
| Date the alert was verified to fire | `UNFILLED` |

The alert is a backstop, not the primary control. The primary control is
`AI-03`'s in-application cap, which refuses a call *before* the provider is
contacted. The project alert exists because an in-application cap cannot catch
spend the application did not make — a key leaked into a client bundle, for
instance, which `AC-AI-05.5` is separately guarding against.

---

## 3. Credential isolation (HR-6)

Not a manual control — this part is enforced in code and asserted by test. It is
recorded here because a reader of this document is asking "can a user's Google
sign-in reach an inference call", and the answer should be in one place.

| Control | Where | Test |
|---|---|---|
| The adapter accepts one credential type: an API key string | `app/ai/gemini.py` | `T-AI-05.4` `test_gemini_credential_surface.py` |
| No attribute or parameter can hold a token, credentials object, or service-account path | `app/ai/gemini.py` | `T-AI-05.4` |
| Nothing in `ai/` reads `os.environ` | `app/ai/*` | `T-AI-05.4` |
| Boot fails when `gemini` is selected and the key is unset | `assert_configuration` | `T-AI-05.2` |
| Boot fails when `GOOGLE_APPLICATION_CREDENTIALS` is present at all | `assert_configuration` | `T-AI-05.2` |
| `ai/*` imports no OAuth or Google-auth library | `.importlinter` `no-oauth-in-ai` | `T-AI-05.3` |
| The base URL is validated against a host allowlist | `check_base_url` | `T-AI-05.7` |

The `GOOGLE_APPLICATION_CREDENTIALS` guard refuses the boot on the variable's
*presence*, not its use. That is intentional and worth stating: an ambient
Google credential in the process is a credential the AI path could find, and
"nothing currently reads it" is a property of today's code rather than of the
system.

---

## 4. Data sent to a provider, and what may be done with it

### What is sent

`16-security-and-compliance.md` §3's list, which the consent screen must match
(`AC-SEC-04.4`):

- resume **text** — never the file (HR-8: "file bytes never leave");
- job description **text** from a public listing;
- the user's stated preferences, where a feature needs them;
- nothing else. No email address, no name where it can be avoided, no
  identifier beyond what the prompt genuinely requires.

### D5 — the tier, and what its terms permit

`05-ai-layer.md` §5.4 requires one choice before public sign-up. **The choice
recorded here is the free tier, disclosed.**

| Field | Value |
|---|---|
| Tier in force | **free** |
| Decided on | 2026-09-07 |
| Provider's stated data use | Free tier: content **is** used to improve Google's products. Paid tier: content is **not**. |
| Source | <https://ai.google.dev/gemini-api/docs/pricing>, read 2026-09-07 |
| Consent copy matching this tier | `app/core/consent.py`, `AI_DATA_USE_FREE_TIER` |
| Asserted by | `T-AI-05.8` `test_consent_matches_tier.py` |

§5.4 is explicit about the one unacceptable outcome: "What is **not** acceptable
is a consent text that implies the first while running the second."
`AC-AI-05.8` is what stops that from happening by accident — the copy and the
configured tier are read from the same place and compared.

**Consequence to be clear about.** On the free tier, résumé text and job
descriptions that users paste into this product may be used by Google to improve
their services. That is a real transfer of real people's employment history to a
third party for their own purposes. It is permitted by §5.4 *only* with the
disclosure above the fold, in plain language, before consent — not in a linked
policy. Switching to the paid tier changes one environment variable and one copy
key.

**During development this is avoided entirely.** ADR-011 promotes Ollama as the
local-development provider precisely so that prompt iteration and the ten-résumé
golden set (`AC-AI-07.5`) can run with no text leaving the machine.

| Field | Value |
|---|---|
| Date the tier must be settled for public sign-up | before the first non-developer account |
| Decision owner | `UNFILLED` |

---

## 5. Model identifiers and prices

§5.2: "Model names and free-tier limits are verified against Gemini's
documentation at implementation time and recorded with a date. Any figure in
this specification about a provider's limits is indicative and must not be
hard-coded."

| Role | Model id | Input / 1M | Output / 1M |
|---|---|---|---|
| `fast` | `gemini-3.5-flash-lite` | $0.30 | $2.50 |
| `quality` | `gemini-3.8-flash` | $0.75 † | $3.75 † |
| embedding | `gemini-embedding-001` | $0.15 | — |

† Introductory rate through 2026-12-31; **$1.50 / $7.50 from 2027-01-01**. The
table in `app/ai/model-pricing.yaml` carries the change date and applies it
automatically, so the dashboard does not silently report half the real cost from
that morning onward.

- **Verified on:** 2026-09-07, against <https://ai.google.dev/gemini-api/docs/pricing>
- **Prices live in:** `app/ai/model-pricing.yaml` — a data file, because
  `AC-AI-02.2` forbids a model id as a `.py` literal and because a provider
  changes prices on their schedule, not on ours
- **Staleness check:** `tests/ai/test_unpriced_model.py` fails when a
  verification is more than 90 days old

`gemini-2.5-pro` and `gemini-3.1-pro-preview` are deliberately **unpriced**: the
provider bills them by prompt length, and one flat number would be wrong for
every prompt over 200k tokens. An unpriced model records `est_cost_usd: null`
and alerts (`AC-AI-04.3`) rather than recording a wrong number that looks
authoritative.

Free-tier rate limits are **not recorded here**, because Google no longer
publishes them as fixed figures — the documentation directs you to AI Studio for
your own project's limits. `AI-03`'s token bucket is configured from
`AI_PROVIDER_RPM` for that reason: the limit is a per-project fact, so it is
configuration rather than a constant.

---

## 6. Review

| Field | Value |
|---|---|
| Last reviewed | 2026-09-08 |
| Next review due | 2026-12-07 |
| Reviewed by | `UNFILLED` |

`AC-AI-05.1` requires a review date within 90 days. The window is the same one
the price verification uses, so the two go stale together and are refreshed in
one sitting.

### What a review checks

1. Model ids still exist and the prices still match the provider's page.
2. The tier in force still matches the consent copy (`T-AI-05.8` asserts this
   continuously; the review is for the *copy* still being honest, which no test
   can judge).
3. The budget alert still exists and its threshold still equals
   2 × `AI_DAILY_COST_CAP_USD` × 30.
4. The Cloud project still has no other API enabled.
5. No provider has been added to `LLM_FACTORIES` without an entry in §1.

---

## Signature

By signing, the owner states that §2's procurement facts are true as written,
that the budget alert exists at the stated threshold, and that the tier recorded
in §4 is the tier actually configured.

| Field | Value |
|---|---|
| Signed by | `UNFILLED` |
| Role | `UNFILLED` |
| Date | `UNFILLED` |
