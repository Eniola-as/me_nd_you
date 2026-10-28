
"""
Django settings for me_nd_you project.
"""

import mimetypes
import sys
from email.utils import formataddr
from pathlib import Path
import dj_database_url
from cryptography.fernet import Fernet
from decouple import config
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent

# Security and environment settings
SECRET_KEY = config("SECRET_KEY")
DEBUG = config("DEBUG", default=False, cast=bool)

# Use .env locally and environment variables on Render.
ALLOWED_HOSTS = [
    host.strip()
    for host in config("ALLOWED_HOSTS", default="").split(",")
    if host.strip()
]

# Render sets this automatically to the service's public hostname.
RENDER_EXTERNAL_HOSTNAME = config("RENDER_EXTERNAL_HOSTNAME", default="")
if RENDER_EXTERNAL_HOSTNAME and RENDER_EXTERNAL_HOSTNAME not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append(RENDER_EXTERNAL_HOSTNAME)

# HTTPS: Render terminates TLS at its proxy and forwards plain HTTP, marking
# the original scheme in X-Forwarded-Proto. Only enforced outside DEBUG.
CSRF_TRUSTED_ORIGINS = [
    f"https://{host}" for host in ALLOWED_HOSTS if host not in ("localhost", "127.0.0.1")
]
if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    # Start short; raise towards 31536000 once HTTPS is confirmed working.
    SECURE_HSTS_SECONDS = config("SECURE_HSTS_SECONDS", default=3600, cast=int)
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True

# The HSTS preload list only accepts registrable domains the owner controls,
# so preloading can't apply to an *.onrender.com subdomain.
SILENCED_SYSTEM_CHECKS = ["security.W021"]

# Application definition
INSTALLED_APPS = [
    # First, so `runserver` is Daphne's ASGI server and serves WebSockets
    # locally, as production does.
    "daphne",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "accounts",
    "couples",
    "game",
    "play",
    "chat",
    "rest_framework",
    "channels",
    "anymail",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "accounts.middleware.ConsentRequiredMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "me_nd_you.settings.ServiceWorkerMiddleware",
]

# Email-and-password accounts (accounts.User). Must stay set before any
# production database is created; changing it later is very hard.
AUTH_USER_MODEL = "accounts.User"
LOGIN_URL = "/accounts/login/"
LOGIN_REDIRECT_URL = "/space/"
LOGOUT_REDIRECT_URL = "/"

ROOT_URLCONF = "me_nd_you.urls"

# Set to something hard to guess in production, e.g. "backstage-7f3k/".
ADMIN_URL = config("ADMIN_URL", default="admin/")

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

ASGI_APPLICATION = "me_nd_you.asgi.application"

# Database: PostgreSQL when DATABASE_URL is set (production), otherwise a
# local SQLite file for development. A deploy check warns if production
# would fall back to SQLite.
DATABASE_URL = config("DATABASE_URL", default="")
if DATABASE_URL:
    DATABASES = {
        "default": dj_database_url.parse(
            DATABASE_URL,
            # A new connection per request. Channels runs database work in a
            # thread pool, where long-lived connections are not reused
            # safely; with one Daphne process and modest traffic, the cost
            # of reconnecting is small. Revisit (e.g. a connection pool)
            # when traffic grows.
            conn_max_age=0,
            conn_health_checks=True,
        )
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]

# Internationalization
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# Static files
mimetypes.add_type("application/manifest+json", ".webmanifest", True)

STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

# Hashed, compressed static files in production. The test runner renders pages
# without running collectstatic first, so it uses plain storage instead.
TESTING = sys.argv[1:2] == ["test"]
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": (
            "django.contrib.staticfiles.storage.StaticFilesStorage"
            if TESTING
            else "whitenoise.storage.CompressedManifestStaticFilesStorage"
        )
    },
}

# Test runner only: a fast password hasher. Real hashing (PBKDF2) is slow on
# purpose, about half a second per password, and the suite creates hundreds of
# test users. Never active outside `manage.py test`; a test checks that.
# Gives users created by tests the current consents (accounts.testing).
TEST_RUNNER = "accounts.testing.ConsentingTestRunner"
if TESTING:
    PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# Default primary key
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

TRUSTED_PROXY_COUNT = config("TRUSTED_PROXY_COUNT", default=None, cast=lambda v: int(v) if v else None)

# Django REST Framework: JSON only; the browsable HTML API is for development.
REST_FRAMEWORK = {
    # Sessions only (no HTTP Basic). Session auth enforces CSRF for signed-in
    # users on unsafe methods.
    "DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework.authentication.SessionAuthentication"],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"]
    + (["rest_framework.renderers.BrowsableAPIRenderer"] if DEBUG else []),
    # Per-client limits on everything that takes a secret word, to slow down
    # guessing other couples' secrets and spamming custom questions.
    "DEFAULT_THROTTLE_RATES": {
        "space_custom_questions": "10/min",
        "account_login": "10/min",
        "account_register": "5/min",
        "account_profile": "20/min",
        # These send mail (provider quota), so they are tighter.
        "account_verify_email": "5/min",
        "account_password_reset": "5/min",
        "space_action": "30/min",
        "invite_link": "20/min",
    },
    # How many proxies in front of the app append to X-Forwarded-For. Rate
    # limits identify clients by the address the last trusted proxy added;
    # anything earlier in the header is client-supplied and can be faked.
    # 0 (the default) ignores the header and uses the connecting address,
    # which can't be faked but, behind a proxy, puts every visitor in one
    # bucket. Set TRUSTED_PROXY_COUNT once the deployment's proxy chain is
    # verified (a deploy check warns while it is unset).
    "NUM_PROXIES": TRUSTED_PROXY_COUNT or 0,
}

