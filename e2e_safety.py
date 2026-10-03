"""Fail-closed validation for the mutating live HTTP test target."""

import hmac
import subprocess
import urllib.parse
from pathlib import Path

import requests


EXPECTED_SERVER_SHA = "77f742398b043432cb03954f8ad2698bd30299a4"
_TRUTHY = {"1", "true", "yes", "on"}


def validate_disposable_target(base_url, environ):
    """Raise ValueError unless every disposable local-target proof is present."""
    if environ.get("BFG2_E2E_DISPOSABLE", "").strip().lower() not in _TRUTHY:
        raise ValueError(
            "Mutating API integration tests require BFG2_E2E_DISPOSABLE=1. "
            "Use scripts/run_disposable_workspace_e2e.sh for an isolated server."
        )

    parsed = urllib.parse.urlparse(base_url)
    if (parsed.hostname or "").lower() not in {"127.0.0.1", "::1"}:
        raise ValueError(f"Refusing non-loopback BASE_URL {base_url!r}.")

    database_value = environ.get("BFG2_E2E_DATABASE_PATH", "").strip()
    marker_value = environ.get("BFG2_E2E_DISPOSABLE_MARKER", "").strip()
    server_value = environ.get("BFG2_E2E_SERVER_DIR", "").strip()
    scratch_value = environ.get("BFG2_E2E_SERVER_SCRATCH_MARKER", "").strip()
    if not all((database_value, marker_value, server_value, scratch_value)):
        raise ValueError("Disposable database, marker, server, and scratch marker are required.")

    database_path = Path(database_value).resolve()
    marker_path = Path(marker_value).resolve()
    server_dir = Path(server_value).resolve()
    scratch_marker = Path(scratch_value).resolve()
    if not database_path.is_file() or not marker_path.is_file():
        raise ValueError("Disposable SQLite database and marker files must exist.")
    if marker_path.parent != database_path.parent:
        raise ValueError("Disposable marker and SQLite database must share an isolated directory.")
    if marker_path.read_text(encoding="utf-8").strip() != "bfg2-e2e-disposable-v1":
        raise ValueError("Disposable marker has invalid contents.")

    if not server_dir.is_dir() or not scratch_marker.is_file():
        raise ValueError("Disposable server checkout and scratch marker must exist.")
    if scratch_marker.parent != server_dir:
        raise ValueError("Server scratch marker must be inside BFG2_E2E_SERVER_DIR.")
    if scratch_marker.read_text(encoding="utf-8").strip() != "bfg2-e2e-server-scratch-v1":
        raise ValueError("Server scratch marker has invalid contents.")
    actual_sha = subprocess.run(
        ["git", "-C", str(server_dir), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if actual_sha != EXPECTED_SERVER_SHA:
        raise ValueError(f"Expected server {EXPECTED_SERVER_SHA}, got {actual_sha}.")


def validate_runtime_attestation(base_url, environ, request_get=requests.get):
    """Prove the loopback HTTP process uses the declared database and server checkout."""
    nonce = environ.get("BFG2_E2E_ATTESTATION_NONCE", "").strip()
    if not nonce:
        raise ValueError("BFG2_E2E_ATTESTATION_NONCE is required.")

    attestation_url = f"{base_url.rstrip('/')}/_bfg2_e2e/attestation/"
    try:
        response = request_get(
            attestation_url,
            headers={"X-Forwarded-Proto": "https"},
            timeout=5,
        )
    except requests.RequestException as exc:
        raise ValueError(f"Runtime attestation request failed: {exc}") from exc
    if response.status_code != 200:
        raise ValueError(f"Runtime attestation returned HTTP {response.status_code}.")
    try:
        payload = response.json()
    except ValueError as exc:
        raise ValueError("Runtime attestation did not return JSON.") from exc

    expected_database = str(Path(environ["BFG2_E2E_DATABASE_PATH"]).resolve())
    actual_nonce = str(payload.get("nonce", ""))
    actual_database = str(payload.get("database_path", ""))
    actual_sha = str(payload.get("server_sha", ""))
    if not hmac.compare_digest(actual_nonce, nonce):
        raise ValueError("Runtime attestation nonce mismatch.")
    if actual_database != expected_database:
        raise ValueError(
            f"Runtime attestation database mismatch: expected {expected_database}, "
            f"got {actual_database or '<missing>'}."
        )
    if actual_sha != EXPECTED_SERVER_SHA:
        raise ValueError(
            f"Runtime attestation server SHA mismatch: expected {EXPECTED_SERVER_SHA}, "
            f"got {actual_sha or '<missing>'}."
        )
