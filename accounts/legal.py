"""Facts the beta privacy notice and the sign-up consents both state, from
one place so they can't drift apart."""

from django.conf import settings

EMAIL_PROVIDER_NAMES = {"brevo": "Brevo", "resend": "Resend", "postmark": "Postmark"}


def email_provider_name():
    """The configured email provider's name, or "" while none is chosen."""
    return EMAIL_PROVIDER_NAMES.get(settings.EMAIL_PROVIDER, "")
