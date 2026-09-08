"""T-FOUND-16.2 - the template registry, validated at startup.

`AC-FOUND-16.2`: "A `send` missing a required `data` key raises before any
provider call."

`01-foundations.md` §16: "Each template declares its `template_id`, its required
`data` keys, and its subject." A template rendering `Hello {name}` as
`Hello None` is worse than a failed send, because it goes out.
"""

from __future__ import annotations

import pytest

from app.infra.email.base import (
    EmailError,
    MissingTemplateData,
    Template,
    TemplateRegistry,
    UnknownTemplate,
)
from app.infra.email.templates import R1_TEMPLATE_IDS, build_registry


def test_the_r1_set_is_the_one_the_spec_names():
    """§16 - the six templates P1 and AUTH-07 need."""
    assert set(R1_TEMPLATE_IDS) == {
        "verify_email",
        "registration_attempted",
        "password_reset",
        "password_changed",
        "deletion_requested",
        "deletion_completed",
    }


def test_the_registry_validates_at_startup():
    """A malformed template fails the boot, not the first send."""
    build_registry()  # raises if anything is wrong


def test_a_missing_key_raises_before_any_send():
    """AC-FOUND-16.2."""
    template = build_registry().get("verify_email")
    with pytest.raises(MissingTemplateData) as caught:
        template.render({"product": "JobPilot"})
    assert caught.value.missing == ["verify_url"]
    assert "verify_email" in str(caught.value)


def test_an_empty_value_counts_as_missing():
    """A blank where a URL should be is the failure this prevents."""
    template = build_registry().get("verify_email")
    with pytest.raises(MissingTemplateData):
        template.render({"product": "JobPilot", "verify_url": ""})
    with pytest.raises(MissingTemplateData):
        template.render({"product": "JobPilot", "verify_url": None})


def test_an_unknown_template_names_the_ones_that_exist():
    registry = build_registry()
    with pytest.raises(UnknownTemplate) as caught:
        registry.get("verrify_email")
    assert "verify_email" in str(caught.value), "the message should help with the typo"


def test_a_template_without_plain_text_is_refused():
    """§16 - "a plain-text alternative is **required**"."""
    registry = TemplateRegistry([Template("bare", "Subject {{a}}", ("a",), "<p>{{a}}</p>", "   ")])
    with pytest.raises(EmailError, match="plain-text"):
        registry.validate()


def test_a_template_using_an_undeclared_key_is_refused():
    """Otherwise the key silently renders as a literal `{{name}}` in someone's
    inbox."""
    registry = TemplateRegistry(
        [Template("leaky", "Hi {{name}}", (), "<p>{{name}}</p>", "Hi {{name}}")]
    )
    with pytest.raises(EmailError, match="undeclared"):
        registry.validate()


def test_a_template_declaring_a_key_it_never_uses_is_refused():
    """A caller passing it would reasonably expect it to appear."""
    registry = TemplateRegistry([Template("unused", "Hello", ("name",), "<p>Hello</p>", "Hello")])
    with pytest.raises(EmailError, match="declares"):
        registry.validate()


def test_a_duplicate_template_id_is_refused():
    template = Template("dupe", "S {{a}}", ("a",), "<p>{{a}}</p>", "{{a}}")
    with pytest.raises(EmailError, match="twice"):
        TemplateRegistry([template, template])


def test_rendering_substitutes_every_placeholder():
    subject, html, text = (
        build_registry()
        .get("password_reset")
        .render({"product": "JobPilot", "reset_url": "https://example.test/reset/abc"})
    )
    assert "JobPilot" in subject
    for rendering in (html, text):
        assert "https://example.test/reset/abc" in rendering
        assert "{{" not in rendering, "an unsubstituted placeholder reached the body"
