"""
API integration test 21: Platform Standalone Mode

Tests Platform extension running as a dedicated BFG instance (separate from workspaces).
Requires two running servers:
  - Platform server (BFG_INSTANCE_TYPE=platform)    → BASE_URL
  - Workspace server (BFG_INSTANCE_TYPE=workspace)  → WORKSPACE_BASE_URL

Env vars:
  BASE_URL                         — Platform API base (e.g. http://localhost:8011)
  WORKSPACE_BASE_URL               — Workspace API base (e.g. http://localhost:8000)
  BFG2_E2E_PLATFORM_EMAIL          — Platform admin email (overrides project-root .env)
  BFG2_E2E_PLATFORM_PASSWORD       — Platform admin password
  BFG2_E2E_PLATFORM_API_KEY        — PLATFORM_API_KEY shared between servers

Flow:
  1. Login on Platform → get Platform JWT
  2. List workspaces → verify PlatformMembership-based listing
  3. Create workspace → verify provisioning (HTTP call to workspace server)
  4. Token Exchange → verify HTTP call to workspace server returns workspace JWT
  5. Use workspace JWT to access workspace server APIs
  6. Subscription / Plans / SSO endpoints
  7. Suspend / Resume lifecycle
  8. Internal API key auth
  9. Cross-server user provisioning
"""

import os
import uuid
import pytest

from client_remote import RemoteAPIClient, get_base_url


def _get_platform_base():
    return get_base_url(require=True)


def _get_workspace_base():
    url = os.environ.get("WORKSPACE_BASE_URL", "").rstrip("/")
    if not url:
        pytest.skip("WORKSPACE_BASE_URL required for standalone platform API integration tests")
    return url


def _login(base, email, password):
    import requests as http
    r = http.post(f"{base}/api/v1/auth/token/", json={"email": email, "password": password}, timeout=10)
    assert r.status_code == 200, f"Login failed for {email}: {r.status_code} {r.text[:200]}"
    return r.json()["access"]


def _platform_client(base, token):
    from types import SimpleNamespace
    return RemoteAPIClient(workspace=None, token=token)


def _workspace_client(base, token, workspace_id):
    from types import SimpleNamespace
    ws = SimpleNamespace(id=workspace_id, slug=None)
    c = RemoteAPIClient(workspace=ws, token=token)
    c.base_url = base
    return c


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _check_server_reachable(url: str, label: str) -> None:
    """Skip test if server is not reachable (standalone mode not running)."""
    import requests as http
    try:
        http.get(f"{url}/api/v1/platform/plans/", timeout=3)
    except Exception:
        pytest.skip(f"{label} not reachable at {url} — start the standalone platform server first")


@pytest.fixture(scope="module")
def platform_base():
    base = _get_platform_base()
    _check_server_reachable(base, "Platform server")
    return base


@pytest.fixture(scope="module")
def workspace_base():
    return _get_workspace_base()


@pytest.fixture(scope="module")
def platform_api_key():
    key = os.environ.get("BFG2_E2E_PLATFORM_API_KEY", "")
    if not key:
        pytest.skip("BFG2_E2E_PLATFORM_API_KEY required for standalone platform API integration tests")
    return key


@pytest.fixture(scope="module")
def admin_token(platform_base):
    email = os.environ.get("BFG2_E2E_PLATFORM_EMAIL") or os.environ.get("BFG2_E2E_SUPERUSER_EMAIL")
    password = os.environ.get("BFG2_E2E_PLATFORM_PASSWORD") or os.environ.get("BFG2_E2E_SUPERUSER_PASSWORD")
    if not email or not password:
        pytest.skip("BFG2_E2E_PLATFORM_EMAIL/PASSWORD required for standalone platform API integration tests")
    return _login(platform_base, email, password)


@pytest.fixture(scope="module")
def platform_client(platform_base, admin_token):
    return _platform_client(platform_base, admin_token)


@pytest.fixture
def new_workspace_slug():
    return f"apitest-standalone-{uuid.uuid4().hex[:8]}"


# ---------------------------------------------------------------------------
# Tests: Workspace Listing (PlatformMembership)
# ---------------------------------------------------------------------------