# Email. EMAIL_PROVIDER picks one of django-anymail's HTTPS API backends;
# EMAIL_API_KEY is that provider's key. There is deliberately no SMTP option:
# Render's free tier blocks outgoing SMTP. Without a provider (local
# development), mail is printed to the console; tests capture it in memory.
# A deploy check warns while production is not configured.
EMAIL_PROVIDERS = {
    # name: (backend, the ANYMAIL setting that holds its key)
    "brevo": ("anymail.backends.brevo.EmailBackend", "BREVO_API_KEY"),
    "resend": ("anymail.backends.resend.EmailBackend", "RESEND_API_KEY"),
    "postmark": ("anymail.backends.postmark.EmailBackend", "POSTMARK_SERVER_TOKEN"),
}
EMAIL_PROVIDER = config("EMAIL_PROVIDER", default="").strip().lower()
EMAIL_API_KEY = config("EMAIL_API_KEY", default="")
if not EMAIL_PROVIDER:
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
    ANYMAIL = {}
elif EMAIL_PROVIDER in EMAIL_PROVIDERS:
    EMAIL_BACKEND, _key_setting = EMAIL_PROVIDERS[EMAIL_PROVIDER]
    ANYMAIL = {_key_setting: EMAIL_API_KEY}
else:
    raise ImproperlyConfigured(
        f"EMAIL_PROVIDER must be one of {', '.join(sorted(EMAIL_PROVIDERS))}, or unset for the console."
    )
DEFAULT_FROM_EMAIL_ADDRESS = config("DEFAULT_FROM_EMAIL", default="")
DEFAULT_FROM_EMAIL = formataddr(("Me & You", DEFAULT_FROM_EMAIL_ADDRESS or "no-reply@localhost"))
# Shown on the privacy policy and terms as the address for privacy requests.
PRIVACY_CONTACT_EMAIL = config("PRIVACY_CONTACT_EMAIL", default="")
# The version of the privacy policy and terms that sign-up consents refer to.
# Change it when the policy changes so everyone is asked to agree again. A
# version containing "draft" marks the pages as under review.
POLICY_VERSION = "draft-2026-10-28"
# Chat message text is encrypted at rest (chat.crypto). CHAT_ENCRYPTION_KEYS
# is one or more Fernet keys separated by commas: the first encrypts, all
# decrypt (see `manage.py rotate_chat_keys`). It comes only from the
# environment, never from the repository or SECRET_KEY. Losing every key
# permanently loses every chat message: keep a copy outside Render.
CHAT_ENCRYPTION_KEYS = [
    key.strip() for key in config("CHAT_ENCRYPTION_KEYS", default="").split(",") if key.strip()
]
for _chat_key in CHAT_ENCRYPTION_KEYS:
    try:
        Fernet(_chat_key)
    except (ValueError, TypeError):
        # Never echo the value: it may be a real key with a typo.
        raise ImproperlyConfigured("CHAT_ENCRYPTION_KEYS contains a value that isn't a valid Fernet key.") from None
if not CHAT_ENCRYPTION_KEYS and not DEBUG:
    raise ImproperlyConfigured(
        "CHAT_ENCRYPTION_KEYS must be set in production (see docs/DEPLOYMENT.md)."
    )

# How long verification links work, in seconds.
EMAIL_VERIFICATION_TIMEOUT = 3 * 24 * 60 * 60
PASSWORD_RESET_TIMEOUT = 60 * 60

# Django Channels
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels.layers.InMemoryChannelLayer",
    }
}

# Logging
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
}


class ServiceWorkerMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if request.path.endswith("service-worker.js"):
            response["Service-Worker-Allowed"] = "/"
        return response


# -------------------------------------------------------------------
# Previous production overrides — intentionally disabled.
#
# These settings were overriding the .env values and preventing
# local access. Render should provide DEBUG and ALLOWED_HOSTS as
# environment variables through its dashboard or render.yaml.
# -------------------------------------------------------------------

# DEBUG = False
# ALLOWED_HOSTS = ["me-nd-you.onrender.com"]

# The middleware list is defined once above, so the old replacement
# block is intentionally disabled.
#
# MIDDLEWARE = [
#     "whitenoise.middleware.WhiteNoiseMiddleware",
#     "django.middleware.security.SecurityMiddleware",
#     "django.contrib.sessions.middleware.SessionMiddleware",
#     "django.middleware.common.CommonMiddleware",
#     "django.middleware.csrf.CsrfViewMiddleware",
#     "django.contrib.auth.middleware.AuthenticationMiddleware",
#     "django.contrib.messages.middleware.MessageMiddleware",
#     "django.middleware.clickjacking.XFrameOptionsMiddleware",
# ]

# STATIC_ROOT = os.path.join(BASE_DIR, "staticfiles")
# STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"
