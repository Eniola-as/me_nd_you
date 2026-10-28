"""Who is connected to chat right now, and where (in memory).

Like the in-memory channel layer, this lives in the one Daphne process: a
second process wouldn't see these connections (docs/DEPLOYMENT.md). Only
the last-seen time is stored, on the member's Membership row."""

# Nothing here may import models at module level: Daphne imports the
# WebSocket routes (and so this) before Django's apps are ready.

# user id -> {channel name: [where, sequence]}; the latest update wins.
_live = {}
_sequence = 0


def reset():
    """Forget everything (tests)."""
    _live.clear()


def valid_where(where):
    from game.models import Question

    if where in ("space", "menu"):
        return True
    modes = {value for value, _ in Question.MODES}
    return isinstance(where, str) and where.startswith("play:") and where[5:] in modes


def join(user_id, channel):
    _touch(user_id, channel, None)


def update(user_id, channel, where):
    _touch(user_id, channel, where)


def leave(user_id, channel):
    """Forget one connection. True if it was the user's last one."""
    channels = _live.get(user_id, {})
    channels.pop(channel, None)
    if channels:
        return False
    _live.pop(user_id, None)
    return True


def status(user_id):
    channels = _live.get(user_id)
    if not channels:
        return {"online": False, "where": None}
    where, _ = max(channels.values(), key=lambda entry: entry[1])
    return {"online": True, "where": where}


def _touch(user_id, channel, where):
    global _sequence
    _sequence += 1
    _live.setdefault(user_id, {})[channel] = [where, _sequence]
