from django.urls import path

from . import views

urlpatterns = [
    path("space/", views.space, name="space"),
    path("invite/", views.invitation_page, name="invitation_page"),
    # Links made before the token moved to the fragment; they expire within 7 days.
    path("invite/<str:token>/", views.invitation_link, name="invitation_link"),
]
