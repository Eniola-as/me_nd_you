from django.conf import settings
from django.core.checks import Tags, Warning, register


@register(Tags.security, deploy=True)
def check_email_delivery(app_configs, **kwargs):
    """Production must send real mail through a provider's HTTPS API."""
    if not settings.EMAIL_PROVIDER:
        return [
            Warning(
                "EMAIL_PROVIDER is not set, so verification and password reset "
                "emails are printed to the console instead of being sent.",
                hint="Set EMAIL_PROVIDER (brevo, resend or postmark) and EMAIL_API_KEY.",
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
