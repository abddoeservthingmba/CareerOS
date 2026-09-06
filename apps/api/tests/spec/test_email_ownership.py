"""T-FOUND-16.7 - who is allowed to send email.

`AC-FOUND-16.7`: "`modules/auth` contains no email client and no provider
import; it depends only on `EmailSender`" (import contract, shared with
`AC-DEP-05.2`).

`18-dependency-closure.md` §5.1 is the reason this requirement exists at all:
in v2.0 the only email specification lived in `NOTIF-02a` at phase P6 while
`AUTH-01`, `AUTH-03` and `AUTH-05` needed to send in P1. The likely improvisation
was an inline SMTP call in `modules/auth` that `notifications` later duplicated -
two send paths, two retry policies, and one of them logging the address.

`app/modules/` is empty until `AUTH-01` lands in P1, so most of what follows
scans nothing today and everything the moment a module exists. That is
deliberate: `AC-FOUND-15.7` forbids skipping, and a gate written after the
violation is a gate written to accommodate it.
"""

from __future__ import annotations

import ast
from pathlib import Path

#: A provider by any name. `smtplib` included: `modules/auth` calling it
#: directly is exactly the v2.0 improvisation this requirement removes.
PROVIDER_MODULES = {
    "smtplib",
    "aiosmtplib",
    "resend",
    "boto3",
    "botocore",
    "sendgrid",
    "mailgun",
    "postmarker",
    "email",
}

#: What a product module may take from `infra/email`. A capability and its
#: vocabulary - never an adapter, never the registry's construction.
ALLOWED_EMAIL_NAMES = {
    "EmailSender",
    "MessageId",
    "EmailError",
    "SendFailed",
    "Undeliverable",
    "MissingTemplateData",
    "UnknownTemplate",
    "Bounce",
    "BounceKind",
    "BounceListener",
    "R1_TEMPLATE_IDS",
}

#: Modules of `infra.email` a product module may not reach into. `senders` holds
#: the adapters; `templates` holds the copy, which is `notifications`' to own by
#: id and nobody's to import.
FORBIDDEN_EMAIL_SUBMODULES = {"senders", "templates", "webhook"}


def _module_files(repo: Path) -> list[Path]:
    return sorted((repo / "apps" / "api" / "app" / "modules").rglob("*.py"))


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def test_no_module_imports_a_mail_provider(repo: Path):
    """AC-FOUND-16.7, "no provider import"."""
    offenders: list[str] = []
    for path in _module_files(repo):
        for node in ast.walk(_tree(path)):
            if isinstance(node, ast.Import):
                names = {alias.name.split(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                names = {node.module.split(".")[0]}
            else:
                continue
            found = names & PROVIDER_MODULES
            if found:
                offenders.append(f"{path.name}:{node.lineno} imports {sorted(found)}")
    assert offenders == [], (
        "a product module naming a provider is the v2.0 failure FOUND-16 exists "
        "to remove:\n" + "\n".join(offenders)
    )


def test_no_module_imports_an_email_adapter(repo: Path):
    """AC-FOUND-16.7, "no email client"."""
    offenders: list[str] = []
    for path in _module_files(repo):
        for node in ast.walk(_tree(path)):
            if not isinstance(node, ast.ImportFrom) or not node.module:
                continue
            parts = node.module.split(".")
            if parts[:3] != ["app", "infra", "email"]:
                continue
            if len(parts) > 3 and parts[3] in FORBIDDEN_EMAIL_SUBMODULES:
                offenders.append(f"{path.name}:{node.lineno} imports {node.module}")
            for alias in node.names:
                if alias.name not in ALLOWED_EMAIL_NAMES:
                    offenders.append(f"{path.name}:{node.lineno} imports {alias.name}")
    assert offenders == [], (
        "a product module depends on the `EmailSender` capability and its "
        "vocabulary, never on an adapter:\n" + "\n".join(offenders)
    )


def test_the_transport_does_not_reach_back_into_product_code(repo: Path):
    """The other half of the cut: "delivering a templated message is
    infrastructure; deciding who receives what is product".

    Enforced by `lint-imports`' `infra-is-dumb` contract too; asserted here as
    well because that contract binds the whole of `app.infra`, and this states
    the specific claim `FOUND-16` makes about itself.
    """
    email_dir = repo / "apps" / "api" / "app" / "infra" / "email"
    offenders: list[str] = []
    for path in sorted(email_dir.rglob("*.py")):
        for node in ast.walk(_tree(path)):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
            elif isinstance(node, ast.Import):
                module = node.names[0].name
            else:
                continue
            if module.startswith(("app.modules", "app.ai", "app.connectors")):
                offenders.append(f"{path.name}:{node.lineno} imports {module}")
    assert offenders == [], "\n".join(offenders)


def test_the_package_exposes_the_protocol_not_the_adapters(repo: Path):
    """§16: "`infra/email` exposes one protocol and nothing else."

    An `__init__` that re-exported `MemorySender` would make the import contract
    above pass while a module used an adapter anyway.
    """
    from app.infra import email

    assert "EmailSender" in email.__all__
    for adapter in ("MemorySender", "SmtpSender", "SenderBase", "build_sender"):
        assert adapter not in email.__all__, (
            f"{adapter} is reachable as `from app.infra.email import {adapter}`"
        )


def test_no_provider_sdk_type_appears_in_the_protocol():
    """§16: "No provider SDK type crosses that boundary."

    The signature is an address, a template id, a dict and an optional key; the
    return is a `str`. Every one of those is a builtin, which is what makes a
    second adapter a change inside this package (`AC-FOUND-16.9`).
    """
    import inspect

    from app.infra.email.base import EmailSender

    signature = inspect.signature(EmailSender.send)
    annotations = [str(parameter.annotation) for parameter in signature.parameters.values()]
    assert "Mapping[str, object]" in annotations
    assert str(signature.return_annotation) == "MessageId"
    for annotation in annotations:
        assert "resend" not in annotation.lower()
        assert "boto" not in annotation.lower()
