"""
E2E Test 20: Platform Embedded Mode

Tests Platform extension running in embedded mode (same BFG instance as workspaces).
Requires:
  - Server running with LOCAL_APPS=resale,platform
  - PLATFORM_WORKSPACE_SLUG=admin (or whatever the management workspace slug is)
  - PLATFORM_EMBEDDED=True (derived from the above)
  - A management workspace (slug matching PLATFORM_WORKSPACE_SLUG) already created
  - BASE_URL pointing to the server

Env vars (set in e2e/platform/embedded/.env, override project-root .env):
  BASE_URL                         — API base (e.g. http://localhost:8077)
  BFG2_E2E_PLATFORM_EMAIL          — platform admin email (StaffMember of management workspace)
  BFG2_E2E_PLATFORM_PASSWORD       — platform admin password
  BFG2_E2E_PLATFORM_WORKSPACE_SLUG — management workspace slug (default: "admin")

Flow:
  1. Login as platform admin → get JWT
  2. List workspaces via /platform/workspaces/me/ → verify StaffMember-based listing
  3. Create workspace via /platform/workspaces/ → verify direct DB creation
  4. Token Exchange → verify embedded mode returns JWT without cross-instance call
  5. Get subscription → verify null (new workspace)
  6. Get plans → verify public endpoint works
  7. Suspend workspace → verify is_active=False
  8. Resume workspace → verify is_active=True
  9. Permission: regular user cannot access platform admin APIs
"""

import os
import uuid
import pytest

from client_remote import RemoteAPIClient, get_base_url


def _get_base():
    return get_base_url(require=True)


def _login(base, email, password):
    """Login via token endpoint, return JWT access token."""
    import requests as http
    r = http.post(f"{base}/api/v1/auth/token/", json={"email": email, "password": password}, timeout=10)
    assert r.status_code == 200, f"Login failed for {email}: {r.status_code} {r.text[:200]}"
    return r.json()["access"]


def _platform_client(base, token, workspace_id=None):
    """Create a RemoteAPIClient with optional X-Workspace-ID for platform APIs."""
    from types import SimpleNamespace
    ws = SimpleNamespace(id=workspace_id, slug=None) if workspace_id else None
    return RemoteAPIClient(workspace=ws, token=token)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def base_url():
    return _get_base()


@pytest.fixture(scope="module")
def platform_slug():
    return os.environ.get("BFG2_E2E_PLATFORM_WORKSPACE_SLUG", "admin")


@pytest.fixture(scope="module")
def admin_token(base_url):
    # Embedded mode: platform runs inside the workspace server, so use the workspace superuser
    email = os.environ.get("BFG2_E2E_SUPERUSER_EMAIL")
    password = os.environ.get("BFG2_E2E_SUPERUSER_PASSWORD")
    if not email or not password:
        pytest.skip("BFG2_E2E_SUPERUSER_EMAIL/PASSWORD required for platform embedded e2e")
    return _login(base_url, email, password)


@pytest.fixture(scope="module")
def platform_client(base_url, admin_token):
    """Authenticated client for platform APIs (no workspace context needed for /me/)."""
    return _platform_client(base_url, admin_token)


@pytest.fixture
def new_workspace_slug():
    return f"e2e-embedded-{uuid.uuid4().hex[:8]}"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.e2e
class TestEmbeddedWorkspaceList:
    """Workspace listing in embedded mode uses StaffMember (same DB)."""

    def test_list_my_workspaces(self, platform_client, platform_slug):
        """GET /platform/workspaces/me/ returns workspaces via StaffMember."""
        r = platform_client.get("/api/v1/platform/workspaces/me/")
        assert r.status_code == 200, (r.status_code, r.data)
        assert "workspaces" in r.data
        assert isinstance(r.data["workspaces"], list)
        assert len(r.data["workspaces"]) >= 1

    def test_is_platform_admin(self, platform_client):
        """Superuser / management workspace StaffMember is recognized as platform admin."""
        r = platform_client.get("/api/v1/platform/workspaces/me/")
        assert r.data["is_platform_admin"] is True

    def test_platform_workspace_in_list(self, platform_client, platform_slug):
        """Management workspace should appear in the list."""
        r = platform_client.get("/api/v1/platform/workspaces/me/")
        slugs = [ws["slug"] for ws in r.data["workspaces"]]
        assert platform_slug in slugs, f"Expected '{platform_slug}' in {slugs}"

    def test_workspace_list_has_is_platform_flag(self, platform_client, platform_slug):
        """Each workspace entry should have is_platform flag."""
        r = platform_client.get("/api/v1/platform/workspaces/me/")
        for ws in r.data["workspaces"]:
            if ws["slug"] == platform_slug:
                assert ws.get("is_platform") is True
            else:
                assert ws.get("is_platform") is not True  # False or absent


