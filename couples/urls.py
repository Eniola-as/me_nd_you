from django.urls import path

from . import views

urlpatterns = [
    path("space/", views.space, name="space"),
    path("invite/", views.invitation_page, name="invitation_page"),
]
