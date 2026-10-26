from django.urls import path

from . import views

urlpatterns = [
    path("space/", views.space, name="space"),
    path("invite/<str:token>/", views.invitation_link, name="invitation_link"),
]
