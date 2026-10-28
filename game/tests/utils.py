import json
import os
import subprocess
import sys

from cryptography.fernet import Fernet
from django.conf import settings

SETTINGS_ENV_KEYS = [
    "SECRET_KEY",
    "DEBUG",
    "ALLOWED_HOSTS",
    "RENDER_EXTERNAL_HOSTNAME",
    "SECURE_HSTS_SECONDS",
    "ADMIN_URL",
    "TRUSTED_PROXY_COUNT",
    "DATABASE_URL",
    "EMAIL_PROVIDER",
    "EMAIL_API_KEY",
    "DEFAULT_FROM_EMAIL",
    "CHAT_ENCRYPTION_KEYS",
    # A test run with --settings exports this; children must load the real
    # settings module.
    "DJANGO_SETTINGS_MODULE",
]


def load_settings(env, names):
    """Import the settings module in a fresh process with the given env vars.

    Settings are evaluated at import time, so a subprocess is the only way to
    see how they react to different environments.
    """
    child_env = {k: v for k, v in os.environ.items() if k not in SETTINGS_ENV_KEYS}
    # Production settings refuse to start without a chat key: give each run a
    # freshly generated one (never a real key).
    child_env.update({"SECRET_KEY": "test-key", "DEBUG": "False",
                      "CHAT_ENCRYPTION_KEYS": Fernet.generate_key().decode()})
    child_env.update(env)
    script = (
        "import json, me_nd_you.settings as s\n"
        f"print(json.dumps({{n: getattr(s, n, None) for n in {names!r}}}, default=str))"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=settings.BASE_DIR,
        env=child_env,
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout.strip().splitlines()[-1])
