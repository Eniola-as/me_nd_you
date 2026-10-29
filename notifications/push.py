"""Web Push: an alert on a member's devices when something new happens while
they're not in the app (even with it closed, where the browser supports it:
on iPhone only for the app added to the home screen, iOS 16.4+).

Needs VAPID keys in the environment (VAPID_PUBLIC_KEY, VAPID_PRIVATE_KEY;
`python manage.py generate_vapid_keys`). Without them push is off and
everything else works. Delivery is up to each browser's push service, so it
isn't guaranteed. The text never has names or content."""

import json
import logging
import threading

from django.conf import settings
from django.db import connections
from pywebpush import WebPushException, webpush

from .models import PushSubscription

logger = logging.getLogger(__name__)

# Push services need an answer within a few seconds; a slow one shouldn't
# hold a thread for long.
TIMEOUT_SECONDS = 10
TTL_SECONDS = 24 * 60 * 60  # Not delivered within a day: drop it.
GONE = {404, 410}  # The browser unsubscribed: forget the device.


def enabled():
    return bool(settings.VAPID_PUBLIC_KEY and settings.VAPID_PRIVATE_KEY)


def run(fn):
    """Send off the request thread, so a slow push service never slows the
    app (tests replace this to run straight away)."""

    def target():
        try:
            fn()
        finally:
            connections.close_all()  # This thread's own database connection.

    threading.Thread(target=target, daemon=True).start()


def notify_user(user_id, kind, url):
    from chat import presence

    from .services import PUSH_TEXT

    if not enabled():
        return
    # In the app right now: they see it there, so no alert.
    if presence.status(user_id)["online"]:
        return
    subscriptions = list(PushSubscription.objects.filter(user_id=user_id))
    if not subscriptions:
        return
    payload = json.dumps({"title": "Me & You", "body": PUSH_TEXT.get(kind, "Something new in your space."),
                          "url": url, "tag": kind})
    run(lambda: _send_all(subscriptions, payload))


def _send_all(subscriptions, payload):
    for subscription in subscriptions:
        try:
            webpush(
                subscription_info={"endpoint": subscription.endpoint,
                                   "keys": {"p256dh": subscription.p256dh, "auth": subscription.auth}},
                data=payload,
                vapid_private_key=settings.VAPID_PRIVATE_KEY,
                vapid_claims={"sub": settings.VAPID_SUBJECT},
                ttl=TTL_SECONDS,
                timeout=TIMEOUT_SECONDS,
            )
        except WebPushException as error:
            status = getattr(error.response, "status_code", None)
            if status in GONE:
                PushSubscription.objects.filter(pk=subscription.pk).delete()
            else:
                logger.warning("A push notification couldn't be sent (status %s).", status)
        except Exception:  # A push must never break anything else.
            logger.exception("A push notification couldn't be sent.")
