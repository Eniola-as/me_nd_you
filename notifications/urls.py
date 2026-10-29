from django.urls import path

from . import views

urlpatterns = [
    path("api/notifications/", views.notification_list, name="notification_list"),
    path("notifications/<int:notification_id>/open/", views.open_notification, name="open_notification"),
    path("notifications/read-all/", views.read_all, name="notifications_read_all"),
    path("api/push/key/", views.push_key, name="push_key"),
    path("api/push/subscribe/", views.push_subscribe, name="push_subscribe"),
    path("api/push/unsubscribe/", views.push_unsubscribe, name="push_unsubscribe"),
]
