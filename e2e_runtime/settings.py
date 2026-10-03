"""Production settings wrapper used only by the disposable E2E runner."""

from config.prod import *  # noqa: F403


ROOT_URLCONF = "e2e_runtime.urls"
BFG_EXTRA_PUBLIC_PATHS = tuple(globals().get("BFG_EXTRA_PUBLIC_PATHS", ())) + (
    "/_bfg2_e2e/attestation/",
)
