"""
Pytest fixtures for BFG2 HTTP API integration tests. Pure API mode only: BASE_URL must be set.
All data is created via HTTP API; no ORM in fixtures.
These tests do not use @pytest.mark.django_db: they never touch the pytest-process test DB, only the live API.

Run: BASE_URL=http://localhost:8000 pytest api/bfg_workspace/ -m api_integration
Full tree (workspace + platform): pytest api/ -m api_integration

When BFG2_E2E_SUPERUSER_* are set and BASE_URL is :8000 or a local host, that
pre-seeded bootstrap user creates both workspaces (if the API allows).

Optional register-mode identities (when not using superuser bootstrap), e.g. another
backend already has the default emails: BFG2_E2E_CUSTOMER_EMAIL,
BFG2_E2E_CUSTOMER2_EMAIL, BFG2_E2E_ADMIN2_EMAIL (defaults: customer_apitest@test.com, …).

Roles:
- bootstrap / workspace admin: creates workspaces
- ws1 admin/customer/anonymous, ws2 admin/customer/anonymous
"""

import os
import urllib.parse
from pathlib import Path

# Load .env from project root or parent directories; fallback to cwd/.env
try:
    from dotenv import load_dotenv
    _conftest_file = Path(__file__).resolve()
    _server_env = _conftest_file.parent.parent.parent / ".env"
    _base_url_preserved = os.environ.get("BASE_URL")
    if _server_env.is_file():
        load_dotenv(_server_env, override=True)
    elif (Path.cwd() / ".env").is_file():
        load_dotenv(Path.cwd() / ".env", override=True)
    if _base_url_preserved:
        os.environ["BASE_URL"] = _base_url_preserved
except ImportError:
    pass
import uuid
import base64
import json
import pytest
import requests
from decimal import Decimal
from types import SimpleNamespace

from client_remote import RemoteAPIClient, get_base_url


def _get_base_url():
    return get_base_url(require=True)


def _decode_user_id_from_token(token):
    payload_b64 = token.split(".")[1]
    payload_b64 += "=" * (-len(payload_b64) % 4)
    payload = json.loads(base64.urlsafe_b64decode(payload_b64).decode("utf-8"))
    user_id = payload.get("user_id") or payload.get("userId") or payload.get("uid") or payload.get("id")
    assert user_id is not None, "Could not decode user_id from JWT"
    try:
        return int(user_id)
    except (TypeError, ValueError):
        return user_id


def _get_token(base, identifier, password):
    """
    Get JWT (POST /api/v1/auth/token/). Tries username and email JSON shapes;
    optional BFG2_E2E_AUTH_LOGIN_EMAIL when superuser is username-only but API expects email.
    """
    url = f"{base.rstrip('/')}/api/v1/auth/token/"
    alt_email = os.environ.get("BFG2_E2E_AUTH_LOGIN_EMAIL")
    attempts = []
    if "@" in identifier:
        attempts.append({"email": identifier, "password": password})
    else:
        attempts.append({"username": identifier, "password": password})
        attempts.append({"email": identifier, "password": password})
    if alt_email and alt_email.strip() and alt_email != identifier:
        attempts.append({"email": alt_email.strip(), "password": password})
    seen = set()
    bodies = []
    for body in attempts:
        key = tuple(sorted(body.items()))
        if key in seen:
            continue
        seen.add(key)
        bodies.append(body)
    last = None
    last_error = None
    for body in bodies:
        try:
            last = requests.post(url, json=body, timeout=10)
        except Exception as exc:
            last_error = exc
            continue
        if last.status_code == 200:
            token = last.json().get("access")
            if token:
                return {"token": token, "user_id": _decode_user_id_from_token(token)}
    # requests.Response is falsy for non-2xx; use explicit None checks.
    snippet = getattr(last, "text", "")[:300] if last is not None else ""
    if last is None and last_error is not None:
        raise AssertionError(f"Could not get token for {identifier}: request failed: {last_error}")
    status = last.status_code if last is not None else "?"
    raise AssertionError(f"Could not get token for {identifier}: {status} {snippet}")


def _login_only(base, identifier, password):
    """Login via token endpoint only (no register). Use for pre-seeded superuser."""
    return _get_token(base, identifier, password)


