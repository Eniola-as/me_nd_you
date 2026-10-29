from django.contrib.auth.views import LogoutView
from django.urls import path

from . import views

urlpatterns = [
    path("login/", views.sign_in, name="login"),
    path("register/", views.register, name="register"),
    path("profile/", views.profile, name="profile"),
    path("profile/download/", views.download_my_data, name="download_my_data"),
    path("profile/delete/", views.delete_account, name="delete_account"),
    path("deleted/", views.account_deleted, name="account_deleted"),
    path("consent/", views.consent, name="consent"),
    path("password/reset/", views.password_reset, name="password_reset"),
    path("password/reset/sent/", views.password_reset_sent, name="password_reset_sent"),
    path("password/reset/confirm/", views.password_reset_confirm, name="password_reset_confirm"),
    path("verify/", views.verify_email, name="verify_email"),
    path("verify/resend/", views.resend_verification, name="resend_verification"),
    path("verify/dismiss/", views.dismiss_verification_banner, name="dismiss_verification_banner"),
    # Django's LogoutView only accepts POST, so links can't sign people out.
    path("logout/", LogoutView.as_view(), name="logout"),
]
