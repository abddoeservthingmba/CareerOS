"""T-SEC-01.1-.3 - the threat model exists, is current, and is honest.

`AC-SEC-01.1`: "`docs/compliance/threat-model.md` exists containing the asset
list, the adversary table, and the explicit non-goals, reviewed within 180 days."
`AC-SEC-01.2`: "Every control named in the table maps to a passing test
elsewhere in this specification (checked by the traceability gate)."
`AC-SEC-01.3`: "Every accepted risk has a named compensating control or an
explicit 'none'."

**Why a threat model is a checkable artifact rather than a document.**
§1's objective is "name what is actually being defended against, so controls can
be judged against something". A control list with no threat model is a list
nobody can argue with: every item looks prudent, none can be shown to be
unnecessary, and none can be shown to be missing. So the checks here are about
whether the document can still do that job - whether every adversary names a
control, whether every control names a criterion that exists, and whether every
accepted risk says what compensates for it.

**`AC-SEC-01.3` is the criterion that does the most work.** "Or an explicit
'none'" is the clause worth reading twice. An accepted risk with no compensating
control and no acknowledgement is indistinguishable from a risk nobody thought
about - and the second is what a threat model is for. Forcing the word "none"
onto the page makes the difference visible: somebody decided, and here is what
they decided.

**What this cannot check**, stated so a green run is not read as more than it
is: whether the assets are ordered correctly, whether an adversary is missing,
and whether a compensating control actually compensates. Those are judgements,
which is why `AC-SEC-01.1` puts a 180-day review on the document and why the
owner and reviewer fields are signed by a person.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path

import pytest

DOCUMENT = Path("docs") / "compliance" / "threat-model.md"
SPEC = Path("docs") / "spec" / "16-security-and-compliance.md"

#: `AC-SEC-01.1`'s window.
MAX_REVIEW_AGE_DAYS = 180

#: §1's five assets, in §1's order. Order is part of the content: "in order of
#: consequence" is what decides which control wins when two compete for effort.
ASSETS = (
    "résumé and profile",
    "application record",
    "Credentials and sessions",
    "AI budget",
    "job corpus",
)

#: §1's seven adversaries.
ADVERSARIES = (
    "Credential stuffer",
    "Another user of the product",
    "A malicious job listing",
    "An abusive signup",
    "A stolen device",
    "A compromised dependency",
    "Us, by accident",
)

#: §1's four explicit non-goals, plus the two R2 controls §2 defers. Every one
#: has to appear with a compensating control or an explicit "none".
NON_GOALS = (
    "compromised host",
    "malicious operator",
    "state-level adversary",
    "revocation before its 15-minute expiry",
)

UNFILLED = "UNFILLED"

AC_REFERENCE = re.compile(r"`(AC-[A-Z]+-\d+\.\d+)`")


@pytest.fixture
def text(repo: Path) -> str:
    return (repo / DOCUMENT).read_text(encoding="utf-8")


def dated(text: str, label: str) -> date | None:
    found = re.search(rf"\|\s*{re.escape(label)}\s*\|\s*(\d{{4}}-\d{{2}}-\d{{2}})\s*\|", text)
    return date.fromisoformat(found.group(1)) if found else None


# -- AC-SEC-01.1: it exists and has the three parts --------------------------


def test_the_document_exists(repo: Path):
    assert (repo / DOCUMENT).is_file(), (
        f"{DOCUMENT.as_posix()} is missing. §1's objective is 'name what is "
        "actually being defended against, so controls can be judged against "
        "something'; without the document there is nothing to judge them against."
    )


@pytest.mark.parametrize("asset", ASSETS)
def test_every_asset_is_listed(text: str, asset: str):
    """`AC-SEC-01.1`'s "asset list"."""
    assert asset in text, f"the asset list does not mention {asset!r}"


def test_the_assets_are_in_the_order_the_spec_gives(text: str):
    """Order is content, not presentation.

    §1 says "in order of consequence", and the order is what decides which
    control wins when two compete for effort. A reordered list is a different
    document with the same words.
    """
    positions = [text.index(asset) for asset in ASSETS]

    assert positions == sorted(positions), (
        "the assets are not in §1's order; 'in order of consequence' is the "
        "thing that makes the list useful"
    )


def test_the_order_is_by_consequence_to_the_user(text: str):
    """And says so.

    The résumé is first rather than credentials, which inverts the usual
    ordering - credentials are the higher-value target and the résumé is the
    higher-consequence loss. Stating why is what stops somebody "correcting" it.
    """
    # Whitespace-normalised: the phrase wraps across a line in the document,
    # and a prose assertion that a reflow can break is a prose assertion that
    # gets deleted rather than fixed.
    flat = " ".join(text.split())
    assert "in order of consequence" in flat
    assert "to the user" in flat


