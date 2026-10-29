"""Account emails. Each is plain text with a minimal HTML version (inline
styles, no images or tracking). Links carry their token after "#", which
browsers never send, so tokens stay out of server and proxy logs."""

import logging
import threading

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import signing
from django.core.cache import cache
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils import timezone

logger = logging.getLogger(__name__)

VERIFY_SALT = "accounts.verify-email"
MAX_TOKEN_LENGTH = 500
# One verification email per account per 2 minutes. Like the rate limits,
# this is counted in the (per-process) cache.
RESEND_COOLDOWN = 120

# At most one "someone tried to sign up with your email" alert per account
# per day (per process, like the rest).
SIGNUP_ALERT_COOLDOWN = 24 * 60 * 60

SENT, COOLDOWN, ALREADY_VERIFIED, FAILED = "sent", "cooldown", "already_verified", "failed"
DISABLED = "disabled"


class EmailDeliveryDisabled(RuntimeError):
    """Raised if code tries to send an account email without a provider."""


def send_account_email(user, template, context):
    """Render accounts/email/<template>{_subject.txt,.txt,.html} and send
    them to the user, from DEFAULT_FROM_EMAIL."""
    if not settings.EMAIL_ENABLED:
        raise EmailDeliveryDisabled("Account email delivery is disabled until a provider is configured.")
    context = {"user": user, **context}
    subject = render_to_string(f"accounts/email/{template}_subject.txt", context).strip()
    body = render_to_string(f"accounts/email/{template}.txt", context)
    message = EmailMultiAlternatives(subject, body, None, [user.email])
    message.attach_alternative(render_to_string(f"accounts/email/{template}.html", context), "text/html")
    message.send()


def send_in_background(user, template, context):
    """Send from a background thread, so the response doesn't wait for the
    provider and takes the same time whether or not an email goes out."""
    if not settings.EMAIL_ENABLED:
        return

    def run():
        try:
            send_account_email(user, template, context)
        except Exception:
            logger.exception("Could not send a %s email.", template)

    threading.Thread(target=run, name="account-email", daemon=True).start()


def verification_token(user):
    # Bound to the address, so the link stops working if it ever changes.
    return signing.dumps({"user": user.pk, "email": user.email}, salt=VERIFY_SALT)


def user_for_verification_token(token):
    """The user a valid, unexpired token was made for, or None."""
    if not token or len(token) > MAX_TOKEN_LENGTH:
        return None
    try:
        data = signing.loads(token, salt=VERIFY_SALT, max_age=settings.EMAIL_VERIFICATION_TIMEOUT)
    except signing.BadSignature:  # Includes expired tokens.
        return None
    if not isinstance(data, dict):
        return None
    return get_user_model().objects.filter(pk=data.get("user"), email=data.get("email")).first()


def mark_verified(user):
    """Record the first verification; later ones keep that time."""
    get_user_model().objects.filter(pk=user.pk, email_verified_at__isnull=True).update(
        email_verified_at=timezone.now()
    )


def send_verification_email(request, user):
    if not settings.EMAIL_ENABLED:
        return DISABLED
    if user.email_verified_at:
        return ALREADY_VERIFIED
    cooldown_key = f"accounts:verification-sent:{user.pk}"
    if not cache.add(cooldown_key, True, RESEND_COOLDOWN):
        return COOLDOWN
    link = request.build_absolute_uri("/accounts/verify/") + "#" + verification_token(user)
    try:
        send_account_email(user, "verify", {"link": link})
    except Exception:
        cache.delete(cooldown_key)  # Let them try again straight away.
        logger.exception("Could not send a verification email.")
        return FAILED
    return SENT


def send_signup_alert(request, user):
    """Tell the owner that someone tried to sign up with their email. Sent
    in the background, and never to deactivated accounts."""
    if (
        not settings.EMAIL_ENABLED
        or not user.is_active
        or not cache.add(f"accounts:signup-alert:{user.pk}", True, SIGNUP_ALERT_COOLDOWN)
    ):
        return
    link = request.build_absolute_uri("/accounts/password/reset/")
    send_in_background(user, "signup_attempt", {"link": link})