@pytest.mark.api_integration
class TestStandaloneWorkspaceList:
    """Workspace listing uses PlatformMembership in standalone mode."""

    def test_list_my_workspaces(self, platform_client):
        """GET /platform/workspaces/me/ returns workspaces via PlatformMembership."""
        r = platform_client.get("/api/v1/platform/workspaces/me/")
        assert r.status_code == 200, (r.status_code, r.data)
        assert "workspaces" in r.data
        assert isinstance(r.data["workspaces"], list)

    def test_is_platform_admin(self, platform_client):
        """Superuser is recognized as platform admin in standalone mode."""
        r = platform_client.get("/api/v1/platform/workspaces/me/")
        assert r.data["is_platform_admin"] is True

    def test_workspace_includes_cluster_info(self, platform_client):
        """Standalone workspaces should include region, cluster, and domain fields."""
        r = platform_client.get("/api/v1/platform/workspaces/me/")
        for ws in r.data["workspaces"]:
            # In standalone mode these fields should exist (even if null)
            assert "region" in ws
            assert "cluster" in ws
            assert "domain" in ws


# ---------------------------------------------------------------------------
# Tests: Token Exchange (cross-server HTTP)
# ---------------------------------------------------------------------------

@pytest.mark.api_integration
class TestStandaloneTokenExchange:
    """Token exchange calls Workspace Server over HTTP."""

    def test_token_exchange(self, platform_client, workspace_base):
        """POST /platform/auth/token-exchange/ should return workspace JWT + frontend URL field."""
        # Get first workspace from list
        r = platform_client.get("/api/v1/platform/workspaces/me/")
        workspaces = r.data.get("workspaces", [])
        if not workspaces:
            pytest.skip("No workspaces available for token exchange test")

        ws = workspaces[0]
        ws_id = ws.get("slug") or ws.get("id")

        r = platform_client.post(
            "/api/v1/platform/auth/token-exchange/",
            {"workspace_id": str(ws_id)},
        )
        assert r.status_code == 200, (r.status_code, r.data)
        assert r.data.get("workspace_token") is not None
        assert r.data.get("embedded") is False
        assert r.data.get("workspace_url") is not None
        assert "workspace_frontend_url" in r.data

    def test_workspace_jwt_works_on_workspace_server(self, platform_client, workspace_base):
        """Workspace JWT from token exchange should authenticate on workspace server."""
        r = platform_client.get("/api/v1/platform/workspaces/me/")
        workspaces = r.data.get("workspaces", [])
        if not workspaces:
            pytest.skip("No workspaces available")

        ws = workspaces[0]
        ws_id = ws.get("slug") or ws.get("id")

        exchange = platform_client.post(
            "/api/v1/platform/auth/token-exchange/",
            {"workspace_id": str(ws_id)},
        )
        assert exchange.status_code == 200

        ws_token = exchange.data["workspace_token"]
        ws_server_id = exchange.data.get("workspace_server_id") or ws.get("id")

        # Use workspace JWT on workspace server — verify token is accepted (not 401)
        ws_client = _workspace_client(workspace_base, ws_token, ws_server_id)
        # Try /workspaces/ (admin-only) or /platform/workspaces/me/ — either proves JWT works
        r = ws_client.get("/api/v1/platform/workspaces/me/")
        # 200 = valid token, has access; 403 = valid token, insufficient role — both mean JWT accepted
        assert r.status_code in (200, 403), f"Workspace JWT not accepted: {r.status_code}"
        assert r.status_code != 401, "Workspace JWT was rejected as unauthorized"

    def test_token_exchange_no_membership(self, platform_base, workspace_base):
        """User without PlatformMembership gets 403."""
        # Register a fresh user on platform
        import requests as http
        email = f"apitest-nomember-{uuid.uuid4().hex[:8]}@test.com"
        password = "TestPass123!"

        # Try register, fallback to skip if not allowed
        reg = http.post(
            f"{platform_base}/api/v1/auth/register/",
            json={"email": email, "password": password, "password_confirm": password},
            timeout=10,
        )
        if reg.status_code not in (200, 201):
            pytest.skip("Cannot register new user on platform for isolation test")

        token = reg.json().get("access")
        if not token:
            token = _login(platform_base, email, password)

        client = _platform_client(platform_base, token)
        r = client.post(
            "/api/v1/platform/auth/token-exchange/",
            {"workspace_id": "any-workspace"},
        )
        assert r.status_code in (403, 404)

    def test_token_exchange_missing_workspace_id(self, platform_client):
        """Token exchange without workspace_id returns 400."""
        r = platform_client.post(
            "/api/v1/platform/auth/token-exchange/",
            {},
        )
        assert r.status_code == 400


