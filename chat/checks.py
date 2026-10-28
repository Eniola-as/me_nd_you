from django.conf import settings
from django.core.checks import Warning, register


@register()
def check_chat_key(app_configs, **kwargs):
    """Production refuses to start without a key (see settings); locally,
    chat just doesn't work until one is set."""
    if settings.CHAT_ENCRYPTION_KEYS:
        return []
    return [
        Warning(
            "CHAT_ENCRYPTION_KEYS is not set, so chat can't send or show messages.",
            hint="Generate a key (see .env.example) and set CHAT_ENCRYPTION_KEYS.",
            id="chat.W001",
        )
    ]
