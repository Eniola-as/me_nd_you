from django.contrib.auth.views import LogoutView
from django.urls import path

from . import views

urlpatterns = [
    path("login/", views.sign_in, name="login"),
    path("register/", views.register, name="register"),
    # Django's LogoutView only accepts POST, so links can't sign people out.
    path("logout/", LogoutView.as_view(), name="logout"),
]
