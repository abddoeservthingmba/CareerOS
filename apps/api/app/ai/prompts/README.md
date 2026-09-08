# Prompts

`05-ai-layer.md` §7. One directory per `Feature`, one file per version:

```
ai/prompts/<feature>/v1.md
ai/prompts/<feature>/v2.md
```

The loader is `app/ai/prompt.py`; it runs at boot and a malformed file fails the
boot. This README is not a `v<N>.md`, so it is not loaded.

## The file

```markdown
---
version: 1
feature: resume_extract
tier: fast
output_schema: app.modules.resumes.schemas.ExtractedResume
untrusted_slots: [resume_text]
changelog:
  - "v1 — first version."
---

Extract structured fields from the résumé in [resume_text].
...
```

Front matter keys are exactly the six above. An unknown key is refused rather
than ignored: a misspelled key is an unset value, and the value it was meant to
set is the one that mattered.

## `{{slot}}` renders to `[slot]`, never to content

A `{{resume_text}}` in the body becomes the literal `[resume_text]` — the header
that `untrusted.render()` writes above that region of the nonce-delimited data
block. The résumé text itself never enters the instruction section; it travels
in `LLMRequest.untrusted` and is rendered once, by `untrusted.py` alone.

That is why `render()` takes no arguments. If you find yourself wanting to
interpolate content here, the content is untrusted and belongs in the data
block — putting it beside the rules is the injection surface HR-11 removes.

Both directions are checked: every declared slot must appear in the body, and
every `{{slot}}` in the body must be declared. An undeclared slot points at a
region that was never sent; an unused declaration sends content the model was
never told about. Neither raises at runtime, and both quietly degrade the
answer.

## A used version is immutable

Once a version has run in production it is recorded in
`packages/contracts/prompts-in-production.json` with its hash, and the
`prompt-immutability` CI step fails any edit to it. An improvement is `v<N+1>`.

This is what makes `prompt_version` on a stored artifact mean something: the
text that produced an output is still retrievable, byte for byte, from the
string stored beside it.

## Every prompt needs a golden set

`tests/ai/golden/<feature>/` holds `(input, expected)` pairs.
`tests/ai/test_golden_fake.py` fails if a prompt exists with no cases — so the
prompt and its tests land in the same commit, which is the point of §7.
