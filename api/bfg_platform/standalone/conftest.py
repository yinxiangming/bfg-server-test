"""Load platform/standalone/.env overriding project-root .env."""
import os
from pathlib import Path
from urllib.parse import urlparse

import pytest

_env = Path(__file__).parent / ".env"
if _env.exists():
    try:
        from dotenv import load_dotenv
        load_dotenv(_env, override=True)
    except ImportError:
        pass


def _api_origin_key(url: str) -> tuple:
    """Normalize scheme/host/port for comparing whether two base URLs hit the same API server."""
    p = urlparse((url or "").strip())
    scheme = (p.scheme or "http").lower()
    host = (p.hostname or "").lower()
    if host == "127.0.0.1":
        host = "localhost"
    port = p.port
    if port is None:
        port = 443 if scheme == "https" else 80
    return scheme, host, port


def _is_embedded_single_server_config() -> bool:
    """
    True when BASE_URL and WORKSPACE_BASE_URL point at the same origin.

    That layout is *embedded* mode (one BFG instance). Standalone platform API integration tests
    expect a dedicated platform server (different origin from workspace).
    """
    base = os.environ.get("BASE_URL", "").strip().rstrip("/")
    ws = os.environ.get("WORKSPACE_BASE_URL", "").strip().rstrip("/")
    if not base or not ws:
        return False
    return _api_origin_key(base) == _api_origin_key(ws)


def _is_standalone_server_up() -> bool:
    """Check if the standalone platform server is reachable."""
    import requests
    base = os.environ.get("BASE_URL", "").rstrip("/")
    if not base:
        return False
    try:
        r = requests.get(f"{base}/api/v1/platform/plans/", timeout=3)
        return r.status_code < 500
    except Exception:
        return False


@pytest.fixture(autouse=True)
def require_standalone_server():
    """Skip each standalone test if the platform server is not reachable."""
    if _is_embedded_single_server_config():
        pytest.skip(
            "Standalone platform API integration tests require a separate platform instance: "
            "set BASE_URL to the platform server and WORKSPACE_BASE_URL to the workspace server "
            "(different origins). With the same URL for both, you are in embedded mode — "
            "run api/bfg_platform/embedded/ instead."
        )
    if not _is_standalone_server_up():
        base = os.environ.get("BASE_URL", "not set")
        pytest.skip(
            f"Standalone platform server not reachable at {base}. "
            "Set BASE_URL=http://localhost:8011 and start the standalone server to run these tests."
        )
