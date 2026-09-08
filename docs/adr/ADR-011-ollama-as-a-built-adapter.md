# ADR-011 — Ollama becomes a built adapter, not a stub

- **Status:** accepted
- **Date:** 2026-09-08
- **Amends:** `05-ai-layer.md` §2 (`AI-02`) — the R1 adapter list and `AC-AI-02.3`
- **Supersedes nothing.** Gemini remains the R1 production default (D3).

## Context

`AI-02` as written lists five adapters and two states for them:

> Adapters present in R1: `gemini.py` (real), `fake.py` (deterministic, used by
> every test and by local development without a key). `openai.py`,
> `anthropic.py`, and `ollama.py` are R1 **stubs** that exist only to prove the
> contract.

That split was made for a good reason — three speculative adapters would be
three things to keep working with no user — and it is right about OpenAI and
Anthropic. It is wrong about Ollama, for one reason the specification itself
raises two sections later.

`AI-05` §5.4 (D5) requires a choice before public sign-up between the paid
Gemini tier, whose terms say prompts are not used for training, and the free
tier, whose terms say they are. The product sends **resume text and job
description text** to whichever provider is configured. The free tier is the
affordable option and the one chosen for now, which means that during
development every resume used as a fixture — including the developer's own, and
the ten real ones `AC-AI-07.5` requires — is sent to a third party under terms
that permit training on it.

The fake provider avoids that entirely and is genuinely sufficient for every
acceptance criterion in `AI-03`, `AI-04`, `AI-05` and `AI-07`. But it is
deterministic by construction: it cannot answer "does this prompt actually
extract employers correctly", which is the question `AC-AI-07.5`'s ≥90%
field-level precision gate exists to ask.

So there is a gap between "no real model at all" and "a real model that trains
on the input", and the gap is exactly where iterating on prompt quality
happens.

## Decision

**Promote `ollama.py` from an R1 stub to a built adapter, as the
local-development provider.** Gemini stays the R1 production default and the
only provider `AI-05`'s isolation rules apply to. `openai.py` and
`anthropic.py` remain stubs.

Concretely, in `05-ai-layer.md` §2:

- the R1 adapter list moves `ollama.py` from the stub sentence to the real one,
  qualified as the local-development provider;
- `AC-AI-02.3` changes "the three stubs" to "the two stubs".

No acceptance criterion is added or removed, and no identifier changes, so the
826 AC/T pairs and the traceability chain are untouched. `AC-AI-02.3`'s contract
suite still runs over all five adapters; Ollama now passes it by answering
rather than by raising.

## Consequences

**What this buys.**

- Prompt iteration and the resume-extraction golden set can run against a real
  model with **no text leaving the machine**. That is a stronger privacy
  position than either D5 option, and it applies during the phase when the
  fixtures are real résumés belonging to real people.
- Development works with no key, no account and no network. `AI-02`'s promise
  that "local development without a key" works is now true with a real model
  rather than only with the fake.
- The provider abstraction gets a second *real* implementation. `AC-AI-02.3`
  exists to stop the protocol "drifting into being Gemini-shaped", and two
  stubs that raise are much weaker evidence of that than one adapter that
  actually answers.

**What it costs.**

- A third adapter to keep working. Mitigated by the contract suite it already
  has to pass, and by it being genuinely simple: Ollama's HTTP API is small and
  the adapter needs no credential at all.
- Extraction quality on a locally runnable model is worse than Flash-Lite's.
  This is a development provider, and `AC-AI-07.5`'s precision gate is
  measured against whatever provider production uses — the nightly `real_ai`
  run is not satisfied by an Ollama result.
- One more thing that can be misconfigured in production. Mitigated by
  `AC-AI-02.5`, which already requires an unresolvable provider to fail at
  startup rather than at first call, and by `ollama.py` refusing to start when
  `APP_ENV` is `prod` unless its base URL is explicitly set — a local model
  reachable from a production container is almost always a mistake.

**What is explicitly not changed.**

- Gemini is still the production default. D3 is not reopened.
- `AI-05`'s isolation rules are Gemini's. Ollama has no credential, no OAuth
  path and no consumer entitlement to be confused with, so HR-6 has nothing to
  bite on there — but `ai/*` still may not import `authlib`, `google.auth`,
  `google.oauth2` or `googleapiclient`, and the `no-oauth-in-ai` contract binds
  the whole package.
- D5 still has to be answered before public sign-up. This ADR makes the
  question less urgent for *development*; it does not answer it for users.

## Alternatives considered

**Leave Ollama a stub and use the fake provider throughout.** Free, zero work,
and the specification's own answer. Rejected because it defers the first honest
measurement of prompt quality to the day the golden set is built, which is also
the day ten real résumés get sent to a provider that may train on them.

**Use the Gemini free tier for development.** Simplest, and already the D5
choice. Rejected as the *only* option rather than rejected outright: it remains
available, and this ADR does not remove it. The objection is narrow and
specific — the fixtures are real people's employment histories.

**Promote OpenAI or Anthropic instead.** Neither has a free tier that would
serve development, so the privacy and cost arguments above do not apply, and
each would be a speculative adapter with no user. Left as stubs.
