# BFG2 HTTP API Integration Test Suite

HTTP API integration tests against a live BFG2 server. No Django ORM — every test uses the real HTTP API.

> Credentials use the `BFG2_E2E_*` environment variable prefix for historical compatibility with existing setups.

## Quick Start

```bash
pip install -r requirements.txt
printf '%s\n' 'bfg2-e2e-server-scratch-v1' \
  > /path/to/bfg-server-django/.bfg-e2e-scratch
BFG2_E2E_SERVER_DIR=/path/to/bfg-server-django \
  BFG2_E2E_SERVER_SCRATCH_MARKER=/path/to/bfg-server-django/.bfg-e2e-scratch \
  bash scripts/run_disposable_workspace_e2e.sh
```

The runner refuses any server revision except
`77f742398b043432cb03954f8ad2698bd30299a4`, creates a fresh SQLite database,
starts the server in production mode on a random loopback port, forwards
`X-Forwarded-Proto: https`, seeds real fixtures, and runs the workspace HTTP
suite. Runtime passwords and signing keys are generated per run. The server
process is always stopped; the temporary directory is retained for inspection.
The server checkout must be a scratch clone containing a marker file whose only
line is `bfg2-e2e-server-scratch-v1`; the runner refuses the canonical Nexus
server path because seeding writes media fixtures into the checkout.

The runner starts Django through the repository's `e2e_runtime.settings`
wrapper. Before any mutating fixture runs, pytest requests a runner-only
attestation endpoint and verifies the per-run random nonce, Django's resolved
SQLite path, and the server checkout SHA. This prevents a different developer
server on another loopback port from satisfying the file-based guard.

Direct `pytest -m api_integration` runs also require an explicit disposable
marker, SQLite database, pinned scratch server checkout, scratch marker, and a
server launched with the same attestation nonce and runtime wrapper. Use the
runner unless debugging an already-attested disposable process. Non-loopback
targets are always rejected by this mutating suite.

## Directory Layout

```
bfg-server-test/
├── conftest.py              # global fixtures (session bootstrap, workspace creation)
├── client_remote.py         # RemoteAPIClient (mimics DRF test client over HTTP)
├── .env                     # local credentials (git-ignored)
├── .env.example             # template
├── pytest.ini
├── requirements.txt
└── api/
    ├── bfg_workspace/       # Core BFG workspace API tests (test_01 … test_18, storefront, etc.)
    │   ├── test_01_registration.py
    │   ├── test_02_website_setup.py
    │   └── ...
    └── bfg_platform/        # Platform extension tests
        ├── embedded/        # Embedded mode (platform runs inside workspace server)
        │   ├── conftest.py
        │   └── test_embedded.py   # 20 tests
        └── standalone/      # Standalone mode (separate platform server)
            ├── conftest.py
            └── test_standalone.py # 21 tests
```

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `BASE_URL` | BFG server base URL | required |
| `BFG2_E2E_SUPERUSER_EMAIL` | Superuser email | `admin@test.com` |
| `BFG2_E2E_SUPERUSER_PASSWORD` | Superuser password | required |
| `BFG2_E2E_CUSTOMER_PASSWORD` | Password for test customer accounts | required |
| `BFG2_E2E_ADMIN_EMAIL` | Admin email (non-superuser bootstrap) | `admin@test.com` |
| `BFG2_E2E_FORWARDED_PROTO` | Reverse-proxy protocol for local production-mode runs | unset |
| `BFG2_E2E_DISPOSABLE` | Acknowledge that the target is throwaway | required |
| `BFG2_E2E_DATABASE_PATH` | Fresh SQLite database used by the target | required |
| `BFG2_E2E_DISPOSABLE_MARKER` | Guard marker beside the SQLite database | required |
| `BFG2_E2E_SERVER_DIR` | Pinned server checkout used by callback fixture setup | required |
| `BFG2_E2E_SERVER_PYTHON` | Python executable for the pinned server | required |
| `BFG2_E2E_SERVER_SCRATCH_MARKER` | Marker proving the server checkout is disposable | required |
| `BFG2_E2E_ATTESTATION_NONCE` | Per-run nonce shared with the isolated runtime wrapper | runner-generated |

See `.env.example` for the full list.

## Current Validation Baseline

Against server `77f742398b043432cb03954f8ad2698bd30299a4`, the disposable
production-mode runner completes with `150 passed, 2 skipped`. All 23 cases in
`test_19_security_contracts.py` pass. The two skips are the pre-existing
`TestLastMeSensitive.test_me_change_password` and
`TestLastMeSensitive.test_me_reset_password` cases; their class remains marked
`Temporarily skip password-sensitive me endpoints`. They are outside the
security-contract file and were already skipped on the branch baseline.

## Running Tests

### Core workspace tests
```bash
BASE_URL=http://localhost:8000 pytest api/bfg_workspace/ -m api_integration -v
```

When the server runs with production HTTPS redirects behind a local HTTP
connection, add `BFG2_E2E_FORWARDED_PROTO=https` to emulate the terminating
reverse proxy without weakening the server's transport settings.

### Platform tests (both modes)
```bash
# Embedded mode
BASE_URL=http://localhost:8000 pytest api/bfg_platform/embedded/ -m api_integration -v

# Standalone mode
BASE_URL=http://localhost:8011 pytest api/bfg_platform/standalone/ -m api_integration -v
```

### Everything (workspace + platform)
```bash
pytest api/ -m api_integration -v
```

## Platform API integration

See **[PLATFORM_API_INTEGRATION.md](PLATFORM_API_INTEGRATION.md)** for full setup instructions for both platform modes.
