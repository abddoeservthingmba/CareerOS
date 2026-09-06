"""The R1 template set - `FOUND-16`.

`01-foundations.md` §16: "`verify_email`, `registration_attempted`,
`password_reset`, `password_changed`, `deletion_requested`,
`deletion_completed`. `NOTIF-02a` adds the reminder templates in P6; `AUTH-08`
adds `export_ready` in R2."

Two rules every template here obeys:

* **A plain-text alternative is always present.** Text-only clients and spam
  scoring both need one, and transactional mail that lands in spam fails
  silently - taking the last clause of the exit sentence with it.
* **The only personal datum is the recipient's own.** No other user's data, no
  job text, no resume text. `{{product}}` comes from `PRODUCT_NAME`
  (`README.md` §5), never a literal.

`registration_attempted` is the one that looks odd and is the most important:
`AUTH-01` is enumeration-safe, so registering an address that already exists
returns the same 202 as a fresh one and sends *this* instead of a verification
link. Without it, the response would be identical but the mailbox would not.

Deviation, recorded: §16 says "MJML compiled to HTML at build time". These are
hand-written HTML with the same inlined-style discipline MJML produces, because
adding a Node build step to the API image for six templates costs more than it
saves. If the set grows past a dozen, MJML is the right answer and the golden
tests below will catch any rendering change it introduces.
"""

from __future__ import annotations

from app.infra.email.base import Template, TemplateRegistry

_STYLE = (
    "font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;"
    "font-size:15px;line-height:1.55;color:#12312e;"
)
_BUTTON = (
    "display:inline-block;padding:10px 18px;background:#0d9488;color:#ffffff;"
    "text-decoration:none;border-radius:6px;font-weight:600;"
)


def _wrap(body: str) -> str:
    return (
        '<!doctype html><html><body style="margin:0;padding:24px;background:#f7faf9;">'
        f'<div style="{_STYLE}max-width:520px;margin:0 auto;background:#ffffff;'
        'padding:28px;border-radius:10px;">'
        f"{body}"
        '<hr style="border:none;border-top:1px solid #d9e6e3;margin:24px 0 12px;">'
        '<p style="font-size:12px;color:#4b5c5a;margin:0;">'
        "{{product}} — you are receiving this because someone used this address "
        "to sign in or sign up.</p>"
        "</div></body></html>"
    )


VERIFY_EMAIL = Template(
    template_id="verify_email",
    subject="Confirm your email for {{product}}",
    required=("product", "verify_url"),
    html=_wrap(
        "<p>Confirm this address to finish setting up your {{product}} account.</p>"
        f'<p><a href="{{{{verify_url}}}}" style="{_BUTTON}">Confirm email</a></p>'
        '<p style="font-size:13px;color:#4b5c5a;">The link expires in 24 hours. '
        "If you did not sign up, you can ignore this.</p>"
    ),
    text=(
        "Confirm this address to finish setting up your {{product}} account.\n\n"
        "{{verify_url}}\n\n"
        "The link expires in 24 hours. If you did not sign up, you can ignore this."
    ),
)

# `AUTH-01`: the existing-account branch of an enumeration-safe registration.
REGISTRATION_ATTEMPTED = Template(
    template_id="registration_attempted",
    subject="Someone tried to sign up with your email — {{product}}",
    required=("product", "reset_url"),
    html=_wrap(
        "<p>Someone just tried to create a {{product}} account with this address. "
        "You already have one, so we did not create a second.</p>"
        "<p>If that was you, sign in as usual. If you have forgotten your password, "
        f'you can reset it: <a href="{{{{reset_url}}}}" style="{_BUTTON}">Reset password</a></p>'
        '<p style="font-size:13px;color:#4b5c5a;">If it was not you, no action is '
        "needed — nothing about your account has changed.</p>"
    ),
    text=(
        "Someone just tried to create a {{product}} account with this address.\n"
        "You already have one, so we did not create a second.\n\n"
        "If that was you, sign in as usual. To reset your password:\n"
        "{{reset_url}}\n\n"
        "If it was not you, no action is needed — nothing about your account has changed."
    ),
)

