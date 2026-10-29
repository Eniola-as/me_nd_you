import json

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import redirect
from django.views.decorators.http import require_GET, require_POST

from . import services
from .models import Notification, PushSubscription

MAX_DEVICES = 10  # Per person; the oldest goes first.


def _signed_in_json(view):
    def wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({"detail": "Sign in first."}, status=403)
        return view(request, *args, **kwargs)

    return wrapped


@require_GET
@_signed_in_json
def notification_list(request):
    """This person's notifications in their current space (never anyone
    else's, and never any message or answer text)."""
    items = [{"id": n["id"], "text": n["text"], "url": n["url"], "unread": n["unread"], "at": n["at"].isoformat()}
             for n in services.recent(request.user)]
    return JsonResponse({"unread": services.unread_count(request.user), "items": items})


@login_required
@require_POST
def open_notification(request, notification_id):
    note = Notification.objects.filter(pk=notification_id, user=request.user).first()
    if note is None:
        raise Http404()
    services.mark_read(request.user, ids=[note.pk])
    return redirect(services.url_for(note.kind, note.mode))


@login_required
@require_POST
def read_all(request):
    services.mark_read(request.user)
    return redirect("/space/#notifications")


def _json_body(request):
    try:
        body = json.loads(request.body or b"{}")
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


@require_POST
@_signed_in_json
def push_subscribe(request):
    """Store this device's push subscription for the signed-in person. A
    device someone else turned on before moves to this person."""
    body = _json_body(request)
    endpoint, keys = body.get("endpoint"), body.get("keys")
    valid = (isinstance(endpoint, str) and endpoint.startswith("https://") and len(endpoint) <= 1000
             and isinstance(keys, dict) and all(isinstance(keys.get(k), str) and 0 < len(keys[k]) <= 200
                                                for k in ("p256dh", "auth")))
    if not valid:
        return JsonResponse({"detail": "That isn't a push subscription."}, status=400)
    with transaction.atomic():
        PushSubscription.objects.update_or_create(
            endpoint=endpoint, defaults={"user": request.user, "p256dh": keys["p256dh"], "auth": keys["auth"]},
        )
        extra = PushSubscription.objects.filter(user=request.user).order_by("-created_at")[MAX_DEVICES:]
        PushSubscription.objects.filter(pk__in=list(extra.values_list("pk", flat=True))).delete()
    return JsonResponse({"ok": True}, status=201)


@require_POST
@_signed_in_json
def push_unsubscribe(request):
    endpoint = _json_body(request).get("endpoint")
    if isinstance(endpoint, str):
        PushSubscription.objects.filter(user=request.user, endpoint=endpoint).delete()
    return HttpResponse(status=204)


@require_GET
def push_key(request):
    """The public VAPID key browsers need to subscribe (empty: push is off)."""
    return JsonResponse({"key": settings.VAPID_PUBLIC_KEY or ""})
