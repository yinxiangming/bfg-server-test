# BFG2 HTTP API Integration Test Suite

HTTP API integration tests against a live BFG2 server. No Django ORM — every test uses the real HTTP API.

> Credentials use the `BFG2_E2E_*` environment variable prefix for historical compatibility with existing setups.

## Quick Start

```bash
pip install -r requirements.txt
cp .env.example .env      # fill in your credentials
BASE_URL=http://localhost:8000 pytest api/bfg_workspace/ -m api_integration -v
```

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

See `.env.example` for the full list.

## Running Tests

### Core workspace tests
```bash
BASE_URL=http://localhost:8000 pytest api/bfg_workspace/ -m api_integration -v
```

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
