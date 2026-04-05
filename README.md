# BFG2 HTTP E2E Test Suite

HTTP-only end-to-end tests against a live BFG2 server. No Django ORM — every test uses the real HTTP API.

## Quick Start

```bash
pip install -r requirements.txt
cp .env.example .env      # fill in your credentials
BASE_URL=http://localhost:8000 pytest e2e/ -m e2e -v
```

## Directory Layout

```
bfg-server-test-e2e/
├── conftest.py              # global fixtures (session bootstrap, workspace creation)
├── client_remote.py         # RemoteAPIClient (mimics DRF test client over HTTP)
├── .env                     # local credentials (git-ignored)
├── .env.example             # template
├── pytest.ini
├── requirements.txt
└── e2e/
    ├── test_01_registration.py
    ├── test_02_website_setup.py
    ├── ...                  # core workspace tests (01–18)
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
BASE_URL=http://localhost:8000 pytest e2e/ -m e2e -v --ignore=e2e/bfg_platform
```

### Platform tests (both modes)
```bash
# Embedded mode
BASE_URL=http://localhost:8000 pytest e2e/bfg_platform/embedded/ -m e2e -v

# Standalone mode
BASE_URL=http://localhost:8011 pytest e2e/bfg_platform/standalone/ -m e2e -v
```

### Everything
```bash
pytest e2e/ -m e2e -v
```

## Platform E2E

See **[PLATFORM_E2E.md](PLATFORM_E2E.md)** for full setup instructions for both platform modes.
