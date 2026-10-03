"""Add a process attestation endpoint to the disposable server URL tree."""

import os
import subprocess
from pathlib import Path

from django.conf import settings
from django.http import JsonResponse
from django.urls import path

from config.urls import urlpatterns as server_urlpatterns


def runtime_attestation(request):
    """Return evidence tied to this exact disposable Django process."""
    database_path = Path(settings.DATABASES["default"]["NAME"]).resolve()
    server_sha = subprocess.run(
        ["git", "-C", str(settings.BASE_DIR), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return JsonResponse(
        {
            "nonce": os.environ.get("BFG2_E2E_ATTESTATION_NONCE", ""),
            "database_path": str(database_path),
            "server_sha": server_sha,
        }
    )


urlpatterns = [
    path("_bfg2_e2e/attestation/", runtime_attestation),
    *server_urlpatterns,
]
