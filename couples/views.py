from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from accounts.views import rate_limited

from . import services

# The token from an invitation link waits here until the person accepts. It
# never goes back into a URL or a page.
PENDING_INVITE = "pending_invite"
NEW_INVITE_URL = "new_invite_url"


@require_http_methods(["GET"])
def invitation_link(request, token):
    request.session[PENDING_INVITE] = token
    if not request.user.is_authenticated:
        return redirect("/accounts/login/?next=/space/")
    return redirect("/space/")


@login_required
@rate_limited("space_action")
@require_http_methods(["GET", "POST"])
def space(request):
    if request.method == "POST":
        _handle_action(request)
        return redirect("/space/")

    user = request.user
    membership = services.active_membership(user)
    return render(request, "couples/space.html", {
        "membership": membership,
        "partner": services.partner_of(user),
        "pending_invitation": services.pending_invitation(user),
        # Shown once, right after it was created.
        "new_invite_url": request.session.pop(NEW_INVITE_URL, None),
        "has_pending_invite": PENDING_INVITE in request.session,
    })


def _handle_action(request):
    user, action = request.user, request.POST.get("action")
    try:
        if action == "create_couple":
            services.create_couple(user)
            messages.success(request, "Your couple space is ready. Invite your partner.")
        elif action == "create_invite":
            token = services.create_invitation(user)
            request.session[NEW_INVITE_URL] = request.build_absolute_uri(f"/invite/{token}/")
        elif action == "revoke_invites":
            services.revoke_invitations(user)
            messages.success(request, "The invitation link no longer works.")
        elif action == "accept_invite":
            token = request.session.pop(PENDING_INVITE, None)
            services.redeem_invitation(user, token)
            messages.success(request, "You've joined your partner's couple space.")
        elif action == "dismiss_invite":
            request.session.pop(PENDING_INVITE, None)
        elif action == "leave_couple":
            if request.POST.get("confirm") != "yes":
                messages.error(request, "Tick the box to confirm that you want to close this space.")
            else:
                services.close_couple(user)
                messages.success(request, "You left. The couple space is closed for both of you.")
    except services.InvitationError as error:
        messages.error(request, str(error))