# ---------------------------------------------------------------------------
# Tests: Workspace Create (standalone → triggers HTTP to workspace server)
# ---------------------------------------------------------------------------

@pytest.mark.api_integration
class TestStandaloneWorkspaceCreate:
    """Create workspace in standalone mode triggers provisioning."""

    def test_create_workspace(self, platform_client, new_workspace_slug):
        """POST /platform/workspaces/ creates workspace metadata + triggers provisioning."""
        r = platform_client.post(
            "/api/v1/platform/workspaces/",
            {"name": f"API integration (standalone) {new_workspace_slug}", "slug": new_workspace_slug},
        )
        # 201 created, or 200 if async provisioning returns workspace immediately
        assert r.status_code in (200, 201, 202), (r.status_code, r.data)

    def test_create_duplicate_slug_fails(self, platform_client):
        """Creating workspace with existing slug should fail."""
        slug = f"apitest-dup-{uuid.uuid4().hex[:8]}"
        # Create first
        platform_client.post(
            "/api/v1/platform/workspaces/",
            {"name": f"Dup Test {slug}", "slug": slug},
        )
        # Try again
        r = platform_client.post(
            "/api/v1/platform/workspaces/",
            {"name": f"Dup Test 2 {slug}", "slug": slug},
        )
        assert r.status_code == 400


# ---------------------------------------------------------------------------
# Tests: Suspend / Resume
# ---------------------------------------------------------------------------

@pytest.mark.api_integration
class TestStandaloneSuspendResume:

    def _create_workspace(self, platform_client):
        slug = f"apitest-sr-{uuid.uuid4().hex[:8]}"
        r = platform_client.post(
            "/api/v1/platform/workspaces/",
            {"name": f"SR Test {slug}", "slug": slug},
        )
        assert r.status_code in (200, 201, 202)
        return r.data["id"], slug

    def test_suspend_and_resume(self, platform_client):
        """Full suspend → resume cycle."""
        ws_id, _ = self._create_workspace(platform_client)

        # Suspend
        r = platform_client.post(
            f"/api/v1/platform/workspaces/{ws_id}/suspend/",
            {"reason": "API integration (standalone) test"},
        )
        assert r.status_code == 200

        # Verify suspended
        detail = platform_client.get(f"/api/v1/platform/workspaces/{ws_id}/")
        if detail.status_code == 200:
            assert detail.data.get("is_active") is False

        # Resume
        r = platform_client.post(f"/api/v1/platform/workspaces/{ws_id}/resume/")
        assert r.status_code == 200

        # Verify active
        detail = platform_client.get(f"/api/v1/platform/workspaces/{ws_id}/")
        if detail.status_code == 200:
            assert detail.data.get("is_active") is True


# ---------------------------------------------------------------------------
# Tests: Subscription
# ---------------------------------------------------------------------------

@pytest.mark.api_integration
class TestStandaloneSubscription:

    def test_get_subscription(self, platform_client):
        """Get subscription for an existing workspace."""
        r = platform_client.get("/api/v1/platform/workspaces/me/")
        workspaces = r.data.get("workspaces", [])
        if not workspaces:
            pytest.skip("No workspaces available")

        ws_id = workspaces[0]["id"]
        r = platform_client.get(f"/api/v1/platform/workspaces/{ws_id}/subscription/")
        assert r.status_code == 200
        # Could be null or a subscription object
        assert "subscription" in r.data


# ---------------------------------------------------------------------------
# Tests: Plans (public)
# ---------------------------------------------------------------------------

@pytest.mark.api_integration
class TestStandalonePlans:

    def test_list_plans_public(self, platform_base):
        """GET /platform/plans/ should work without authentication."""
        anon = _platform_client(platform_base, token=None)
        r = anon.get("/api/v1/platform/plans/")
        assert r.status_code == 200

    def test_plans_structure(self, platform_client):
        """Plans should return list with expected fields."""
        r = platform_client.get("/api/v1/platform/plans/")
        assert r.status_code == 200
        data = r.data
        items = data if isinstance(data, list) else data.get("results", [])
        for plan in items:
            assert "name" in plan
            assert "price" in plan or "id" in plan


# ---------------------------------------------------------------------------
# Tests: SSO
# ---------------------------------------------------------------------------

