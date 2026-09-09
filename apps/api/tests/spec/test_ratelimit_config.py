"""T-AUTH-09.6 - every limit is configuration.

`AC-AUTH-09.6`: "Every limit is read from config; no numeric literal for a
limit exists in the limiter."

§9: "Limits are config, not literals, so they can be tuned in R2 without a
deploy." A limiter with `10` written into it is a limiter that needs a release
to respond to an incident, which is the wrong end of the trade when the incident
is an attack in progress.

Asserted against the syntax tree rather than a `grep`, because the interesting
case is a literal in the *capacity* position of a `Limit(...)` call and a text
search cannot tell that from a window length or a slice index.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from app.core.config import Settings

MODULE = Path("apps/api/app/core/ratelimit.py")

#: The window lengths `ratelimit` is allowed to name. §9 expresses its limits
#: per minute and per hour; those two durations are structure, not policy, and
#: `_MINUTE`/`_HOUR` exist so the table reads as the spec writes it.
ALLOWED_WINDOW_NAMES = {"_MINUTE", "_HOUR"}


@pytest.fixture(scope="module")
def tree(repo: Path) -> ast.Module:
    return ast.parse((repo / MODULE).read_text(encoding="utf-8"))


def _limit_calls(tree: ast.Module) -> list[ast.Call]:
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "Limit"
    ]


def test_the_limiter_constructs_limits(tree: ast.Module) -> None:
    """A guard on the guard.

    Every assertion below is vacuously true if `Limit(...)` is never called, so
    the count is checked first. Nine calls is §9's table: four for login, one
    for registration, two for reset, one for verification resend, one for
    refresh.
    """
    calls = _limit_calls(tree)
    assert len(calls) == 9, f"expected §9's nine limits, found {len(calls)}"


def test_no_capacity_is_a_numeric_literal(tree: ast.Module) -> None:
    """`AC-AUTH-09.6` - the capacity always comes from config.

    The first argument of every `Limit(...)` must be an attribute read, which in
    practice is `limits.RATE_*`. A bare `Limit(10, _MINUTE)` fails here.
    """
    offenders: list[str] = []
    for call in _limit_calls(tree):
        capacity = call.args[0] if call.args else None
        if isinstance(capacity, ast.Constant):
            offenders.append(f"line {call.lineno}: Limit({capacity.value!r}, ...)")
        elif not isinstance(capacity, ast.Attribute):
            offenders.append(f"line {call.lineno}: capacity is {type(capacity).__name__}")

    assert not offenders, "a limit is hardcoded in the limiter:\n" + "\n".join(offenders)


def test_every_capacity_names_a_real_settings_field(tree: ast.Module) -> None:
    """The config it reads has to exist.

    `limits.RATE_TYPO_PER_MIN` would satisfy the previous test and then fail at
    runtime on the first request, which is the worst place to find out.
    """
    declared = set(Settings.model_fields)
    unknown: list[str] = []
    for call in _limit_calls(tree):
        capacity = call.args[0]
        assert isinstance(capacity, ast.Attribute)
        if capacity.attr not in declared:
            unknown.append(f"line {call.lineno}: {capacity.attr}")

    assert not unknown, "the limiter reads a setting that does not exist:\n" + "\n".join(unknown)


def test_every_window_is_a_named_duration(tree: ast.Module) -> None:
    """Windows are `_MINUTE` or `_HOUR`, not stray integers.

    Softer than the capacity rule, and intentionally: a window is structure
    rather than tunable policy, so it may be a literal in a *test* helper. In
    the module's own table it must read as §9 writes it.
    """
    offenders: list[str] = []
    for call in _limit_calls(tree):
        window = call.args[1] if len(call.args) > 1 else None
        if isinstance(window, ast.Name) and window.id in ALLOWED_WINDOW_NAMES:
            continue
        shown = ast.dump(window) if window else "absent"
        offenders.append(f"line {call.lineno}: window is {shown}")

    assert not offenders, "a window is not a named duration:\n" + "\n".join(offenders)


def test_all_rate_settings_are_used_by_the_policy(tree: ast.Module) -> None:
    """No orphan limit in `Settings`.

    A `RATE_*` variable nobody reads is a knob that does nothing - an operator
    turns it during an incident and the attack continues. Every one declared
    must be wired, and this is the test that notices when a new one is added to
    config and forgotten in the policy.

    `RATE_GENERAL_PER_MIN_USER` is exempt: §9's table is auth routes, and the
    general per-user limit belongs to the routes that `JOB-01` and its
    neighbours add.
    """
    exempt = {"RATE_GENERAL_PER_MIN_USER"}
    declared = {name for name in Settings.model_fields if name.startswith("RATE_")} - exempt
    read = {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and node.attr.startswith("RATE_")
    }

    assert declared <= read, f"declared but never read: {sorted(declared - read)}"


def test_the_trust_boundary_is_configuration_too(tree: ast.Module) -> None:
    """`TRUSTED_PROXY_CIDRS` exists and defaults to trusting nothing.

    The default is what makes `AC-AUTH-09.4` hold out of the box: with no
    trusted proxies, a forwarding header is never believed and the socket
    address is used. A default that trusted anything would ship the criterion
    broken.
    """
    field = Settings.model_fields.get("TRUSTED_PROXY_CIDRS")

    assert field is not None, "AUTH-09's trust boundary must be configurable"
    assert field.default == "", "the default must trust nothing (AC-AUTH-09.4)"
