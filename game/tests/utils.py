import json
import os
import subprocess
import sys

from django.conf import settings

SETTINGS_ENV_KEYS = [
    "SECRET_KEY",
    "DEBUG",
    "ALLOWED_HOSTS",
    "RENDER_EXTERNAL_HOSTNAME",
    "SECURE_HSTS_SECONDS",
    "ADMIN_URL",
]


def load_settings(env, names):
    """Import the settings module in a fresh process with the given env vars.

    Settings are evaluated at import time, so a subprocess is the only way to
    see how they react to different environments.
    """
    child_env = {k: v for k, v in os.environ.items() if k not in SETTINGS_ENV_KEYS}
    child_env.update({"SECRET_KEY": "test-key", "DEBUG": "False"})
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
