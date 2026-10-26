import logging

from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.utils import timezone
from urllib.parse import urlencode

from rest_framework.decorators import api_view, authentication_classes, throttle_classes
from rest_framework.throttling import SimpleRateThrottle
from rest_framework.response import Response
from rest_framework import status
from .models import CoupleSession, Question, CustomQuestion, questions_cache_version
from .serializers import CustomQuestionSerializer, LoginSerializer

logger = logging.getLogger(__name__)


class LoginRateThrottle(SimpleRateThrottle):
    """Limits login attempts per client IP (rate set in settings)."""

    scope = "login"

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}


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
def get_questions(request, mode):
    if mode not in VALID_MODES:
        return Response({"detail": "Unknown game mode."}, status=400)

    secret_word = request.GET.get("secret")
    try:
        session = CoupleSession.objects.get(secret_word=secret_word)
    except CoupleSession.DoesNotExist:
        return Response([], status=200)  # Return empty array if session not found
    session.touch()

    # Keyed by session id so the secret never ends up in the cache.
    cache_key = f"questions:{questions_cache_version()}:{mode}:{session.pk}"
    cached_questions = cache.get(cache_key)
    if cached_questions is not None:
        return Response(cached_questions)

    if mode == "mixed":
        admin_qs = Question.objects.all()
        # Custom questions for the specific couple session
        custom_qs = CustomQuestion.objects.filter(couple=session)
    else:
        admin_qs = Question.objects.filter(mode=mode)
        custom_qs = CustomQuestion.objects.filter(couple=session, mode=mode)

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
    return Response(combined_data)


@api_view(["POST"])
# Requests are authorised by the submitted secret, not a Django login, so
# session authentication (and its CSRF check for logged-in users) is skipped.
@authentication_classes([])
def add_custom_question(request):
    serializer = CustomQuestionSerializer(data=request.data)
    if not serializer.is_valid():
        # Log field names only: error messages can echo submitted values.
        logger.warning("Invalid custom question; fields: %s", sorted(serializer.errors))
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    data = serializer.validated_data
    session = CoupleSession.objects.filter(secret_word=data["secret"]).first()
    if session is None:
        return Response({"detail": "Session not found."}, status=status.HTTP_404_NOT_FOUND)
    session.touch()

    # Saving bumps the questions cache version (see models.py), so the new
    # question shows up on the couple's next question load.
    question = CustomQuestion.objects.create(couple=session, text=data["text"], mode=data["mode"])
    return Response(
        {"text": question.text, "mode": question.mode, "is_custom": True},
        status=status.HTTP_201_CREATED,
    )


@api_view(["GET"])
def check_session(request):
    secret = request.GET.get("secret")
    if not secret:
        return Response({"valid": False})

    # Read-only: expired sessions are deleted by purge_inactive_sessions,
    # never as a side effect of a GET request.
    session = CoupleSession.objects.filter(secret_word=secret).first()
    return Response({"valid": bool(session and not session.is_expired())})


def login_page(request):
    return render(request, "game/login.html")


def mode_select_page(request):
    return render(request, "game/mode_select.html")


def play_page(request):
    return render(request, "game/play.html")
