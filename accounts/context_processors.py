from django.conf import settings


def email_delivery(request):
    return {"email_enabled": settings.EMAIL_ENABLED}