def _register_and_login(base, email, password, first_name="API", last_name="Integration"):
    """Register user (or login if exists). Returns {token, user_id}."""
    r = requests.post(
        f"{base}/api/v1/auth/register/",
        json={
            "email": email,
            "password": password,
            "password_confirm": password,
            "first_name": first_name,
            "last_name": last_name,
        },
        timeout=10,
    )
    if r.status_code in (200, 201):
        token = r.json().get("access")
        if token:
            return {"token": token, "user_id": _decode_user_id_from_token(token)}
    # Fallback: get token via token endpoint (same as login)
    return _get_token(base, email, password)


def _create_workspace(base, token, name, slug):
    """Create workspace with given token. Returns {id, slug}."""
    r = requests.post(
        f"{base}/api/v1/workspaces/",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"name": name, "slug": slug, "email": "apitest@example.com"},
        timeout=10,
    )
    if r.status_code == 201:
        d = r.json()
        return {"id": d["id"], "slug": d["slug"]}
    r2 = requests.get(
        f"{base}/api/v1/workspaces/",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        timeout=10,
    )
    assert r2.status_code == 200, r2.text
    data = r2.json()
    results = data.get("results") if isinstance(data, dict) else data or []
    for item in results:
        if item.get("slug") == slug:
            return {"id": item["id"], "slug": item.get("slug", slug)}
    assert results, "No workspaces found"
    return {"id": results[0]["id"], "slug": results[0].get("slug", slug)}


