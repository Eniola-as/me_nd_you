import logging
from functools import wraps

from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import SimpleRateThrottle, UserRateThrottle

from couples.services import active_couple
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


NOT_IN_COUPLE = {"detail": "Join a couple first."}


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
    kind = ""
    if data["mode"] == TRUTH_OR_DARE:
        kind = data.get("kind") or classify(data["text"])
    question = CustomQuestion.objects.create(space=couple, text=data["text"], mode=data["mode"], kind=kind)
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
def mode_select_page(request):
    return render(request, "game/mode_select.html")


@couple_member_required
@ensure_csrf_cookie  # The custom-question API needs the CSRF token for POSTs.
def play_page(request):
    return render(request, "game/play.html")
