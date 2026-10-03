"""Production settings wrapper used only by the disposable E2E runner."""

from config.prod import *  # noqa: F403


ROOT_URLCONF = "e2e_runtime.urls"
CELERY_BROKER_URL = "memory://"
CELERY_RESULT_BACKEND = "cache+memory://"
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
BFG_EXTRA_PUBLIC_PATHS = tuple(globals().get("BFG_EXTRA_PUBLIC_PATHS", ())) + (
    "/_bfg2_e2e/attestation/",
)
