import logging

from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.utils import timezone
from urllib.parse import urlencode

from django.views.decorators.csrf import ensure_csrf_cookie
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    permission_classes,
    throttle_classes,
)
from rest_framework.permissions import IsAuthenticated
from rest_framework.throttling import SimpleRateThrottle, UserRateThrottle

from couples.services import active_couple
from play.services import add_custom_card
from rest_framework.response import Response
from rest_framework import status
from .models import CoupleSession, Question, CustomQuestion, questions_cache_version
from .serializers import CustomQuestionSerializer, LoginSerializer, QuestionInputSerializer

logger = logging.getLogger(__name__)


class ClientRateThrottle(SimpleRateThrottle):
    """Per-client limit for one scope (rates are set in settings).

    Clients are identified by address (see REST_FRAMEWORK["NUM_PROXIES"]).
    Counts live in Django's default cache, which is in-memory and therefore
    per process: a scaled deployment needs a shared cache for these to hold.
    """

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}


class LoginRateThrottle(ClientRateThrottle):
    scope = "login"


class QuestionsRateThrottle(ClientRateThrottle):
    scope = "questions"


class CustomQuestionRateThrottle(ClientRateThrottle):
    scope = "custom_questions"


class SpaceQuestionsRateThrottle(UserRateThrottle):
    """Per signed-in user (per address for anonymous requests)."""

    scope = "space_questions"


class SpaceCustomQuestionRateThrottle(UserRateThrottle):
    scope = "space_custom_questions"


@csrf_exempt
@api_view(["POST"])
@throttle_classes([LoginRateThrottle])
def login_or_register(request):
    serializer = LoginSerializer(data=request.data)
    if not serializer.is_valid():
        field_keys = {
            "partner1_name": "partner1",
            "partner2_name": "partner2",
            "secret_word": "secret",
        }
        return Response(
            {
                "success": False,
                "detail": "Please check the highlighted fields.",
                "errors": {
                    field_keys.get(field, field): " ".join(str(m) for m in messages)
                    for field, messages in serializer.errors.items()
                },
            },
            status=400,
        )
    partner1_name = serializer.validated_data["partner1_name"]
    partner2_name = serializer.validated_data["partner2_name"]
    secret_word = serializer.validated_data["secret_word"]

    # Sort names for matching
    names = sorted([partner1_name.casefold(), partner2_name.casefold()])

    try:
        session = CoupleSession.objects.get(secret_word=secret_word)
        stored_names = sorted(
            [
                session.partner1_name.casefold(),
                session.partner2_name.casefold(),
            ]
        )
        if names != stored_names:
            return Response(
                {
                    "success": False,
                    "detail": (
                        "This secret word is already in use by another couple. "
                        "If this is your session, please enter the same names you used before. "
                        "Otherwise, choose a different secret word."
                    ),
                },
                status=400,
            )
    except CoupleSession.DoesNotExist:
        # Create new session
        try:
            with transaction.atomic():
                session = CoupleSession.objects.create(
                    partner1_name=partner1_name,
                    partner2_name=partner2_name,
                    secret_word=secret_word,
                )
        except IntegrityError:
            # Another request claimed this secret between our lookup and insert.
            return Response(
                {
                    "success": False,
                    "detail": "This secret word was just taken. Please try again.",
                },
                status=409,
            )

    session.touch()
    return Response(
        {
            "success": True,
            "redirect": f"/modes/?{urlencode({'secret': secret_word})}",
            "session": {
                "id": str(session.id),
                "secret": secret_word,
                "names": [session.partner1_name, session.partner2_name],
                "timestamp": timezone.now().timestamp(),
            },
        }
    )


VALID_MODES = {value for value, _ in Question.MODES}


@api_view(["GET"])
@throttle_classes([QuestionsRateThrottle])
def get_questions(request, mode):
    if mode not in VALID_MODES:
        return Response({"detail": "Unknown game mode."}, status=400)

    session = CoupleSession.find_active(request.GET.get("secret"))
    if session is None:
        return Response([], status=200)  # Unknown or expired: same answer.
    session.touch()
    # Keyed by session id so the secret never ends up in the cache.
    return Response(
        question_list(mode, CustomQuestion.objects.filter(couple=session), f"session:{session.pk}")
    )


