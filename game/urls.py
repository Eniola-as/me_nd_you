from django.urls import path

from . import views

urlpatterns = [
    path("", views.landing_page, name="landing"),
    path("modes/", views.mode_select_page, name="modes"),
    path("play/", views.play_page, name="play"),
    path(
        "api/space/custom-questions/",
        views.add_space_custom_question,
        name="space_custom_questions",
    ),
]
