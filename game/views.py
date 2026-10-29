import logging
from functools import wraps

from django.contrib.staticfiles import finders
from django.http import HttpResponse
from django.views.decorators.cache import cache_control
from django.views.decorators.http import require_GET

from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import SimpleRateThrottle, UserRateThrottle

from couples.services import active_couple
from notifications import services as notifications
from play import modes
from play.services import add_custom_card

from .models import CustomQuestion
from .serializers import QuestionInputSerializer
from .truth_or_dare import MODE as TRUTH_OR_DARE, classify

logger = logging.getLogger(__name__)


class ClientRateThrottle(SimpleRateThrottle):
    """Per-client limit for one scope (rates are set in settings).

    Clients are identified by address (see REST_FRAMEWORK["NUM_PROXIES"]).
    Counts live in Django's default cache, which is in-memory and therefore
    per process: a scaled deployment needs a shared cache for these to hold.
    """

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}


class SpaceCustomQuestionRateThrottle(UserRateThrottle):
    scope = "space_custom_questions"


class SpaceModeRateThrottle(UserRateThrottle):
    scope = "space_mode"


NOT_IN_COUPLE = {"detail": "Join a couple first."}


@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
@throttle_classes([SpaceModeRateThrottle])
def space_mode(request):
    """The couple's shared game mode (play.modes): GET it, or POST
    {"action": "start"|"request"|"accept"|"decline"|"cancel", "mode", "version"}.
    A stale version answers 409 with the latest state."""
    couple = active_couple(request.user)
    if couple is None:
        return Response(NOT_IN_COUPLE, status=status.HTTP_403_FORBIDDEN)
    if request.method == "GET":
        return Response(modes.snapshot(couple, request.user))
    action, mode, version = request.data.get("action"), request.data.get("mode"), request.data.get("version")
    try:
        if action == "start":
            state = modes.start(request.user, mode)
        elif not isinstance(version, int):
            return Response({"detail": "Send the version you last saw."}, status=status.HTTP_400_BAD_REQUEST)
        elif action == "request":
            state = modes.request_switch(request.user, mode, version)
        elif action in ("accept", "decline"):
            state = modes.respond(request.user, action == "accept", version)
        elif action == "cancel":
            state = modes.cancel(request.user, version)
        else:
            return Response({"detail": "Unknown action."}, status=status.HTTP_400_BAD_REQUEST)
    except modes.Stale as stale:
        return Response({"detail": "The mode changed.", "state": stale.snapshot}, status=status.HTTP_409_CONFLICT)
    except modes.Invalid as error:
        return Response({"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST)
    except modes.Forbidden:
        return Response(NOT_IN_COUPLE, status=status.HTTP_403_FORBIDDEN)
    return Response(state)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@throttle_classes([SpaceCustomQuestionRateThrottle])
def add_space_custom_question(request):
    """Add a question to the signed-in user's couple space. Session
    authentication enforces the CSRF token."""
    couple = active_couple(request.user)
    if couple is None:
        return Response(NOT_IN_COUPLE, status=status.HTTP_403_FORBIDDEN)
    serializer = QuestionInputSerializer(data=request.data)
    if not serializer.is_valid():
        logger.warning("Invalid space question; fields: %s", sorted(serializer.errors))
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    data = serializer.validated_data
    current = modes.current_mode(request.user)
    if current not in (None, "mixed", data["mode"]):
        return Response({"mode": ["Add prompts to the mode you're playing."]}, status=status.HTTP_400_BAD_REQUEST)
    kind = ""
    if data["mode"] == TRUTH_OR_DARE:
        kind = data.get("kind") or classify(data["text"])
    question = CustomQuestion.objects.create(
        space=couple, text=data["text"], mode=data["mode"], kind=kind, author=request.user
    )
    # Server-authoritative rooms get it too, so both partners see it once.
    add_custom_card(question)
    return Response(
        {"text": question.text, "mode": question.mode, "is_custom": True},
        status=status.HTTP_201_CREATED,
    )


def landing_page(request):
    # Signed-in people belong on their space page: it shows their couple,
    # or how to start or join one.
    if request.user.is_authenticated:
        return redirect("/space/")
    return render(request, "game/landing.html")


def couple_member_required(view):
    """Signed in (else sign in first) and in a couple (else the space page,
    where they can start or join one)."""

    @wraps(view)
    @login_required
    def wrapped(request, *args, **kwargs):
        if active_couple(request.user) is None:
            return redirect("/space/")
        return view(request, *args, **kwargs)

    return wrapped


@couple_member_required
@ensure_csrf_cookie  # The mode API needs the CSRF token for POSTs.
def mode_select_page(request):
    return render(request, "game/mode_select.html", modes.page_context(request.user))


@couple_member_required
@ensure_csrf_cookie  # The custom-question and mode APIs need the CSRF token.
def play_page(request):
    """The couple's current mode. With none set yet, the mode opened starts
    for both; another mode's link shows the current one (switching is a
    request the partner accepts, from the mode menu)."""
    mode = request.GET.get("mode")
    if mode not in modes.MODE_GAMES:
        return redirect("/modes/")
    current = modes.current_mode(request.user)
    if current is None:
        current = modes.start(request.user, mode)["mode"]
    if current != mode:
        return redirect(f"/play/?mode={current}")
    # Opening the game shows what these said (who answered, what's playing).
    for kind in (notifications.ANSWERED, notifications.REVEALED, notifications.MODE_SWITCHED):
        notifications.mark_read(request.user, kind=kind, mode=mode)
    return render(request, "game/play.html", {**modes.page_context(request.user), "game": modes.MODE_GAMES[mode]})


@require_GET
@cache_control(no_cache=True)
def service_worker(request):
    """static/service-worker.js, served from the root so its scope is the
    whole site. Browsers re-check it on every visit (no-cache)."""
    with open(finders.find("service-worker.js"), encoding="utf-8") as source:
        return HttpResponse(source.read(), content_type="application/javascript")


@require_GET
def offline_page(request):
    """What the service worker shows when a page can't load. Never personal."""
    return render(request, "game/offline.html")
