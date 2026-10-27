"""
ASGI config for me_nd_you project.

It exposes the ASGI callable as a module-level variable named `application`.

For more information on this file, see
https://docs.djangoproject.com/en/5.2/howto/deployment/asgi/
"""

import os
from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack
from channels.security.websocket import AllowedHostsOriginValidator
from play import routing

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "me_nd_you.settings")

application = ProtocolTypeRouter(
    {
        "http": get_asgi_application(),
        # Reject sockets opened by pages on other sites (cross-site hijacking).
        "websocket": AllowedHostsOriginValidator(
            AuthMiddlewareStack(
                URLRouter(routing.websocket_urlpatterns)
            )
        ),
    }
)
