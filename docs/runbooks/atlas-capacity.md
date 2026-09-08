# Atlas capacity

`17-data-model.md` §3 (`AC-DATA-03.4`) and §6 (`DATA-06`).

## The constraint

Atlas M0 is **512 MB of storage, total** — documents *and* indexes, in one
budget. There is no soft limit and no warning tier: at 512 MB writes fail, and
the first write to fail is somebody's résumé upload.

That makes index size a number to watch rather than a detail. Documents grow
because users use the product, which is the point; indexes grow because somebody
adds one, which is a decision. A new compound index on `jobs` costs tens of
megabytes the moment it is created.

## The budget

| | |
|---|---|
| Ceiling for the R1 index set | **120 MB** |
| Measured at | **50,000** jobs |
| M0 total | **512 MB** |
| Enforced by | `tests/integration/test_index_size_budget.py` (nightly) |

120 MB leaves roughly 390 MB for documents, which `DATA-06`'s arithmetic sizes
at well under that for R1's expected corpus. The gap is deliberate: an M0 that
is 95% full is one bad day from refusing writes, and the migration off M0 is not
something to do under pressure.

## Measurements

Record each run. The recorded number is what makes a later breach diagnosable:
"it is 130 MB now" is only useful beside "it was 84 MB in September, and these
were the largest three".

| Date | Jobs | Total index size | Largest three | Measured by |
|---|---|---|---|---|
| `UNFILLED` | 50,000 | `UNFILLED` | `UNFILLED` | `UNFILLED` |

The nightly job prints the per-collection breakdown on failure and the total on
success; copy the total and the three largest entries into a new row rather than
overwriting the last one. A single current value answers "are we over budget"
and nothing else; the series answers "what changed", which is the question asked
when the answer to the first one is yes.

## Taking the measurement by hand

```bash
uv run --project apps/api pytest tests/integration/test_index_size_budget.py \
  -m real_source -o addopts=""
```

It builds 50,000 realistic listings, creates every declared index, reads
`collStats`, and drops the database afterwards. Minutes, not seconds — which is
why it is nightly and not on the merge path (`AC-OPS-03.6` caps a full CI run at
12 minutes).

The corpus is realistic *in the fields the indexes cover*. That matters most for
the text index on `jobs`, whose size tracks the number of distinct terms rather
than the number of documents: 50,000 copies of one description would report a
text index of essentially nothing and a budget with plenty of room.

## If the budget is breached

1. **Find which index grew.** The failure message has the per-collection
   breakdown. It is almost always one index on `jobs`; `job_search` (text) is
   the largest single entry in the set and the least predictable.
2. **Ask what query it serves**, from §3's table. An index whose row nobody can
   point at is an index to drop — and `AC-DATA-03.3` should have caught it
   already, since an undeclared index fails `/readyz`.
3. **Do not raise the ceiling to make the test pass.** `CLAUDE.md`: never weaken
   an acceptance criterion to make a test pass. The ceiling exists because the
   headroom above it is what stops M0 refusing writes; raising it spends that
   headroom without deciding to.
4. If the index is genuinely needed and the budget is genuinely too small, that
   is an M2 upgrade and a spec amendment, in that order.

| Field | Value |
|---|---|
| Owner accountable for this budget | `UNFILLED` |
| Cluster tier in force | `UNFILLED` |
| Last measured | `UNFILLED` |
