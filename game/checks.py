from django.conf import settings
from django.core.checks import Tags, Warning, register


@register(Tags.security, deploy=True)
def check_trusted_proxy_count(app_configs, **kwargs):
    """Rate limits need the real proxy count to tell visitors apart."""
    if settings.TRUSTED_PROXY_COUNT is None:
        return [
            Warning(
                "TRUSTED_PROXY_COUNT is not set, so rate limits ignore "
                "X-Forwarded-For and use the connecting address. Behind a "
                "proxy, all visitors then share one rate-limit bucket.",
                hint="Verify how many proxies sit in front of the app and set "
                "TRUSTED_PROXY_COUNT to that number.",
                id="game.W001",
            )
        ]
    return []
