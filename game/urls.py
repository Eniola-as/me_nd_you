from django.urls import path
from . import views

urlpatterns = [
    path("", views.login_page, name="login"),
    path("modes/", views.mode_select_page, name="modes"),
    path("play/", views.play_page, name="play"),
    path("api/questions/<str:mode>/", views.get_questions, name="get_questions"),
    path(
        "api/add-custom-question/",
        views.add_custom_question,
        name="add_custom_question",
    ),
    path("api/login/", views.login_or_register, name="api_login"),
]
