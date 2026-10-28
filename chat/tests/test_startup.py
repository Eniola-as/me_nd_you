"""Daphne imports the ASGI app before Django's apps are ready, so nothing
the WebSocket routes import may touch models at import time."""

import os
import subprocess
import sys

from cryptography.fernet import Fernet
from django.conf import settings
from django.test import SimpleTestCase

from game.tests.utils import SETTINGS_ENV_KEYS


class AsgiStartupTests(SimpleTestCase):
    def test_the_asgi_app_imports_in_a_fresh_process_like_daphne(self):
        env = {k: v for k, v in os.environ.items() if k not in SETTINGS_ENV_KEYS}
        env.update({"SECRET_KEY": "test-key", "DEBUG": "True", "DJANGO_SETTINGS_MODULE": "me_nd_you.settings",
                    "CHAT_ENCRYPTION_KEYS": Fernet.generate_key().decode()})
        result = subprocess.run([sys.executable, "-c", "import me_nd_you.asgi"], cwd=settings.BASE_DIR,
                                env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr[-2000:])
