"""T-FOUND-16.5 - no suite sends real mail.

`AC-FOUND-16.5`: "No test in any suite sends mail outside mailpit (asserted by
an outbound-request guard)."

Two guards, because they fail differently:

* **A repository guard** - nothing under `tests/` imports `smtplib`, a provider
  SDK, or an HTTP client aimed at one. This catches the test that would send
  before it is ever run, which matters because the failure mode of the other
  guard is "it already went out".
* **A runtime guard** - `smtplib.SMTP` is replaced for the whole session, so a
  test that reaches a real socket raises instead of connecting.

Sending real mail from a test suite is not a slow test: it is a message to a
real person, from a domain whose reputation every other user depends on.
"""

from __future__ import annotations

import ast
import smtplib
from pathlib import Path

import pytest

#: Modules that can put a message on the wire. `smtplib` is allowed in exactly
#: one place - the adapter that exists to speak SMTP - and nowhere under tests.
OUTBOUND_MODULES = {
    "smtplib",
    "aiosmtplib",
    "resend",
    "boto3",
    "botocore",
    "sendgrid",
    "mailgun",
    "postmarker",
}

#: `SmtpSender` is the adapter; `httpx` is the API test client. Both are the
#: point rather than a violation, so they are named here instead of being
#: matched by a pattern that would also hide the next real one.
ALLOWED_IMPORTERS = {
    Path("app/infra/email/senders.py"),
    Path("tests/conftest.py"),  # installs the guard
    Path("tests/spec/test_no_live_email.py"),  # asserts the guard
}


def _imports(source: str) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module.split(".")[0])
    return names


def test_no_test_imports_a_mail_transport(repo: Path):
    """AC-FOUND-16.5, the repository half."""
    offenders: list[str] = []
    for path in sorted((repo / "apps" / "api" / "tests").rglob("*.py")):
        relative = path.relative_to(repo / "apps" / "api")
        if relative in ALLOWED_IMPORTERS:
            continue
        found = _imports(path.read_text(encoding="utf-8")) & OUTBOUND_MODULES
        if found:
            offenders.append(f"{relative.as_posix()} imports {sorted(found)}")
    assert offenders == [], (
        "a test that can open a mail transport can send a message to a real "
        "person from a domain every other user depends on:\n" + "\n".join(offenders)
    )


def test_only_the_adapter_speaks_smtp(repo: Path):
    """`smtplib` lives in one file, which is what makes swapping the transport a
    change inside `infra/email` (`AC-FOUND-16.9`)."""
    api = repo / "apps" / "api"
    importers = [
        path.relative_to(api).as_posix()
        for path in sorted((api / "app").rglob("*.py"))
        if "smtplib" in _imports(path.read_text(encoding="utf-8"))
    ]
    assert importers == ["app/infra/email/senders.py"], importers


def test_the_runtime_guard_is_installed():
    """AC-FOUND-16.5, the runtime half.

    `conftest.py` replaces `smtplib.SMTP` for the whole session. This asserts the
    replacement is in place rather than trusting that it was, because a guard
    that silently stopped being installed is worse than no guard: it is a guard
    everyone believes in.
    """
    assert getattr(smtplib.SMTP, "__jobpilot_blocked__", False), (
        "the outbound-mail guard is not installed; see tests/conftest.py"
    )


def test_the_guard_raises_rather_than_connecting():
    with pytest.raises(RuntimeError, match="mailpit"):
        smtplib.SMTP("smtp.example.com", 25)
