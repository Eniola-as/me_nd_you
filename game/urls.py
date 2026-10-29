from django.urls import path

from . import views

urlpatterns = [
    path("", views.landing_page, name="landing"),
    path("service-worker.js", views.service_worker, name="service_worker"),
    path("offline/", views.offline_page, name="offline"),
    path("modes/", views.mode_select_page, name="modes"),
    path("play/", views.play_page, name="play"),
    path("api/space/mode/", views.space_mode, name="space_mode"),
    path(
        "api/space/custom-questions/",
        views.add_space_custom_question,
        name="space_custom_questions",
    ),
]
