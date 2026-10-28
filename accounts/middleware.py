from urllib.parse import urlencode

from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import redirect

from .consents import SESSION_KEY, missing_consents

# Reachable before consenting: the consent page itself, reading the policy,
# signing out, and static files. The admin is staff tooling, not the app.
OPEN_PREFIXES = ("/accounts/consent/", "/accounts/logout/", "/privacy/", "/terms/")


class ConsentRequiredMiddleware:
    """Signed-in users who haven't confirmed they're 18+ or given the
    current consents must do so before using anything else. Pages redirect
    to the consent page; the API answers 403. (The sockets check too.)"""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if self._must_consent(request):
            if request.path.startswith("/api/"):
                return JsonResponse(
                    {"detail": "Please accept the terms first.", "code": "consent_required"}, status=403
                )
            return redirect(f"/accounts/consent/?{urlencode({'next': request.get_full_path()})}")
        return self.get_response(request)

    @staticmethod
    def _must_consent(request):
        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated:
            return False
        path = request.path
        if path.startswith(OPEN_PREFIXES + (settings.STATIC_URL, "/" + settings.ADMIN_URL)):
            return False
        if request.session.get(SESSION_KEY) == settings.POLICY_VERSION:
            return False
        if missing_consents(user):
            return True
        request.session[SESSION_KEY] = settings.POLICY_VERSION
        return False
