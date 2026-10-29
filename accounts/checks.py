from django.conf import settings
from django.core.checks import Error, Tags, Warning, register


@register(Tags.security, deploy=True)
def check_email_delivery(app_configs, **kwargs):
    """Production must send real mail through a provider's HTTPS API."""
    if not settings.EMAIL_PROVIDER:
        return [
            Warning(
                "EMAIL_PROVIDER is not set; account email delivery is disabled.",
                hint="Email verification, password reset and account email notices are unavailable until a provider is configured.",
                id="accounts.W001",
            )
        ]
    warnings = []
    if not settings.EMAIL_API_KEY:
        warnings.append(
            Warning(
                f"EMAIL_PROVIDER is {settings.EMAIL_PROVIDER} but EMAIL_API_KEY is not set.",
                hint="Set EMAIL_API_KEY to the provider's API key.",
                id="accounts.W002",
            )
        )
    if not settings.DEFAULT_FROM_EMAIL_ADDRESS:
        warnings.append(
            Warning(
                "DEFAULT_FROM_EMAIL is not set, so mail would come from no-reply@localhost.",
                hint="Set DEFAULT_FROM_EMAIL to an address the provider lets you send from.",
                id="accounts.W003",
            )
        )
    return warnings


def published_notice_text():
    """The privacy notice as it is published (accounts/privacy.html), with
    the settings filled in, so only notes that would actually show count."""
    from django.template import Context, Template, loader

    from .legal import email_provider_name

    source = loader.get_template("accounts/privacy.html").template.source
    body = source[source.index("{% block content %}") + len("{% block content %}"):source.rindex("{% endblock %}")]
    return Template(body).render(Context({
        "contact_email": settings.PRIVACY_CONTACT_EMAIL,
        "policy_version": settings.POLICY_VERSION,
        "email_provider": email_provider_name(),
        "is_draft": "draft" in settings.POLICY_VERSION.lower(),
    }))


@register(Tags.security, deploy=True)
def check_policy(app_configs, **kwargs):
    """Deploy safety (owner, 2026-10-29): never deploy with DEBUG off while
    the policy is a draft, the published notice still has open notes, or
    there's no privacy contact. Local development isn't blocked."""
    if settings.DEBUG:
        return []
    errors = []
    if "draft" in settings.POLICY_VERSION.lower():
        errors.append(Error(
            f"POLICY_VERSION is a draft ({settings.POLICY_VERSION}).",
            hint="Set the final version in me_nd_you/settings.py once the policy text is final.",
            id="accounts.E001",
        ))
    text = published_notice_text()
    for marker, error_id in (("[CHECK", "accounts.E002"), ("[DEPENDS ON", "accounts.E003")):
        count = text.count(marker)
        if count:
            errors.append(Error(
                f"The published privacy notice still has {count} {marker}] note(s).",
                hint="Confirm each fact and replace its note in the notice (accounts/templates/accounts/privacy.html).",
                id=error_id,
            ))
    if not settings.PRIVACY_CONTACT_EMAIL:
        errors.append(Error(
            "PRIVACY_CONTACT_EMAIL is not set, so the privacy notice shows no contact address.",
            hint="Set PRIVACY_CONTACT_EMAIL to the address that answers privacy requests.",
            id="accounts.E004",
        ))
    return errors