@pytest.mark.e2e
class TestEmbeddedWorkspaceCreate:
    """Create workspace in embedded mode: direct DB creation."""

    def test_create_workspace(self, platform_client, new_workspace_slug):
        """POST /platform/workspaces/ creates workspace in same DB."""
        r = platform_client.post(
            "/api/v1/platform/workspaces/",
            {"name": f"E2E Test {new_workspace_slug}", "slug": new_workspace_slug},
        )
        assert r.status_code == 201, (r.status_code, r.data)

    def test_created_workspace_appears_in_list(self, platform_client, new_workspace_slug):
        """After creation, workspace appears in queryset-based list."""
        # Create first
        platform_client.post(
            "/api/v1/platform/workspaces/",
            {"name": f"E2E List Test {new_workspace_slug}", "slug": new_workspace_slug},
        )
        # List all (via queryset, not /me/)
        r = platform_client.get("/api/v1/platform/workspaces/")
        assert r.status_code == 200
        results = r.data if isinstance(r.data, list) else r.data.get("results", r.data)
        slugs = [ws.get("slug") for ws in results] if isinstance(results, list) else []
        assert new_workspace_slug in slugs, f"Expected '{new_workspace_slug}' in {slugs}"

    def test_create_duplicate_slug_fails(self, platform_client, platform_slug):
        """Duplicate slug should return 400."""
        r = platform_client.post(
            "/api/v1/platform/workspaces/",
            {"name": "Duplicate", "slug": platform_slug},
        )
        assert r.status_code == 400


@pytest.mark.e2e
class TestEmbeddedTokenExchange:
    """Token exchange in embedded mode: same JWT, no cross-instance HTTP."""

    def test_token_exchange_returns_jwt(self, platform_client, base_url, admin_token):
        """POST /platform/auth/token-exchange/ returns JWT for target workspace."""
        # First create a workspace to exchange into
        slug = f"e2e-te-{uuid.uuid4().hex[:8]}"
        platform_client.post(
            "/api/v1/platform/workspaces/",
            {"name": f"TE Test {slug}", "slug": slug},
        )

        r = platform_client.post(
            "/api/v1/platform/auth/token-exchange/",
            {"workspace_id": slug},
        )
        assert r.status_code == 200, (r.status_code, r.data)
        assert r.data.get("workspace_token") is not None
        assert len(r.data["workspace_token"]) > 0
        assert r.data.get("embedded") is True
        assert r.data["workspace"]["slug"] == slug

    def test_token_exchange_nonexistent_workspace(self, platform_client):
        """Token exchange for non-existent workspace returns 404."""
        r = platform_client.post(
            "/api/v1/platform/auth/token-exchange/",
            {"workspace_id": "does-not-exist-xyz"},
        )
        assert r.status_code in (403, 404)

    def test_token_exchange_missing_param(self, platform_client):
        """Token exchange without workspace_id returns 400."""
        r = platform_client.post(
            "/api/v1/platform/auth/token-exchange/",
            {},
        )
        assert r.status_code == 400


