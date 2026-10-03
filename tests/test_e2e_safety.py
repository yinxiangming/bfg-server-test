from pathlib import Path

import pytest

from e2e_safety import validate_disposable_target, validate_runtime_attestation


def test_non_loopback_target_is_rejected_even_with_disposable_flag(tmp_path):
    database = tmp_path / "db.sqlite3"
    marker = tmp_path / "DISPOSABLE"
    database.touch()
    marker.write_text("bfg2-e2e-disposable-v1\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Refusing non-loopback BASE_URL"):
        validate_disposable_target(
            "https://uat.example.test",
            {
                "BFG2_E2E_DISPOSABLE": "1",
                "BFG2_E2E_DATABASE_PATH": str(database),
                "BFG2_E2E_DISPOSABLE_MARKER": str(marker),
                "BFG2_E2E_SERVER_DIR": str(Path.cwd()),
                "BFG2_E2E_SERVER_SCRATCH_MARKER": str(tmp_path / "scratch"),
            },
        )


def test_loopback_service_with_different_database_is_rejected(tmp_path):
    declared_database = tmp_path / "declared.sqlite3"
    other_database = tmp_path / "developer.sqlite3"
    declared_database.touch()
    other_database.touch()
    nonce = "unit-test-random-nonce"

    class OtherLoopbackResponse:
        status_code = 200

        @staticmethod
        def json():
            return {
                "nonce": nonce,
                "database_path": str(other_database.resolve()),
                "server_sha": "77f742398b043432cb03954f8ad2698bd30299a4",
            }

    requested = []

    def get_other_loopback(url, **kwargs):
        requested.append((url, kwargs))
        return OtherLoopbackResponse()

    with pytest.raises(ValueError, match="Runtime attestation database mismatch"):
        validate_runtime_attestation(
            "http://127.0.0.1:8765",
            {
                "BFG2_E2E_ATTESTATION_NONCE": nonce,
                "BFG2_E2E_DATABASE_PATH": str(declared_database),
            },
            request_get=get_other_loopback,
        )
    assert requested[0][0] == "http://127.0.0.1:8765/_bfg2_e2e/attestation/"
