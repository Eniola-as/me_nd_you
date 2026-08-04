from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.utils import timezone
from datetime import timedelta

# Create your views here.
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
from .models import CoupleSession, Question, CustomQuestion
from .models import CoupleSession

from .serializers import (
    QuestionSerializer,
    CustomQuestionSerializer,
    CoupleSessionSerializer,
)


@csrf_exempt
@api_view(["POST"])
def login_or_register(request):
    partner1_name = request.data.get("partner1_name")
    partner2_name = request.data.get("partner2_name")
    secret_word = request.data.get("secret_word")

    if not all([partner1_name, partner2_name, secret_word]):
        return Response(
            {
                "success": False,
                "detail": "Please fill in all fields before continuing.",
            },
            status=400,
        )

    # Sort names for matching
    names = sorted([partner1_name.strip().lower(), partner2_name.strip().lower()])

    try:
        session = CoupleSession.objects.get(secret_word=secret_word)
        stored_names = sorted(
            [
                session.partner1_name.strip().lower(),
                session.partner2_name.strip().lower(),
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
        session = CoupleSession.objects.create(
            partner1_name=partner1_name,
            partner2_name=partner2_name,
            secret_word=secret_word,
        )

    return Response(
        {
            "success": True,
            "redirect": f"/modes/?secret={secret_word}",
            "session": {
                "id": str(session.id),
                "secret": secret_word,
                "names": [session.partner1_name, session.partner2_name],
                "timestamp": timezone.now().timestamp(),
            },
        }
    )


from django.db.models import Q
import random


@api_view(["GET"])
def get_questions(request, mode):
    secret_word = request.GET.get("secret")

    # Try fetching from cache first
    cache_key = f"questions_{mode}_{secret_word}"
    cached_questions = cache.get(cache_key)
    if cached_questions:
        return Response(cached_questions)

    # If not in cache, get from database
    try:
        session = CoupleSession.objects.get(secret_word=secret_word)
    except CoupleSession.DoesNotExist:
        return Response([], status=200)  # Return empty array if session not found

    if mode == "mixed":
        admin_qs = Question.objects.all().order_by("?")
        # Custom questions for the specific couple session
        custom_qs = CustomQuestion.objects.filter(couple=session)
    else:
        admin_qs = Question.objects.filter(mode=mode)
        custom_qs = CustomQuestion.objects.filter(couple=session, mode=mode)

    all_questions = list(admin_qs) + list(custom_qs)
    # Shuffle questions
    random.shuffle(all_questions)

    combined_data = []
    for q in all_questions:
        # Support both Question and CustomQuestion
        combined_data.append(
            {"text": q.text, "mode": q.mode, "is_custom": isinstance(q, CustomQuestion)}
        )

    # Cache the results for 1 hour
    cache.set(cache_key, combined_data, timeout=3600)
    return Response(combined_data)


@api_view(["POST"])
def add_custom_question(request):
    serializer = CustomQuestionSerializer(data=request.data)

    if serializer.is_valid():
        serializer.save()
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    print("Serializer errors:", serializer.errors)  # Debugging
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(["GET"])
def get_custom_questions(request, secret_word, mode):
    try:
        session = CoupleSession.objects.get(secret_word=secret_word)
        # Get 10 random custom questions
        custom_qs = CustomQuestion.objects.filter(couple=session, mode=mode).order_by(
            "?"
        )
        serializer = CustomQuestionSerializer(custom_qs, many=True)
        return Response(serializer.data)
    except CoupleSession.DoesNotExist:
        return Response({"error": "Session not found"}, status=404)


@api_view(["GET"])
def check_session(request):
    secret = request.GET.get("secret")
    if not secret:
        return Response({"valid": False})

    try:
        session = CoupleSession.objects.get(secret_word=secret)
        if timezone.now() - session.last_active > timedelta(days=30):
            session.delete()
            return Response({"valid": False})
        session.save()  # Updates last_active
        return Response({"valid": True})
    except CoupleSession.DoesNotExist:
        return Response({"valid": False})


def login_page(request):
    return render(request, "game/login.html")


def mode_select_page(request):
    return render(request, "game/mode_select.html")


def play_page(request):
    return render(request, "game/play.html")