@pytest.mark.e2e
class TestEmbeddedSuspendResume:
    """Suspend and resume workspace lifecycle."""

    def _create_workspace(self, platform_client):
        slug = f"e2e-sr-{uuid.uuid4().hex[:8]}"
        r = platform_client.post(
            "/api/v1/platform/workspaces/",
            {"name": f"SR Test {slug}", "slug": slug},
        )
        assert r.status_code == 201
        return r.data["id"], slug

    def test_suspend_workspace(self, platform_client):
        """POST /platform/workspaces/{id}/suspend/ deactivates workspace."""
        ws_id, _ = self._create_workspace(platform_client)

        r = platform_client.post(
            f"/api/v1/platform/workspaces/{ws_id}/suspend/",
            {"reason": "e2e test suspension"},
        )
        assert r.status_code == 200

        # Verify workspace shows as suspended/inactive
        detail = platform_client.get(f"/api/v1/platform/workspaces/{ws_id}/")
        assert detail.status_code == 200
        assert detail.data.get("is_active") is False

    def test_resume_workspace(self, platform_client):
        """POST /platform/workspaces/{id}/resume/ reactivates workspace."""
        ws_id, _ = self._create_workspace(platform_client)

        # Suspend first
        platform_client.post(f"/api/v1/platform/workspaces/{ws_id}/suspend/")

        # Resume
        r = platform_client.post(f"/api/v1/platform/workspaces/{ws_id}/resume/")
        assert r.status_code == 200

        # Verify workspace is active again
        detail = platform_client.get(f"/api/v1/platform/workspaces/{ws_id}/")
        assert detail.status_code == 200
        assert detail.data.get("is_active") is True


@pytest.mark.e2e
class TestEmbeddedSubscription:
    """Subscription endpoints in embedded mode."""

    def test_get_subscription_none(self, platform_client):
        """New workspace should have no subscription."""
        slug = f"e2e-sub-{uuid.uuid4().hex[:8]}"
        r = platform_client.post(
            "/api/v1/platform/workspaces/",
            {"name": f"Sub Test {slug}", "slug": slug},
        )
        ws_id = r.data["id"]

        r = platform_client.get(f"/api/v1/platform/workspaces/{ws_id}/subscription/")
        assert r.status_code == 200
        assert r.data.get("subscription") is None


@pytest.mark.e2e
class TestEmbeddedPlans:
    """Plan listing (public endpoint)."""

    def test_list_plans(self, base_url):
        """GET /platform/plans/ should work without authentication."""
        anon = _platform_client(base_url, token=None)
        r = anon.get("/api/v1/platform/plans/")
        assert r.status_code == 200

    def test_plans_response_is_list(self, platform_client):
        """Plans endpoint should return a list (or paginated results)."""
        r = platform_client.get("/api/v1/platform/plans/")
        assert r.status_code == 200
        data = r.data
        if isinstance(data, dict):
            assert "results" in data
        else:
            assert isinstance(data, list)


@pytest.mark.e2e
class TestEmbeddedSSO:
    """SSO check endpoint (public)."""

    def test_sso_check_unknown_domain(self, base_url):
        """Domain without SSO config returns sso_enabled=False."""
        anon = _platform_client(base_url, token=None)
        r = anon.get("/api/v1/platform/auth/sso-check/?domain=no-sso-configured.xyz")
        assert r.status_code == 200
        assert r.data["sso_enabled"] is False

    def test_sso_check_empty_domain(self, base_url):
        """Empty domain returns sso_enabled=False."""
        anon = _platform_client(base_url, token=None)
        r = anon.get("/api/v1/platform/auth/sso-check/?domain=")
        assert r.status_code == 200
        assert r.data["sso_enabled"] is False


@pytest.mark.e2e
class TestEmbeddedPermission:
    """Non-admin users should have restricted access."""

    def test_unauthenticated_cannot_list_workspaces(self, base_url):
        """Unauthenticated user cannot access /platform/workspaces/me/."""
        anon = _platform_client(base_url, token=None)
        r = anon.get("/api/v1/platform/workspaces/me/")
        assert r.status_code in (401, 403)

    def test_unauthenticated_cannot_create_workspace(self, base_url):
        """Unauthenticated user cannot create workspace."""
        anon = _platform_client(base_url, token=None)
        r = anon.post(
            "/api/v1/platform/workspaces/",
            {"name": "Hacked", "slug": "hacked"},
        )
        assert r.status_code in (401, 403)

    def test_unauthenticated_cannot_token_exchange(self, base_url):
        """Unauthenticated user cannot do token exchange."""
        anon = _platform_client(base_url, token=None)
        r = anon.post(
            "/api/v1/platform/auth/token-exchange/",
            {"workspace_id": "anything"},
        )
        assert r.status_code in (401, 403)
