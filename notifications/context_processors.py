def unread(request):
    """The unread count for member pages' "N new notifications" link."""
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {}
    from .services import unread_count

    return {"notification_unread": unread_count(user)}