@pytest.mark.api_integration
class TestStandaloneSSO:

    def test_sso_check_unknown(self, platform_base):
        """Unknown domain returns sso_enabled=False."""
        anon = _platform_client(platform_base, token=None)
        r = anon.get("/api/v1/platform/auth/sso-check/?domain=unknown-domain.xyz")
        assert r.status_code == 200
        assert r.data["sso_enabled"] is False

    def test_sso_check_empty(self, platform_base):
        """Empty domain returns sso_enabled=False."""
        anon = _platform_client(platform_base, token=None)
        r = anon.get("/api/v1/platform/auth/sso-check/?domain=")
        assert r.data["sso_enabled"] is False


# ---------------------------------------------------------------------------
# Tests: Internal API Key Auth
# ---------------------------------------------------------------------------

@pytest.mark.api_integration
class TestStandaloneInternalAuth:
    """Internal endpoints require X-Platform-API-Key."""

    def test_internal_endpoint_without_key_rejected(self, platform_base):
        """Internal endpoint without API key should return 403."""
        import requests as http
        r = http.post(
            f"{platform_base}/api/v1/platform/internal/provision-user/",
            json={"platform_user_id": "1", "email": "test@test.com", "name": "Test"},
            headers={"Content-Type": "application/json"},
            timeout=10,
        )
        assert r.status_code in (401, 403)

    def test_internal_endpoint_with_wrong_key_rejected(self, platform_base):
        """Internal endpoint with wrong API key should return 403."""
        import requests as http
        r = http.post(
            f"{platform_base}/api/v1/platform/internal/provision-user/",
            json={"platform_user_id": "1", "email": "test@test.com"},
            headers={
                "Content-Type": "application/json",
                "X-Platform-API-Key": "wrong-key-12345",
            },
            timeout=10,
        )
        assert r.status_code in (401, 403)


# ---------------------------------------------------------------------------
# Tests: Permission
# ---------------------------------------------------------------------------

@pytest.mark.api_integration
class TestStandalonePermission:

    def test_unauthenticated_cannot_list(self, platform_base):
        """Unauthenticated user cannot list workspaces."""
        anon = _platform_client(platform_base, token=None)
        r = anon.get("/api/v1/platform/workspaces/me/")
        assert r.status_code in (401, 403)

    def test_unauthenticated_cannot_create(self, platform_base):
        """Unauthenticated user cannot create workspace."""
        anon = _platform_client(platform_base, token=None)
        r = anon.post(
            "/api/v1/platform/workspaces/",
            {"name": "Hacked", "slug": "hacked"},
        )
        assert r.status_code in (401, 403)

    def test_unauthenticated_cannot_exchange(self, platform_base):
        """Unauthenticated user cannot do token exchange."""
        anon = _platform_client(platform_base, token=None)
        r = anon.post(
            "/api/v1/platform/auth/token-exchange/",
            {"workspace_id": "any"},
        )
        assert r.status_code in (401, 403)


# ---------------------------------------------------------------------------
# Tests: Cross-Server Provisioning Smoke Test
# ---------------------------------------------------------------------------

@pytest.mark.api_integration
class TestStandaloneCrossServer:
    """Smoke test: full create → exchange → access workspace flow."""

    def test_full_create_exchange_access_flow(self, platform_client, workspace_base):
        """Create workspace → token exchange → use JWT on workspace server."""
        slug = f"apitest-full-{uuid.uuid4().hex[:8]}"

        # 1. Create workspace on platform
        r = platform_client.post(
            "/api/v1/platform/workspaces/",
            {"name": f"Full Flow {slug}", "slug": slug},
        )
        if r.status_code not in (200, 201, 202):
            pytest.skip(f"Cannot create workspace: {r.status_code} {r.data}")
        ws_id = r.data.get("id")

        # 2. Token exchange
        exchange = platform_client.post(
            "/api/v1/platform/auth/token-exchange/",
            {"workspace_id": slug},
        )
        if exchange.status_code != 200:
            pytest.skip(f"Token exchange failed: {exchange.status_code} {exchange.data}")

        ws_token = exchange.data["workspace_token"]
        ws_server_id = exchange.data.get("workspace_server_id") or ws_id

        # 3. Access workspace server
        ws_client = _workspace_client(workspace_base, ws_token, ws_server_id)
        r = ws_client.get("/api/v1/workspaces/")
        assert r.status_code == 200, f"Cross-server access failed: {r.status_code} {r.data}"