@pytest.mark.parametrize("adversary", ADVERSARIES)
def test_every_adversary_is_in_the_table(text: str, adversary: str):
    """`AC-SEC-01.1`'s "adversary table"."""
    assert adversary in text


def test_every_adversary_names_a_control(text: str):
    """An adversary with no control is a threat nobody answered.

    Checked by row, because a table can name seven adversaries and four
    controls and still look complete at a glance.
    """
    section = text.split("## 2. Adversaries", 1)[1].split("## 3.", 1)[0]

    for line in section.split("\n"):
        cells = [cell.strip() for cell in line.split("|")]
        if len(cells) < 6 or cells[1] in ("Adversary", "---"):
            continue
        assert cells[3], f"{cells[1]!r} names no control"
        assert cells[4], f"{cells[1]!r} names no verifying criterion"


@pytest.mark.parametrize("non_goal", NON_GOALS)
def test_every_non_goal_is_recorded(text: str, non_goal: str):
    """`AC-SEC-01.1`'s "explicit non-goals".

    §1: "recorded so the choice is deliberate". An undocumented non-goal is
    indistinguishable from an oversight, and the two get very different
    reactions from whoever finds it.
    """
    assert non_goal in text


# -- AC-SEC-01.2: every control maps to a criterion that exists --------------


def test_every_control_names_a_criterion_that_exists(repo: Path, text: str):
    """AC-SEC-01.2.

    Every `AC-` reference in the adversary table is checked against the
    specification's own set of defined criteria. A control that cites a
    criterion nobody wrote is a control with no test behind it - and it reads
    exactly like one that has.
    """
    from specgate import parser

    defined = set(parser.parse_spec().criteria)
    section = text.split("## 2. Adversaries", 1)[1].split("## 3.", 1)[0]

    referenced = set(AC_REFERENCE.findall(section))
    assert referenced, "the adversary table cites no criteria at all"

    missing = sorted(referenced - defined)
    assert missing == [], (
        f"the adversary table cites {missing}, which the specification does not "
        "define. A control naming a criterion nobody wrote has no test behind it "
        "and reads exactly like one that has."
    )


def test_every_non_goal_names_a_criterion_or_says_none(repo: Path, text: str):
    """The same check over §3, where a citation is optional but a wrong one is
    still wrong."""
    from specgate import parser

    defined = set(parser.parse_spec().criteria)
    section = text.split("## 3. Explicitly not defended", 1)[1].split("## 4.", 1)[0]

    missing = sorted(set(AC_REFERENCE.findall(section)) - defined)
    assert missing == [], f"§3 cites {missing}, which the specification does not define"


def test_the_adversary_table_matches_the_specifications(repo: Path, text: str):
    """The document and `16-security-and-compliance.md` §1 name the same seven.

    Two copies of one list is one copy too many; the only thing that keeps them
    equal is something that compares them. An adversary added to the
    specification and not to this document is a threat the compliance artifact
    does not mention.
    """
    spec = (repo / SPEC).read_text(encoding="utf-8")
    spec_section = spec.split("Adversaries and the controls", 1)[1].split("Explicitly **not**", 1)[
        0
    ]

    named_in_spec = {
        cells[1].strip()
        for line in spec_section.split("\n")
        if len(cells := line.split("|")) >= 5 and cells[1].strip() not in ("Adversary", "---")
    }

    missing = sorted(named_in_spec - set(ADVERSARIES))
    assert missing == [], f"§1 names adversary/adversaries {missing} this document omits"


# -- AC-SEC-01.3: every accepted risk names a compensating control -----------


def test_every_accepted_risk_names_a_compensating_control(text: str):
    """AC-SEC-01.3.

    "Or an explicit 'none'" is the clause that does the work. An accepted risk
    with no compensating control and no acknowledgement is indistinguishable
    from one nobody thought about - and the second is the thing a threat model
    exists to prevent. Writing the word forces the difference onto the page.
    """
    section = text.split("## 3. Explicitly not defended", 1)[1].split("## 4.", 1)[0]

    subsections = [block for block in section.split("\n### ")[1:]]
    assert len(subsections) >= 4, f"§3 has {len(subsections)} accepted risks; §1 names four"

    for block in subsections:
        heading = block.split("\n", 1)[0].strip()
        assert "**Compensating control:**" in block, (
            f"the accepted risk {heading!r} names no compensating control and does "
            "not say 'none'. AC-SEC-01.3 requires one or the other, because an "
            "unacknowledged accepted risk reads exactly like an oversight."
        )