def question_list(mode, custom_qs, owner_key):
    """The admin questions for a mode plus an owner's custom questions,
    cached per owner. Saving any question bumps the cache version."""
    cache_key = f"questions:{questions_cache_version()}:{mode}:{owner_key}"
    cached_questions = cache.get(cache_key)
    if cached_questions is not None:
        return cached_questions

    admin_qs = Question.objects.all()
    if mode != "mixed":
        admin_qs = admin_qs.filter(mode=mode)
        custom_qs = custom_qs.filter(mode=mode)

    # Stable order: the client shuffles with a seed shared by both partners.
    all_questions = list(admin_qs.order_by("pk")) + list(custom_qs.order_by("created_at"))

    # The client tracks seen questions by text, so list each text once.
    combined_data = []
    seen_texts = set()
    for q in all_questions:
        key = q.text.strip().casefold()
        if key in seen_texts:
            continue
        seen_texts.add(key)
        combined_data.append(
            {"text": q.text, "mode": q.mode, "is_custom": isinstance(q, CustomQuestion)}
        )

    # Cache the results for 1 hour
    cache.set(cache_key, combined_data, timeout=3600)
    return combined_data


NOT_IN_COUPLE = {"detail": "Join a couple first."}


@api_view(["GET"])
@permission_classes([IsAuthenticated])
@throttle_classes([SpaceQuestionsRateThrottle])
def get_space_questions(request, mode):
    """Questions for the signed-in user's own couple space. The couple comes
    from the session's user, never from the request."""
    if mode not in VALID_MODES:
        return Response({"detail": "Unknown game mode."}, status=400)
    couple = active_couple(request.user)
    if couple is None:
        return Response(NOT_IN_COUPLE, status=status.HTTP_403_FORBIDDEN)
    return Response(
        question_list(mode, CustomQuestion.objects.filter(space=couple), f"space:{couple.pk}")
    )


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
    question = CustomQuestion.objects.create(space=couple, text=data["text"], mode=data["mode"])
    # Server-authoritative rooms get it too, so both partners see it once.
    add_custom_card(question)
    return Response(
        {"text": question.text, "mode": question.mode, "is_custom": True},
        status=status.HTTP_201_CREATED,
    )


@api_view(["POST"])
# Requests are authorised by the submitted secret, not a Django login, so
# session authentication (and its CSRF check for logged-in users) is skipped.
@authentication_classes([])
@throttle_classes([CustomQuestionRateThrottle])
def add_custom_question(request):
    serializer = CustomQuestionSerializer(data=request.data)
    if not serializer.is_valid():
        # Log field names only: error messages can echo submitted values.
        logger.warning("Invalid custom question; fields: %s", sorted(serializer.errors))
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    data = serializer.validated_data
    session = CoupleSession.find_active(data["secret"])
    if session is None:  # Unknown or expired: same answer.
        return Response({"detail": "Session not found."}, status=status.HTTP_404_NOT_FOUND)
    session.touch()

    # Saving bumps the questions cache version (see models.py), so the new
    # question shows up on the couple's next question load.
    question = CustomQuestion.objects.create(couple=session, text=data["text"], mode=data["mode"])
    return Response(
        {"text": question.text, "mode": question.mode, "is_custom": True},
        status=status.HTTP_201_CREATED,
    )


def login_page(request):
    return render(request, "game/login.html")


def mode_select_page(request):
    return render(request, "game/mode_select.html", {"in_space": in_space(request)})


@ensure_csrf_cookie  # The space API needs the CSRF token for POSTs.
def play_page(request):
    return render(request, "game/play.html", {"in_space": in_space(request)})


def in_space(request):
    """Whether the page should play in the user's couple space rather than
    with a secret word from the URL."""
    return active_couple(request.user) is not None
