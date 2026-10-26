from functools import wraps

from django.contrib.auth import login
from django.contrib.auth.views import LoginView
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_http_methods

from game.views import ClientRateThrottle

from .forms import EmailAuthenticationForm, RegistrationForm


def rate_limited(scope):
    """Limit POSTs to a view per client address (rates in settings), using
    the same throttle as the API. Counts are per process (in-memory cache)."""

    throttle_class = type(f"{scope.title()}Throttle", (ClientRateThrottle,), {"scope": scope})

    def decorator(view):
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            if request.method == "POST" and not throttle_class().allow_request(request, None):
                return HttpResponse(
                    "Too many attempts. Please wait a minute and try again.", status=429
                )
            return view(request, *args, **kwargs)

        return wrapped

    return decorator


def _next_url(request, default="/space/"):
    candidate = request.POST.get("next") or request.GET.get("next")
    if candidate and url_has_allowed_host_and_scheme(
        candidate, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return candidate
    return default


@rate_limited("account_register")
@require_http_methods(["GET", "POST"])
def register(request):
    if request.user.is_authenticated:
        return redirect("/space/")
    form = RegistrationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user)  # Starts a fresh session (new session key).
        return redirect(_next_url(request))
    return render(request, "accounts/register.html", {"form": form, "next": _next_url(request)})


class EmailLoginView(LoginView):
    template_name = "accounts/login.html"
    authentication_form = EmailAuthenticationForm
    redirect_authenticated_user = True


sign_in = rate_limited("account_login")(EmailLoginView.as_view())