def test_a_compensating_control_of_none_is_explicit(text: str):
    """Three of the accepted risks genuinely have none, and each says so.

    An empty cell, a dash, or an omitted line would all read as "not filled in
    yet". The word is what distinguishes a decision from a gap.
    """
    section = text.split("## 3. Explicitly not defended", 1)[1].split("## 4.", 1)[0]

    assert section.count("**Compensating control:** none") >= 3


def test_the_reason_is_given_where_the_answer_is_none(text: str):
    """ "None" on its own is an admission, not a decision.

    Each says why the alternative was rejected - a compromised host defeats
    application-level encryption, a state-level adversary is not changed by any
    control here, and field encryption protects a lower-ranked asset than the
    résumé text it would not protect.

    Length is a crude proxy and it is the only one a test can apply, so the
    threshold is set where a bare "none." plus one sentence fails and a real
    paragraph passes. It was 400 first, which failed the state-level entry at
    269 characters - and that entry is short because there is genuinely less to
    say, not because it was left unexplained. Calibrating to the shortest
    honest answer rather than to the longest is what keeps this a check rather
    than a word count.
    """
    section = text.split("## 3. Explicitly not defended", 1)[1].split("## 4.", 1)[0]

    for block in section.split("\n### ")[1:]:
        heading = block.split("\n", 1)[0].strip()
        reasoning = block.split("**Compensating control:**", 1)[-1]
        assert len(reasoning) > 180, (
            f"{heading!r} states a compensating control and does not say why it "
            "is the right trade. 'None' on its own is an admission, not a decision."
        )


def test_the_r2_deferrals_are_treated_as_accepted_risks(text: str):
    """§2 marks malware scanning and field encryption R2.

    A control deferred to a later track is an accepted risk for the duration of
    R1, whether or not §1's list names it - and "it is on the roadmap" is not a
    compensating control.
    """
    assert "malware scanning" in text.casefold()
    assert "field-level encryption" in text.casefold()


# -- it is current -------------------------------------------------------------


def test_it_carries_both_review_dates(text: str):
    assert dated(text, "Last reviewed") is not None
    assert dated(text, "Next review due") is not None


def test_the_review_interval_is_one_hundred_and_eighty_days(text: str):
    """`AC-SEC-01.1`'s window, asserted against the document's own two dates -
    so the *policy* is checked here and the *freshness* below."""
    reviewed = dated(text, "Last reviewed")
    due = dated(text, "Next review due")

    assert reviewed is not None and due is not None
    assert (due - reviewed) <= timedelta(days=MAX_REVIEW_AGE_DAYS)


def test_the_review_is_not_overdue(text: str):
    """The one assertion here that is *supposed* to start failing with the
    passage of time. That is what a review date is for.

    §4: a threat model that is not revisited describes the product as it was,
    and the gap grows silently in the direction of fewer controls covering more
    surface.
    """
    from app.core import clock

    reviewed = dated(text, "Last reviewed")
    assert reviewed is not None
    age = clock.now().date() - reviewed

    assert age <= timedelta(days=MAX_REVIEW_AGE_DAYS), (
        f"the threat model was last reviewed {age.days} days ago. Re-read §2's "
        "control table against §2 of this document - the assets rarely change, "
        "the number of ways in changes with every requirement."
    )


def test_it_says_what_reviewing_it_means(text: str):
    """A review instruction of "re-read this document" produces a re-read and
    no findings. The useful instruction is to read it *against* something."""
    assert "Review means" in text
    assert "§2's table" in text or "control table" in text


def test_it_says_what_it_cannot_answer(text: str):
    """A compliance document that reads as complete is worse than one that
    admits its limits, because the limits are where somebody will rely on it.

    Whether the assets are ordered correctly, whether an adversary is missing,
    and whether a compensating control actually compensates are judgements. The
    document says so, which is why it carries a human's signature.
    """
    section = text.split("## 4.", 1)[1]

    assert "not" in section
    assert "we do not know" in section or "gap" in section


# -- the fields a person owns --------------------------------------------------


def test_the_ownership_fields_are_the_only_unfilled_ones(text: str):
    """Unlike `ai-providers.md`, this document is complete except for its
    owner.

    The threat model is a thing the code can state; the procurement facts in
    the AI compliance document are not. So exactly two fields are `UNFILLED`
    here - who owns the control and who reviewed it - and a third appearing
    would mean something factual was left blank.
    """
    remaining = [
        line.strip()
        for line in text.split("\n")
        if line.lstrip().startswith("|") and f"`{UNFILLED}`" in line
    ]

    assert len(remaining) == 2, f"{len(remaining)} fields are UNFILLED: {remaining}"
    assert any("Owner accountable" in line for line in remaining)
    assert any("Reviewed by" in line for line in remaining)
