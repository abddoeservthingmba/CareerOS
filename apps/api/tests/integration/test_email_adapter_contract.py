"""T-FOUND-16.9 - one contract, every adapter.

`AC-FOUND-16.9`: "Swapping the adapter to a second provider requires no change
outside `infra/email` — proven by the SES adapter passing the same contract
suite."

The SES adapter is not built (it is an HTTP client that arrives with a
credential), so what is proven today is the half that can be: **the suite is
parameterised over `ADAPTERS`, not written against one class.** Adding SES adds
a row to `ADAPTERS` and nothing else, and it is held to every rule below the
moment it exists rather than the moment someone remembers.

Everything asserted here is behaviour `SenderBase` provides, which is the design
claim: an adapter is the transport and nothing else. If a rule below were
implemented per-adapter, the second provider is where it would be forgotten -
and the rules being forgotten are "do not send to a bouncing address" and "do
not log the recipient".
"""

from __future__ import annotations

import pytest

from app.infra.email.base import (
    EmailSender,
    MissingTemplateData,
    Undeliverable,
    UnknownTemplate,
)
from app.infra.email.bounces import BounceKind, MemoryBounceRegistry
from app.infra.email.senders import ADAPTERS, PLANNED_ADAPTERS, SenderBase, build_sender
from app.infra.email.templates import R1_TEMPLATE_IDS

DATA = {"verify_url": "https://example.test/verify/TOKEN"}


@pytest.fixture(params=sorted(ADAPTERS), ids=sorted(ADAPTERS))
def adapter(request: pytest.FixtureRequest) -> SenderBase:
    """One instance per built adapter.

    Constructed through `build_sender`, because that is the path a deployment
    takes and a suite that bypassed it would not notice a provider that cannot
    be reached from configuration at all.
    """
    return build_sender(
        request.param,
        sender_address="no-reply@localhost",
        product_name="JobPilot",
        bounces=MemoryBounceRegistry(),
    )


def test_every_adapter_satisfies_the_protocol(adapter: SenderBase):
    """Structurally, not by inheritance: a provider SDK's own client could be
    wrapped without subclassing anything of ours."""
    assert isinstance(adapter, EmailSender)


async def test_every_adapter_validates_data_before_the_transport(adapter: SenderBase):
    """AC-FOUND-16.2, for every adapter.

    `MemorySender` would record and `SmtpSender` would open a socket; neither
    gets the chance, which is the point of the check living in `SenderBase`.
    """
    with pytest.raises(MissingTemplateData):
        await adapter.send("a@example.test", "verify_email", {})
    assert adapter.attempts == 0


async def test_every_adapter_rejects_an_unknown_template(adapter: SenderBase):
    with pytest.raises(UnknownTemplate):
        await adapter.send("a@example.test", "no_such_template", DATA)
    assert adapter.attempts == 0


async def test_every_adapter_refuses_a_bounced_address(adapter: SenderBase):
    """AC-FOUND-16.6, for every adapter - the rule that protects the sending
    domain for every other user."""
    adapter.mark_undeliverable("a@example.test", BounceKind.BOUNCE, "hard_bounce")
    with pytest.raises(Undeliverable):
        await adapter.send("a@example.test", "verify_email", DATA)
    assert adapter.attempts == 0


async def test_every_adapter_suppresses_a_repeated_idempotency_key(adapter: SenderBase):
    """AC-FOUND-16.3, for every adapter.

    Asserted without a delivery: the second call is refused by the store before
    the transport, so this holds for an adapter that cannot reach its provider
    in a test at all.
    """
    adapter._idempotency.remember("k", "provider-message-id")  # noqa: SLF001
    sent = await adapter.send("a@example.test", "verify_email", DATA, "k")
    assert sent == "provider-message-id"
    assert adapter.attempts == 0


@pytest.mark.parametrize("provider", sorted(ADAPTERS))
def test_every_adapter_shares_the_bounce_registry_it_was_given(provider: str):
    """The webhook writes to one registry; every adapter reads that one.

    An adapter that kept its own list would pass every test above and still send
    to a bounced address in production, because the webhook writes elsewhere -
    and marking an address *after* the sender was constructed is exactly the
    order a bounce arrives in.
    """
    registry = MemoryBounceRegistry()
    sender = build_sender(
        provider,
        sender_address="no-reply@localhost",
        product_name="JobPilot",
        bounces=registry,
    )
    registry.mark("a@example.test", BounceKind.BOUNCE)
    assert sender.is_undeliverable("a@example.test")


def test_every_adapter_knows_the_r1_template_set(adapter: SenderBase):
    for template_id in R1_TEMPLATE_IDS:
        assert template_id in adapter._registry  # noqa: SLF001


def test_every_adapter_applies_the_same_retry_rule(adapter: SenderBase):
    """AC-FOUND-16.8 lives in `SenderBase`, so a new provider cannot arrive with
    its own retry policy - or with none."""
    assert type(adapter)._deliver_with_retries is SenderBase._deliver_with_retries  # noqa: SLF001


def test_every_adapter_implements_deliver_and_nothing_else(adapter: SenderBase):
    """The design claim in one assertion: an adapter is the transport.

    `send` - which is where validation, idempotency, the bounce check, the retry
    policy and the redacted logging live - is inherited unchanged by every one.
    """
    assert type(adapter).send is SenderBase.send
    assert type(adapter).deliver is not SenderBase.deliver


def test_an_unbuilt_provider_fails_at_startup_with_the_reason():
    """A container that boots green while unable to send mail is the "up but not
    ready" state `AC-OPS-01.3` exists to prevent."""
    for provider in PLANNED_ADAPTERS:
        with pytest.raises(Exception, match="not built"):
            build_sender(provider, sender_address="no-reply@localhost", product_name="JobPilot")


def test_an_unknown_provider_names_the_ones_that_exist():
    with pytest.raises(Exception, match="not an adapter"):
        build_sender("carrier-pigeon", sender_address="no-reply@localhost", product_name="JobPilot")


def test_the_configured_provider_resolves():
    """`EMAIL_PROVIDER`'s allowed values and the adapters that exist are two
    lists, and this is the assertion that they line up."""
    from typing import get_args

    from app.core.config import Settings

    allowed = set(get_args(Settings.model_fields["EMAIL_PROVIDER"].annotation))
    assert allowed == set(ADAPTERS) - {"memory"} | set(PLANNED_ADAPTERS), (
        "EMAIL_PROVIDER accepts a value no adapter answers to, or an adapter "
        "exists that no deployment can select"
    )