def _create_customer_in_workspace(base, token, workspace_id, user_id):
    """Create customer record in workspace. Returns customer dict."""
    for payload in [{"user_id": user_id, "company_name": "Test Co", "tax_number": "TAX"}, {"user": user_id, "company_name": "Test Co", "tax_number": "TAX"}]:
        r = requests.post(
            f"{base}/api/v1/customers/",
            headers={
                "Authorization": f"Bearer {token}",
                "X-Workspace-Id": str(workspace_id),
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=10,
        )
        if r.status_code == 201:
            return r.json()
    raise AssertionError(f"Could not create customer in workspace {workspace_id}: {r.text}")


def _add_user_as_staff(base, admin_token, workspace_id, user_id, role_code="admin"):
    """Add an existing user as StaffMember of a workspace.

    Looks up the role by code in the target workspace and POSTs to
    /api/v1/staff-members/. Caller's ``admin_token`` must belong to a
    user with admin / superuser-bypass access in that workspace.
    """
    role_resp = requests.get(
        f"{base}/api/v1/staff-roles/",
        headers={
            "Authorization": f"Bearer {admin_token}",
            "X-Workspace-Id": str(workspace_id),
            "Content-Type": "application/json",
        },
        timeout=10,
    )
    if role_resp.status_code != 200:
        raise AssertionError(f"Could not list staff-roles for workspace {workspace_id}: "
                             f"{role_resp.status_code} {role_resp.text[:200]}")
    body = role_resp.json()
    roles = body.get("results", body) if isinstance(body, dict) else body
    role_id = next((r["id"] for r in roles if r.get("code") == role_code), None)
    if role_id is None:
        raise AssertionError(f"No staff role with code={role_code!r} in workspace {workspace_id}; "
                             f"available={[r.get('code') for r in roles]}")
    r = requests.post(
        f"{base}/api/v1/staff-members/",
        headers={
            "Authorization": f"Bearer {admin_token}",
            "X-Workspace-Id": str(workspace_id),
            "Content-Type": "application/json",
        },
        json={"user_id": user_id, "role_id": role_id},
        timeout=10,
    )
    if r.status_code in (200, 201):
        return r.json()
    if r.status_code == 400 and "already" in r.text.lower():
        return None  # already a member, treat as success
    raise AssertionError(f"Could not add user {user_id} as staff of workspace {workspace_id}: "
                         f"{r.status_code} {r.text[:200]}")


def _activate_user(base, admin_token, workspace_id, user_id):
    """Best-effort: force ``is_active=True`` on a freshly-registered user.

    Workspace servers with ``EMAIL_VERIFICATION_REQUIRED=true`` deactivate
    new accounts at register time pending email confirmation. Tests have
    no mailbox, so we ask the admin UserViewSet to flip the flag back on.
    UserViewSet only sees users who are members of the workspace, so this
    only succeeds when ``user_id`` already has a StaffMember (or
    default_workspace) — for customer-only users it will 404 silently.
    Set ``EMAIL_VERIFICATION_REQUIRED=false`` server-side to skip this
    dance entirely.
    """
    try:
        r = requests.patch(
            f"{base}/api/v1/users/{user_id}/",
            headers={
                "Authorization": f"Bearer {admin_token}",
                "X-Workspace-Id": str(workspace_id),
                "Content-Type": "application/json",
            },
            json={"is_active": True},
            timeout=10,
        )
    except Exception:
        return
    # 200/202 = activated, 404 = not visible (customer-only user, OK to skip).
    if r.status_code not in (200, 202, 404):
        # Surface unexpected errors loudly so they don't masquerade as
        # downstream "user inactive" failures.
        raise AssertionError(f"Could not activate user {user_id} in workspace {workspace_id}: "
                             f"{r.status_code} {r.text[:200]}")


def _ensure_workspace_admin(base, bootstrap_token, workspace_id, email, password,
                            first_name, last_name):
    """
    Make sure ``email`` exists, is an admin StaffMember of ``workspace_id``,
    and return a JWT for them.

    The token returned is the register-time access token. At register
    time, the user has no memberships yet so
    ``CustomTokenObtainPairSerializer._resolve_workspace_id`` returns
    ``None`` — the JWT therefore carries no ``workspace_id`` claim and
    ``WorkspaceMiddleware`` falls back to the ``X-Workspace-Id`` request
    header for tenant resolution. That's exactly what each per-workspace
    admin client needs.

    We deliberately skip a re-login because workspace servers with
    ``EMAIL_VERIFICATION_REQUIRED=true`` flip the user inactive after
    register, and ``/auth/token/`` rejects inactive accounts. The
    register-time token still authenticates because simplejwt does not
    re-check ``is_active`` on each request.
    """
    user = _register_and_login(base, email, password, first_name, last_name)
    _add_user_as_staff(base, bootstrap_token, workspace_id, user["user_id"], role_code="admin")
    _activate_user(base, bootstrap_token, workspace_id, user["user_id"])
    # Re-login now that the user is active again so the JWT picks up the
    # new StaffMember (claim resolves to ``workspace_id``) — but if login
    # fails (e.g. simplejwt rejects re-issued claims), fall back to the
    # register-time token, which is still valid now that the user is active.
    try:
        fresh = _get_token(base, email, password)
        return {"token": fresh["token"], "user_id": user["user_id"]}
    except AssertionError:
        return {"token": user["token"], "user_id": user["user_id"]}


def _is_local_api_host(base: str) -> bool:
    try:
        u = urllib.parse.urlparse(base)
        host = (u.hostname or "").lower()
        return host in ("localhost", "127.0.0.1", "::1", "0.0.0.0")
    except Exception:
        return False


def _use_bootstrap_superuser(base):
    """Use pre-seeded superuser when env is set and host is local Django port or any local API."""
    if not (os.environ.get("BFG2_E2E_SUPERUSER_EMAIL") and os.environ.get("BFG2_E2E_SUPERUSER_PASSWORD")):
        return False
    b = base.rstrip("/")
    if b.endswith(":8000") or ":8000/" in base:
        return True
    return _is_local_api_host(base)


def _require_bootstrap_superuser_env(base):
    """Require bootstrap credentials when default local Django port is used without them."""
    b = base.rstrip("/")
    if not (b.endswith(":8000") or ":8000/" in base):
        return
    if os.environ.get("BFG2_E2E_SUPERUSER_EMAIL") and os.environ.get("BFG2_E2E_SUPERUSER_PASSWORD"):
        return
    pytest.fail(
        "API integration tests with BASE_URL ending in :8000 require a pre-seeded bootstrap user. "
        "Set BFG2_E2E_SUPERUSER_EMAIL and BFG2_E2E_SUPERUSER_PASSWORD "
        "(see your BFG2 server documentation for bootstrap setup)."
    )


@pytest.fixture(scope="session")
def _session():
    """
    Bootstrap: superadmin creates ws1/ws2; register admin and customer per workspace.
    Returns dict with superadmin_token, ws1, ws2 (each with workspace, admin_token, customer_token, customer, etc).
    When BFG2_E2E_SUPERUSER_* are set and host is :8000 or local, one bootstrap user creates both workspaces.
    """
    base = _get_base_url()
    _require_bootstrap_superuser_env(base)
    admin_email = os.environ.get("BFG2_E2E_ADMIN_EMAIL") or "admin@test.com"
    admin_password = os.environ.get("BFG2_E2E_ADMIN_PASSWORD")
    customer_password = os.environ.get("BFG2_E2E_CUSTOMER_PASSWORD")
    customer_email = os.environ.get("BFG2_E2E_CUSTOMER_EMAIL") or "customer_apitest@test.com"
    customer2_email = os.environ.get("BFG2_E2E_CUSTOMER2_EMAIL") or "customer2_apitest@test.com"
    admin2_email = os.environ.get("BFG2_E2E_ADMIN2_EMAIL") or "admin2_apitest@test.com"
    if not customer_password:
        pytest.fail(
            "BFG2_E2E_CUSTOMER_PASSWORD must be set in env for API integration tests (customer accounts)"
        )
    use_superuser = _use_bootstrap_superuser(base)
    if use_superuser:
        superuser_email = os.environ.get("BFG2_E2E_SUPERUSER_EMAIL")
        superuser_password = os.environ.get("BFG2_E2E_SUPERUSER_PASSWORD")
    else:
        if not admin_password:
            pytest.fail("BFG2_E2E_ADMIN_PASSWORD must be set in env when not using superuser")

    # ── Bootstrap user creates the test workspaces ──────────────────────
    # In superuser mode this is a privileged account that can create
    # workspaces freely. In non-superuser mode we re-use the legacy admin
    # account; tests where create-workspace is gated to superusers will
    # surface as bootstrap errors there.
    if use_superuser:
        bootstrap = _login_only(base, superuser_email, superuser_password)
    else:
        bootstrap = _register_and_login(base, admin_email, admin_password, "Admin", "Integration")
    bootstrap_token = bootstrap["token"]

    # ── ws1: workspace + per-workspace admin/customer with their own JWTs ──
    ws1_slug = f"test-workspace-{uuid.uuid4().hex[:6]}"
    ws1 = _create_workspace(base, bootstrap_token, "Test Workspace", ws1_slug)

    # Per-workspace admin user — unique email so each test session gets a
    # fresh StaffMember row whose JWT claim resolves to ws1 only.
    ws1_admin_email = f"admin1_{uuid.uuid4().hex[:8]}@apitest.test"
    ws1_admin_password = customer_password  # any valid password — reuse for simplicity
    u1 = _ensure_workspace_admin(
        base, bootstrap_token, ws1["id"],
        ws1_admin_email, ws1_admin_password, "Admin1", "Integration",
    )

    # Per-workspace customer (separate user from admin so isolation tests
    # can verify ws1.customer.id != ws2.customer.id).
    ws1_customer_email = f"customer1_{uuid.uuid4().hex[:8]}@apitest.test"
    u2 = _register_and_login(base, ws1_customer_email, customer_password, "Customer1", "Integration")
    _activate_user(base, bootstrap_token, ws1["id"], u2["user_id"])
    cust1 = _create_customer_in_workspace(base, u1["token"], ws1["id"], u2["user_id"])

    # ── ws2: same pattern with its own admin + customer ────────────────
    ws2_slug = f"test-workspace-2-{uuid.uuid4().hex[:6]}"
    ws2 = _create_workspace(base, bootstrap_token, "Test Workspace 2", ws2_slug)

    ws2_admin_email = f"admin2_{uuid.uuid4().hex[:8]}@apitest.test"
    u3 = _ensure_workspace_admin(
        base, bootstrap_token, ws2["id"],
        ws2_admin_email, ws1_admin_password, "Admin2", "Integration",
    )
    ws2_customer_email = f"customer2_{uuid.uuid4().hex[:8]}@apitest.test"
    u4 = _register_and_login(base, ws2_customer_email, customer_password, "Customer2", "Integration")
    _activate_user(base, bootstrap_token, ws2["id"], u4["user_id"])
    cust2 = _create_customer_in_workspace(base, u3["token"], ws2["id"], u4["user_id"])

    return {
        "superadmin_token": bootstrap_token,
        "ws1": {
            "workspace": ws1,
            "admin_token": u1["token"],
            "admin_user_id": u1["user_id"],
            "customer_token": u2["token"],
            "customer_user_id": u2["user_id"],
            "customer": cust1,
        },
        "ws2": {
            "workspace": ws2,
            "admin_token": u3["token"],
            "admin_user_id": u3["user_id"],
            "customer_token": u4["token"],
            "customer_user_id": u4["user_id"],
            "customer": cust2,
        },
    }


# --- Workspace 1 fixtures (main) ---

@pytest.fixture
def workspace(_session):
    ws = _session["ws1"]["workspace"]
    return SimpleNamespace(id=ws["id"], slug=ws["slug"])


@pytest.fixture
def user(_session):
    return SimpleNamespace(id=_session["ws1"]["admin_user_id"])


@pytest.fixture
def customer(_session):
    c = _session["ws1"]["customer"]
    return SimpleNamespace(
        id=c["id"],
        customer_number=c.get("customer_number"),
        company_name=c.get("company_name"),
        tax_number=c.get("tax_number"),
    )


@pytest.fixture
def customer_user_key():
    return "user_id"


@pytest.fixture
def customer_user(_session):
    return SimpleNamespace(
        id=_session["ws1"]["customer_user_id"],
        token=_session["ws1"]["customer_token"],
    )


@pytest.fixture
def admin_client(workspace, _session):
    return RemoteAPIClient(workspace=workspace, token=_session["ws1"]["admin_token"])


@pytest.fixture
def authenticated_client(admin_client):
    return admin_client


@pytest.fixture
def customer_client(workspace, _session):
    return RemoteAPIClient(workspace=workspace, token=_session["ws1"]["customer_token"])


@pytest.fixture
def anonymous_api_client(workspace):
    return RemoteAPIClient(workspace=workspace, token=None)


@pytest.fixture
def api_client(workspace, _session):
    return RemoteAPIClient(workspace=workspace, token=_session["ws1"]["admin_token"])


# --- Workspace 2 fixtures (isolation tests) ---

@pytest.fixture
def workspace2(_session):
    ws = _session["ws2"]["workspace"]
    return SimpleNamespace(id=ws["id"], slug=ws["slug"])


@pytest.fixture
def admin_client2(workspace2, _session):
    return RemoteAPIClient(workspace=workspace2, token=_session["ws2"]["admin_token"])


@pytest.fixture
def customer_client2(workspace2, _session):
    return RemoteAPIClient(workspace=workspace2, token=_session["ws2"]["customer_token"])


@pytest.fixture
def anonymous_api_client2(workspace2):
    return RemoteAPIClient(workspace=workspace2, token=None)


@pytest.fixture
def customer2(_session):
    """Customer record in workspace2 (for test_16 isolation)."""
    c = _session["ws2"]["customer"]
    return SimpleNamespace(
        id=c["id"],
        customer_number=c.get("customer_number"),
        company_name=c.get("company_name"),
        tax_number=c.get("tax_number"),
    )


# --- Data fixtures (API-created) ---

@pytest.fixture
def message_templates(authenticated_client, workspace):
    templates_data = [
        {"name": "Order Created", "code": "order_created", "event": "order.created", "language": "en",
         "email_enabled": True, "email_subject": "Order Confirmation", "email_body": "Thank you.",
         "app_message_enabled": True, "app_message_title": "Order Created", "app_message_body": "Order created.",
         "is_active": True},
        {"name": "Payment Received", "code": "payment_received", "event": "payment.completed", "language": "en",
         "email_enabled": True, "email_subject": "Payment Received", "email_body": "Payment received.",
         "app_message_enabled": True, "app_message_title": "Payment Received", "app_message_body": "Payment received.",
         "is_active": True},
    ]
    out = []
    for data in templates_data:
        r = authenticated_client.post("/api/v1/inbox/templates/", data)
        if r.status_code == 201:
            out.append(SimpleNamespace(id=r.data["id"], **data))
    return out


@pytest.fixture
def warehouse(authenticated_client, workspace):
    suffix = uuid.uuid4().hex[:6]
    r = authenticated_client.post(
        "/api/v1/delivery/warehouses/",
        {"name": f"Default WH {suffix}", "code": f"WH-001-{suffix}"},
    )
    assert r.status_code == 201, (r.status_code, r.data)
    d = r.data
    return SimpleNamespace(id=d["id"], name=d.get("name"), code=d.get("code"), workspace_id=workspace.id)


@pytest.fixture
def store(authenticated_client, workspace, warehouse):
    suffix = uuid.uuid4().hex[:6]
    r = authenticated_client.post(
        "/api/v1/shop/stores/",
        {"name": f"Default Store {suffix}", "code": f"ST-001-{suffix}", "warehouse_ids": [warehouse.id]},
    )
    assert r.status_code == 201, (r.status_code, r.data)
    return SimpleNamespace(id=r.data["id"], name=r.data.get("name"), code=r.data.get("code"))


@pytest.fixture
def currency(authenticated_client):
    """Requires at least one active currency; seed finance/currencies if empty."""
    r = authenticated_client.get("/api/v1/finance/currencies/")
    assert r.status_code == 200, (r.status_code, r.data)
    if isinstance(r.data, list):
        data = r.data
    elif isinstance(r.data, dict) and "results" in r.data:
        # Do not use `or r.data`: empty results [] is falsy and would break indexing.
        data = r.data.get("results") or []
    else:
        data = []
    assert data, "No currency from API; seed finance/currencies (admin UI or migration)."
    c = data[0]
    for x in data:
        if isinstance(x, dict) and x.get("code") == "USD":
            c = x
            break
    return SimpleNamespace(id=c["id"], code=c.get("code", "USD"), name=c.get("name", "US Dollar"), symbol=c.get("symbol", "$"))


@pytest.fixture
def carrier(authenticated_client, workspace):
    suffix = uuid.uuid4().hex[:6]
    r = authenticated_client.post(
        "/api/v1/delivery/carriers/",
        {"name": f"Test Carrier {suffix}", "code": f"TC-001-{suffix}"},
    )
    assert r.status_code == 201, (r.status_code, r.data)
    d = r.data
    return SimpleNamespace(id=d["id"], name=d.get("name"), code=d.get("code"))


@pytest.fixture
def freight_service(authenticated_client, workspace, carrier):
    suffix = uuid.uuid4().hex[:6]
    r = authenticated_client.post(
        "/api/v1/delivery/freight-services/",
        {
            "carrier": carrier.id,
            "name": f"Standard Shipping {suffix}",
            "code": f"STD-{suffix}",
            "base_price": "10.00",
            "price_per_kg": "5.00",
            "is_active": True,
        },
    )
    if r.status_code == 201:
        d = r.data
        return SimpleNamespace(id=d["id"], carrier_id=carrier.id, name=d.get("name"), code=d.get("code"))
    return SimpleNamespace(id=carrier.id, carrier_id=carrier.id, name="Standard", code="STD")


@pytest.fixture
def payment_gateway(authenticated_client, workspace):
    suffix = uuid.uuid4().hex[:6]
    r = authenticated_client.post(
        "/api/v1/finance/payment-gateways/",
        {"name": f"Test Gateway {suffix}", "gateway_type": "custom", "is_active": True},
    )
    assert r.status_code == 201, (r.status_code, r.data)
    d = r.data
    return SimpleNamespace(id=d["id"], name=d.get("name"), gateway_type=d.get("gateway_type", "custom"))


@pytest.fixture
def test_address(authenticated_client):
    payload = {
        "full_name": "John Doe",
        "phone": "1234567890",
        "address_line1": "123 Main St",
        "city": "Test City",
        "country": "US",
        "postal_code": "12345",
    }
    response = authenticated_client.post("/api/v1/addresses/", payload)
    assert response.status_code == 201, (response.status_code, response.data)
    return response.data


@pytest.fixture
def other_user_client(workspace, _session):
    base = _get_base_url()
    customer_password = os.environ.get("BFG2_E2E_CUSTOMER_PASSWORD")
    if not customer_password:
        pytest.fail("BFG2_E2E_CUSTOMER_PASSWORD must be set in env for API integration tests")
    email = f"apitest-other-{uuid.uuid4().hex[:8]}@test.com"
    u = _register_and_login(base, email, customer_password, "Other", "User")
    return RemoteAPIClient(workspace=workspace, token=u["token"])
