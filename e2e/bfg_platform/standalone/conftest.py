"""Load platform/standalone/.env overriding project-root .env."""
import os
from pathlib import Path
import pytest

_env = Path(__file__).parent / ".env"
if _env.exists():
    try:
        from dotenv import load_dotenv
        load_dotenv(_env, override=True)
    except ImportError:
        pass


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
    if not _is_standalone_server_up():
        base = os.environ.get("BASE_URL", "not set")
        pytest.skip(
            f"Standalone platform server not reachable at {base}. "
            "Set BASE_URL=http://localhost:8011 and start the standalone server to run these tests."
        )