PASSWORD_RESET = Template(
    template_id="password_reset",
    subject="Reset your {{product}} password",
    required=("product", "reset_url"),
    html=_wrap(
        "<p>Use the link below to set a new password.</p>"
        f'<p><a href="{{{{reset_url}}}}" style="{_BUTTON}">Set a new password</a></p>'
        '<p style="font-size:13px;color:#4b5c5a;">The link expires in 60 minutes and '
        "can be used once. If you did not ask for this, ignore it — your password "
        "has not changed.</p>"
    ),
    text=(
        "Use the link below to set a new {{product}} password.\n\n"
        "{{reset_url}}\n\n"
        "The link expires in 60 minutes and can be used once.\n"
        "If you did not ask for this, ignore it — your password has not changed."
    ),
)

# `AUTH-05`: "A confirmation email is sent on success and mentions no password
# material" (`AC-AUTH-05.5`).
PASSWORD_CHANGED = Template(
    template_id="password_changed",
    subject="Your {{product}} password was changed",
    required=("product", "changed_at"),
    html=_wrap(
        "<p>Your {{product}} password was changed on {{changed_at}}.</p>"
        "<p>Every signed-in session was ended, so you will need to sign in again.</p>"
        '<p style="font-size:13px;color:#4b5c5a;">If this was not you, reset your '
        "password immediately and contact support.</p>"
    ),
    text=(
        "Your {{product}} password was changed on {{changed_at}}.\n\n"
        "Every signed-in session was ended, so you will need to sign in again.\n\n"
        "If this was not you, reset your password immediately and contact support."
    ),
)

# `AUTH-07`: the two-phase deletion, with its 7-day clock stated.
DELETION_REQUESTED = Template(
    template_id="deletion_requested",
    subject="Your {{product}} account will be deleted on {{delete_on}}",
    required=("product", "delete_on", "cancel_url"),
    html=_wrap(
        "<p>You asked us to delete your {{product}} account. Everything will be "
        "removed on <strong>{{delete_on}}</strong>.</p>"
        "<p>Until then the account is inaccessible, and nothing new is processed — "
        "no scoring, no reminders.</p>"
        f'<p><a href="{{{{cancel_url}}}}" style="{_BUTTON}">Cancel the deletion</a></p>'
        '<p style="font-size:13px;color:#4b5c5a;">Backups made before today age out '
        "within 14 days.</p>"
    ),
    text=(
        "You asked us to delete your {{product}} account.\n"
        "Everything will be removed on {{delete_on}}.\n\n"
        "Until then the account is inaccessible, and nothing new is processed —\n"
        "no scoring, no reminders.\n\n"
        "To cancel:\n{{cancel_url}}\n\n"
        "Backups made before today age out within 14 days."
    ),
)

DELETION_COMPLETED = Template(
    template_id="deletion_completed",
    subject="Your {{product}} account has been deleted",
    required=("product",),
    html=_wrap(
        "<p>Your {{product}} account and everything in it have been deleted.</p>"
        "<p>We have kept no copy. This message is the last one you will receive.</p>"
    ),
    text=(
        "Your {{product}} account and everything in it have been deleted.\n\n"
        "We have kept no copy. This message is the last one you will receive."
    ),
)

R1_TEMPLATES = (
    VERIFY_EMAIL,
    REGISTRATION_ATTEMPTED,
    PASSWORD_RESET,
    PASSWORD_CHANGED,
    DELETION_REQUESTED,
    DELETION_COMPLETED,
)

#: `01-foundations.md` §16's R1 set, by id.
R1_TEMPLATE_IDS = tuple(template.template_id for template in R1_TEMPLATES)


def build_registry() -> TemplateRegistry:
    registry = TemplateRegistry(list(R1_TEMPLATES))
    registry.validate()
    return registry


__all__ = ["R1_TEMPLATES", "R1_TEMPLATE_IDS", "build_registry"]
