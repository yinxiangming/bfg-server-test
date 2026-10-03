#!/usr/bin/env bash
set -euo pipefail

readonly EXPECTED_SERVER_SHA="77f742398b043432cb03954f8ad2698bd30299a4"
readonly TEST_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly SERVER_DIR="${BFG2_E2E_SERVER_DIR:?Set BFG2_E2E_SERVER_DIR to the pinned server checkout}"
readonly SERVER_PYTHON="${BFG2_E2E_SERVER_PYTHON:-${SERVER_DIR}/.venv/bin/python}"
readonly SERVER_SCRATCH_MARKER="${BFG2_E2E_SERVER_SCRATCH_MARKER:?Set BFG2_E2E_SERVER_SCRATCH_MARKER}"

if [[ "$(cd "${SERVER_DIR}" && pwd)" == "/Users/mac/Projects/nexus/src/server" ]]; then
  echo "Refusing the canonical Nexus server checkout; use a scratch clone." >&2
  exit 2
fi
if [[ ! -f "${SERVER_SCRATCH_MARKER}" ]] || \
   [[ "$(cat "${SERVER_SCRATCH_MARKER}")" != "bfg2-e2e-server-scratch-v1" ]] || \
   [[ "$(dirname "${SERVER_SCRATCH_MARKER}")" != "$(cd "${SERVER_DIR}" && pwd)" ]]; then
  echo "A valid scratch marker inside BFG2_E2E_SERVER_DIR is required." >&2
  exit 2
fi

actual_sha="$(git -C "${SERVER_DIR}" rev-parse HEAD)"
if [[ "${actual_sha}" != "${EXPECTED_SERVER_SHA}" ]]; then
  echo "Expected server ${EXPECTED_SERVER_SHA}, got ${actual_sha}" >&2
  exit 2
fi
if [[ ! -x "${SERVER_PYTHON}" ]]; then
  echo "Server Python is not executable: ${SERVER_PYTHON}" >&2
  exit 2
fi

run_root="$(mktemp -d "${TMPDIR:-/tmp}/bfg-server-e2e.XXXXXX")"
database_path="${run_root}/db.sqlite3"
marker_path="${run_root}/DISPOSABLE"
server_log="${run_root}/server.log"
init_log="${run_root}/init.log"
printf '%s\n' 'bfg2-e2e-disposable-v1' > "${marker_path}"

port="$("${SERVER_PYTHON}" -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1]); s.close()')"
runtime_secret="$("${SERVER_PYTHON}" -c 'import secrets; print(secrets.token_urlsafe(48))')"
admin_password="$("${SERVER_PYTHON}" -c 'import secrets; print("E2E-" + secrets.token_urlsafe(24))')"
customer_password="$("${SERVER_PYTHON}" -c 'import secrets; print("E2E-" + secrets.token_urlsafe(24))')"
attestation_nonce="$("${SERVER_PYTHON}" -c 'import secrets; print(secrets.token_urlsafe(48))')"

export ENV=prod
export PYTHONPATH="${TEST_ROOT}${PYTHONPATH:+:${PYTHONPATH}}"
export DJANGO_SETTINGS_MODULE=e2e_runtime.settings
export DEBUG=False
export SECRET_KEY="${runtime_secret}"
export DATABASE_URL="sqlite:///${database_path}"
export ALLOWED_HOSTS="127.0.0.1,localhost"
export EMAIL_VERIFICATION_REQUIRED=false
export BFG_SUPERUSER_BYPASS_WORKSPACE_PERMISSIONS=true
export CELERY_BROKER_URL="memory://"
export EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend"
export INIT_ADMIN_PASSWORD="${admin_password}"
export ADMIN_PASSWORD="${admin_password}"

export BASE_URL="http://127.0.0.1:${port}"
export BFG2_E2E_FORWARDED_PROTO=https
export BFG2_E2E_DISPOSABLE=1
export BFG2_E2E_DATABASE_PATH="${database_path}"
export BFG2_E2E_DISPOSABLE_MARKER="${marker_path}"
export BFG2_E2E_SERVER_DIR="${SERVER_DIR}"
export BFG2_E2E_SERVER_PYTHON="${SERVER_PYTHON}"
export BFG2_E2E_SERVER_SETTINGS="config.prod"
export BFG2_E2E_ATTESTATION_NONCE="${attestation_nonce}"
export BFG2_E2E_SUPERUSER_EMAIL="e2e-admin@localhost"
export BFG2_E2E_SUPERUSER_PASSWORD="${admin_password}"
export BFG2_E2E_CUSTOMER_PASSWORD="${customer_password}"
export BFG2_E2E_TEMP_PASSWORD="${customer_password}"

server_pid=""
stop_server() {
  if [[ -n "${server_pid}" ]] && kill -0 "${server_pid}" 2>/dev/null; then
    kill "${server_pid}"
    wait "${server_pid}" 2>/dev/null || true
  fi
}
trap stop_server EXIT INT TERM

cd "${SERVER_DIR}"
if ! "${SERVER_PYTHON}" manage.py init \
  --workspace-name "E2E Bootstrap" \
  --workspace-slug "e2e-bootstrap" \
  --admin "e2e-admin" \
  --seed-data >"${init_log}" 2>&1; then
  echo "Disposable server initialization failed. Log: ${init_log}" >&2
  tail -100 "${init_log}" >&2 || true
  exit 1
fi

"${SERVER_PYTHON}" manage.py runserver "127.0.0.1:${port}" --noreload >"${server_log}" 2>&1 &
server_pid="$!"

ready=0
for _ in {1..60}; do
  if "${SERVER_PYTHON}" -c \
    'import os, requests; r=requests.get(os.environ["BASE_URL"] + "/api/v1/health/", headers={"X-Forwarded-Proto": "https"}, timeout=1); raise SystemExit(0 if r.status_code == 200 else 1)' \
    2>/dev/null; then
    ready=1
    break
  fi
  if ! kill -0 "${server_pid}" 2>/dev/null; then
    break
  fi
  sleep 1
done
if [[ "${ready}" != "1" ]]; then
  echo "Disposable server failed to become ready. Log: ${server_log}" >&2
  tail -100 "${server_log}" >&2 || true
  exit 1
fi

cd "${TEST_ROOT}"
if [[ "$#" -eq 0 ]]; then
  set -- api/bfg_workspace/ -m api_integration -q --tb=short
fi
env -u DJANGO_SETTINGS_MODULE "${SERVER_PYTHON}" -m pytest "$@"

echo "Disposable artifacts retained at ${run_root}"
