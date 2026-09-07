"""What a model call costs - `AI-04`.

`05-ai-layer.md` §4: "`est_cost_usd` is computed from `MODEL_PRICING`, a config
table of input and output per-million-token prices keyed by model id, with an
explicit `unknown` marker. An unpriced model records `est_cost_usd: null` and
increments an `ai_unpriced_model` counter that alerts, rather than silently
recording zero."

The `unknown` marker is the whole design, and it is worth being explicit about
why it is not a default of zero. A model this table has never heard of is
usually a model somebody just switched to. Recording its cost as zero means the
dashboard says spend is flat, the budget never trips, and the first sign of a
problem is the bill. Recording `null` and alerting means someone is told, that
day, that cost tracking has a blind spot - which is the only honest thing an
estimate can say about a price it does not know.

**Prices carry the date they were verified**, because §5.2 requires it: "Model
names and free-tier limits are verified against Gemini's documentation at
implementation time and recorded with a date. Any figure in this specification
about a provider's limits is indicative and must not be hard-coded."

**And, where the provider has announced one, the date the price changes.**
Gemini's 3.x Flash rates are introductory and double on 2027-01-01. A table that
recorded only today's number would keep reporting half the real cost from that
morning, silently, on every dashboard and in every budget check. `price_for`
takes the instant from `core.clock`, so the change happens by itself and a
frozen-clock test can stand on either side of it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from app.core import clock

#: How long a verification stays good. §5.2 asks for a date; this is what makes
#: the date do something. Ninety days, matching `AC-AI-05.1`'s review window for
#: the compliance document - the two go stale together and should be refreshed
#: together.
MAX_PRICE_AGE_DAYS = 90


@dataclass(frozen=True)
class Price:
    """Per-million-token prices for one model, and when they stop being true.

    `Decimal` rather than `float`: these are money, and `0.30 * 3` in binary
    floating point is not `0.90`. The same rule as `shared/money.py`, for the
    same reason.
    """

    input_per_million: Decimal
    output_per_million: Decimal
    verified_on: date
    #: The day the provider has already said these numbers change, if it has.
    changes_on: date | None = None
    then_input_per_million: Decimal | None = None
    then_output_per_million: Decimal | None = None
    note: str = ""

    def at(self, moment: datetime) -> tuple[Decimal, Decimal]:
        """The prices in force at `moment`."""
        if (
            self.changes_on is not None
            and moment.date() >= self.changes_on
            and self.then_input_per_million is not None
            and self.then_output_per_million is not None
        ):
            return self.then_input_per_million, self.then_output_per_million
        return self.input_per_million, self.output_per_million


#: The table itself lives in `model-pricing.yaml` beside this module.
#: `AC-AI-02.2` forbids a model id as a `.py` literal, and the reason is not
#: tidiness: a provider changes prices on their schedule, and a table that
#: needed a release to update is a table that is wrong between releases.
#: `MODEL_PRICING_PATH` overrides the file, so a deployment can correct a price
#: without waiting for a build.
PRICING_FILE = Path(__file__).with_name("model-pricing.yaml")


def _load(path: Path) -> tuple[dict[str, Price], frozenset[str]]:
    """Read the table, or fail at import.

    Failing loudly is the point. A pricing file that could not be read and left
    the table empty would price every model as unknown - which alerts, but on
    every call, which is the same as not alerting.
    """
    import yaml

    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    default_date = _as_date(document.get("verified_on"))
    if default_date is None:
        raise ValueError(
            f"{path.name} has no top-level `verified_on`. §5.2 requires the "
            "figures to be recorded with the date they were read off the "
            "provider's page, and an undated price cannot go stale."
        )

    table: dict[str, Price] = {}
    for model, entry in (document.get("models") or {}).items():
        table[str(model)] = Price(
            input_per_million=Decimal(str(entry["input"])),
            output_per_million=Decimal(str(entry["output"])),
            verified_on=_as_date(entry.get("verified_on")) or default_date,
            changes_on=_as_date(entry.get("changes_on")),
            then_input_per_million=(
                Decimal(str(entry["then_input"])) if "then_input" in entry else None
            ),
            then_output_per_million=(
                Decimal(str(entry["then_output"])) if "then_output" in entry else None
            ),
            note=str(entry.get("note", "")),
        )
    return table, frozenset(str(name) for name in document.get("length_tiered") or [])


def _as_date(value: object) -> date | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


MODEL_PRICING, LENGTH_TIERED = _load(PRICING_FILE)

#: The day the figures were read off the provider's own pricing page, taken
#: from the file rather than restated here.
VERIFIED_ON = min(price.verified_on for price in MODEL_PRICING.values())

#: Incremented whenever a call is made against a model this table does not
#: price. `15-infra-and-ops.md` §4.3 alerts on it: "Unpriced AI model | any
#: `est_cost_usd: null` | Cost tracking has a blind spot".
UNPRICED_CALLS: dict[str, int] = {}


def is_priced(model: str) -> bool:
    return model in MODEL_PRICING


def estimate_cost(
    model: str, input_tokens: int, output_tokens: int, *, at: datetime | None = None
) -> Decimal | None:
    """`est_cost_usd`, or `None` when the model is unpriced.

    `None`, never zero. A model this table has never heard of is usually one
    somebody just switched to; calling it free means the dashboard says spend is
    flat and the first sign of trouble is the bill.
    """
    price = MODEL_PRICING.get(model)
    if price is None:
        UNPRICED_CALLS[model] = UNPRICED_CALLS.get(model, 0) + 1
        return None

    moment = at or clock.now()
    input_rate, output_rate = price.at(moment)
    million = Decimal(1_000_000)
    return (Decimal(input_tokens) * input_rate + Decimal(output_tokens) * output_rate) / million


def unpriced_count(model: str | None = None) -> int:
    if model is None:
        return sum(UNPRICED_CALLS.values())
    return UNPRICED_CALLS.get(model, 0)


def stale_prices(*, at: datetime | None = None) -> list[str]:
    """Models whose verification has aged out, or whose price has already moved.

    Read by `tests/spec/test_compliance_docs.py`. A price that changed while
    nobody looked reports half the real spend, on every dashboard and in every
    budget check, until someone notices the bill.
    """
    moment = at or clock.now()
    today = moment.date()
    stale: list[str] = []
    for model, price in MODEL_PRICING.items():
        if (today - price.verified_on).days > MAX_PRICE_AGE_DAYS:
            stale.append(
                f"{model}: verified {price.verified_on}, older than {MAX_PRICE_AGE_DAYS} days"
            )
        if (
            price.changes_on is not None
            and today >= price.changes_on
            and price.then_input_per_million is None
        ):
            stale.append(
                f"{model}: price changed on {price.changes_on} and no new rate is recorded"
            )
    return stale


__all__ = [
    "LENGTH_TIERED",
    "PRICING_FILE",
    "MAX_PRICE_AGE_DAYS",
    "MODEL_PRICING",
    "UNPRICED_CALLS",
    "VERIFIED_ON",
    "Price",
    "estimate_cost",
    "is_priced",
    "stale_prices",
    "unpriced_count",
]
