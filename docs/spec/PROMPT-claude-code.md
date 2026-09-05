# Kickoff prompt for Claude Code

## Step 0 — set up the repo before you start Claude Code

```bash
mkdir jobpilot && cd jobpilot && git init
mkdir -p docs/spec
# copy the 20 spec files + the 6 companions into docs/spec/
cp /path/to/jobpilot-spec/*.md    docs/spec/
cp /path/to/jobpilot-spec/*.yaml  docs/spec/
cp /path/to/jobpilot-spec/*.json  docs/spec/
cp /path/to/jobpilot-spec/*.py    docs/spec/
# put CLAUDE.md at the repo root, not in docs/
cp /path/to/CLAUDE.md .
git add -A && git commit -m "docs: JobPilot build specification v2.1"
claude
```

`CLAUDE.md` at the root is loaded automatically every session, so the rules below do not have to be
repeated. The prompt in §1 is the one-time kickoff; §2 is what you paste for each subsequent chunk.

---

## 1 — Paste this as your first message

> You are building JobPilot from the specification in `docs/spec/`. Read `docs/spec/README.md`,
> `00-scope-and-phases.md`, `01-foundations.md` and `17-data-model.md` before writing any code.
> `CLAUDE.md` at the repo root holds the operating rules — follow them exactly.
>
> **Context discipline:** do not read all twenty spec files. Read the four above once, then use
> `make bundle REQ=<id>` (which you will build in step 1 below) to pull only the files a given
> requirement needs. No R1 requirement needs more than five.
>
> **We are building track R1 only.** Skip every section marked R2 or R3. Sections marked `absent`
> in the status registry must produce no code, no route, no flag and no skipped test.
>
> **Work in this order.**
>
> **Step 1 — the spec tooling, before any product code.** The specification ships two generator
> scripts (`docs/spec/spec_metadata.py`, `docs/spec/gen_dependencies.py`) and four gates that keep
> the rest honest. Build them first, because everything after depends on them being real:
> `FOUND-06` (traceability gate), `DEP-01`–`DEP-04` (manifest, module graph, track closure, phase
> closure), `DEP-06` (`make bundle`), `FOUND-15` (status registry). These are pure Python with no
> product dependencies. When they pass on an otherwise empty repo, `make bundle` works and you can
> use it for everything that follows.
>
> **Step 2 — P0, infrastructure proving.** Everything in `00-scope-and-phases.md` §4, phase P0,
> including the two v2.1 additions: `FOUND-16` email transport (P1 needs it) and the `DATA-06`
> embedding quantization codec (P2 needs it). P0 is done when a commit on `develop` reaches staging
> unattended and both clients render live health from it — but **do not deploy**; get it green in
> CI and Docker Compose locally and stop there.
>
> **Step 3 onwards — follow `docs/spec/BUILD-ORDER.md`**, which is generated from the dependency
> graph. One requirement per commit. Stop at each phase boundary (P0 → P1 → P2 …), summarise what
> is green and what the phase gate says, and wait for me before starting the next phase.
>
> **Definition of done for every requirement:** the implementation, plus every test named in that
> section's **Tests** list at the exact path given, plus `make check` green (ruff, mypy,
> import-linter, the spec gates, pytest with the coverage gates). An acceptance criterion without a
> passing test is not done.
>
> **Before you write code, tell me:**
> 1. the three or four decisions from `00-scope-and-phases.md` §5 you need from me now (D1 product
>    name, D2 Atlas region, D3 host, D7 email provider) — and which defaults you will use if I say
>    nothing;
> 2. the credentials you need in `.env` and when you will need each;
> 3. your plan for step 1, as a list of files you will create.
>
> Then start with step 1. Do not scaffold the whole monorepo speculatively — build what the current
> requirement needs.

---

## 2 — Per-chunk prompt, for every session after the first

> Continue JobPilot. Read `docs/spec/BUILD-ORDER.md` and `git log --oneline -20` to find where we
> are. Next requirement is `<ID>` — run `make bundle REQ=<ID>`, read those files, implement it with
> the tests named in its Tests list, and run `make check`. Stop when it is green and tell me: what
> you built, which acceptance criteria are now passing, and anything in the spec that was ambiguous.

## 3 — Phase-boundary prompt

> We are at the end of phase `<Pn>`. Do not start the next phase. Instead:
> 1. run `make check` and report anything not green;
> 2. list every requirement in `<Pn>` with its acceptance criteria and whether each has a passing
>    test — no summaries, the actual list;
> 3. check the phase gate in `00-scope-and-phases.md` §4 and say plainly whether it is met;
> 4. list every place you deviated from the spec, and every spec ambiguity you worked around.
> Then wait.

## 4 — Prompts worth having ready

**When it starts improvising**
> Stop. Which acceptance criterion are you satisfying with that? If none, either it is out of scope
> for this requirement or the spec is missing something — say which, and propose the spec edit.

**When a test is failing and it wants to move on**
> Do not weaken the criterion or skip the test. Explain in one paragraph why the criterion cannot
> be satisfied as written, and what you would change in the spec.

**When it asks to add a dependency**
> Check `06-connectors.md` §2 and `16-security-and-compliance.md` §2 first: no HTML parser, no
> headless browser, no analytics SDK reaches production. If it is still needed, tell me the package,
> the reason, and which requirement needs it.

**Before the R1 gate**
> Run every item in `00-scope-and-phases.md` §3.1 in order and report pass/fail per item with
> evidence. Do not summarise; I want the eleven items and their results.

---

## 5 — What "deployment later" means here

Nothing deploys until the R1 gate (`00-scope-and-phases.md` §3.1) is green locally and in CI. The
spec already contains the deployment path — `15-infra-and-ops.md` §2 and §3 — but the gate comes
first. When you are ready, the deployment conversation is a separate one and needs four things
decided: **D1** the product name (blocks the production deploy, not the code), **D2** the Atlas
region, **D3** the container host, and **D5** the Gemini tier before any public sign-up. Everything
else has a default that takes effect on its own.

Two things to have in hand before that conversation: a green `make check`, and a backup that has
restored at least once (`OPS-06`).
