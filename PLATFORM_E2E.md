# Platform Extension E2E Tests

The Platform extension can run in two modes. Each has its own test directory and setup:

| Mode | Directory | Server config |
|------|-----------|---------------|
| **Embedded** | `e2e/bfg_platform/embedded/` | Platform runs inside the workspace server (same process, same DB) |
| **Standalone** | `e2e/bfg_platform/standalone/` | Platform runs as a separate BFG instance with its own DB |

---

## Mode 1 — Embedded

### How it works

The workspace server loads `apps.platform` as a local app. One workspace (e.g. `slug=admin`) acts as the management workspace. No separate process is needed.

```
Client → :8000 (workspace + platform in same Django process)
```

### Prerequisites

**1. Workspace server with platform enabled**

In your workspace server `.env`:
```env
BFG_INSTANCE_TYPE=workspace
LOCAL_APPS=myapp,platform
PLATFORM_WORKSPACE_SLUG=admin      # slug of your management workspace
PLATFORM_EMBEDDED=True
```

**2. Run migrations**
```bash
python manage.py migrate
```

**3. Create a superuser**
```bash
python manage.py createsuperuser
# or via shell:
python manage.py shell -c "
from django.contrib.auth import get_user_model
User = get_user_model()
User.objects.create_superuser(
    username='admin', email='admin@example.com', password='yourpassword'
)
"
```

**4. Create the management workspace**
```bash
curl -s -X POST http://localhost:8000/api/v1/auth/token/ \
  -H 'Content-Type: application/json' \
  -d '{"email":"admin@example.com","password":"yourpassword"}' \
  | python3 -c "import sys,json; t=json.load(sys.stdin)['access']; print(t)" > /tmp/token.txt

curl -s -X POST http://localhost:8000/api/v1/workspaces/ \
  -H "Authorization: Bearer $(cat /tmp/token.txt)" \
  -H 'Content-Type: application/json' \
  -d '{"name":"Admin Platform","slug":"admin","domain":"","email":"admin@example.com"}'
```

**5. Start the server**
```bash
python manage.py runserver 8000
```

### Configure tests

In `e2e/bfg_platform/embedded/.env` (or root `.env`):
```env
BASE_URL=http://localhost:8000
BFG2_E2E_SUPERUSER_EMAIL=admin@example.com
BFG2_E2E_SUPERUSER_PASSWORD=yourpassword
BFG2_E2E_PLATFORM_WORKSPACE_SLUG=admin
```

### Run

```bash
BASE_URL=http://localhost:8000 \
  pytest e2e/bfg_platform/embedded/ -m e2e -v
```

Expected: **20 passed**

---

## Mode 2 — Standalone

### How it works

Two independent BFG servers communicate over HTTP:

```
Client → :8011 (platform server)
                    ↓ HTTP (token exchange, user provisioning)
              :8000 (workspace server)
```

- Platform server: `BFG_INSTANCE_TYPE=platform`, manages `PlatformMembership` + `WorkspacePlatformProfile`
- Workspace server: `BFG_INSTANCE_TYPE=workspace`, exposes `/api/v1/internal/auth/provision-user/`
- A shared `PLATFORM_API_KEY` authenticates internal calls

### Prerequisites

**Server A — Workspace server (port 8000)**

`.env`:
```env
BFG_INSTANCE_TYPE=workspace
LOCAL_APPS=myapp
PLATFORM_API_KEY=your-shared-api-key
DATABASE_URL=mysql://root:pass@127.0.0.1:3306/workspace_db
```

Start: `python manage.py runserver 8000`

**Server B — Platform server (port 8011)**

Copy the workspace server project to a separate directory (or use a fresh checkout), then set `.env`:
```env
BFG_INSTANCE_TYPE=platform
LOCAL_APPS=platform
PLATFORM_API_KEY=your-shared-api-key
WORKSPACE_API_URL=http://localhost:8000
DATABASE_URL=mysql://root:pass@127.0.0.1:3306/platform_db
```

```bash
# Create platform DB
mysql -u root -p -e "CREATE DATABASE IF NOT EXISTS platform_db CHARACTER SET utf8mb4;"

# Migrate
python manage.py migrate

# Create platform superuser
python manage.py shell -c "
from django.contrib.auth import get_user_model
User = get_user_model()
User.objects.create_superuser(
    username='platform_admin',
    email='admin@platform.example.com',
    password='yourpassword'
)
"

# Start
python manage.py runserver 8011
```

**Seed: link a workspace**

After both servers are up, create a workspace on the platform server and link it to an existing workspace on the workspace server:

```bash
# 1. Get workspace UUID from workspace server
WS_TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/token/ \
  -H 'Content-Type: application/json' \
  -d '{"email":"admin@example.com","password":"yourpassword"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access'])")

WS_UUID=$(curl -s http://localhost:8000/api/v1/platform/workspaces/me/ \
  -H "Authorization: Bearer $WS_TOKEN" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['workspaces'][0]['uuid'])")

echo "Workspace UUID: $WS_UUID"

# 2. Create workspace record on platform server
PLAT_TOKEN=$(curl -s -X POST http://localhost:8011/api/v1/auth/token/ \
  -H 'Content-Type: application/json' \
  -d '{"email":"admin@platform.example.com","password":"yourpassword"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access'])")

curl -s -X POST http://localhost:8011/api/v1/platform/workspaces/ \
  -H "Authorization: Bearer $PLAT_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"name":"My Workspace","slug":"my-workspace"}'

# 3. Link remote UUID (via Django shell on platform server)
python manage.py shell -c "
from django.apps import apps
Workspace = apps.get_model('common', 'Workspace')
ws = Workspace.objects.get(slug='my-workspace')
ws.remote_workspace_uuid = '$WS_UUID'
ws.save()
print('linked')
"

# 4. Create PlatformMembership
python manage.py shell -c "
from django.apps import apps
from django.contrib.auth import get_user_model
User = get_user_model()
PlatformMembership = apps.get_model('platform', 'PlatformMembership')
WorkspacePlatformProfile = apps.get_model('platform', 'WorkspacePlatformProfile')
Workspace = apps.get_model('common', 'Workspace')

user = User.objects.get(email='admin@platform.example.com')
ws = Workspace.objects.get(slug='my-workspace')
profile, _ = WorkspacePlatformProfile.objects.get_or_create(
    workspace=ws,
    defaults={'remote_workspace_uuid': '$WS_UUID'}
)
PlatformMembership.objects.get_or_create(
    user=user, profile=profile,
    defaults={'role': 'owner', 'is_active': True}
)
print('membership created')
"
```

### Configure tests

In `e2e/bfg_platform/standalone/.env` (or root `.env`):
```env
BASE_URL=http://localhost:8011
WORKSPACE_BASE_URL=http://localhost:8000
BFG2_E2E_PLATFORM_EMAIL=admin@platform.example.com
BFG2_E2E_PLATFORM_PASSWORD=yourpassword
BFG2_E2E_PLATFORM_API_KEY=your-shared-api-key
```

### Run

```bash
BASE_URL=http://localhost:8011 \
  pytest e2e/bfg_platform/standalone/ -m e2e -v
```

Expected: **20 passed, 1 skipped**

The 1 skip (`test_full_create_exchange_access_flow`) is expected — creating a workspace via the API doesn't automatically create a `PlatformMembership` for the creator, so token exchange is skipped. This is by design.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| `Login failed` | Wrong credentials in `.env` | Check `BFG2_E2E_SUPERUSER_EMAIL` / `PASSWORD` |
| `platform server not reachable` | Server not started | `python manage.py runserver 8011` |
| `500 on /platform/plans/` | `sort_order` field missing on `SubscriptionPlan` | Remove `sort_order` from `order_by()` in `PlanViewSet.get_queryset()` |
| `500 on /platform/workspaces/` | `id` missing from create response | Add `to_representation()` to `WorkspaceCreateSerializer` |
| `500 on token-exchange` (standalone) | `int(workspace_id)` fails on slug | Wrap in `try/except ValueError` in `_token_exchange_standalone()` |
| `Duplicate entry 'xxx' for username` | `provision_sso_user` username conflict | Pre-check uniqueness before `User.objects.create()` |
| Tests skip with "not reachable" | `BASE_URL` not pointing to right server | Set `BASE_URL=http://localhost:800X` before running |

---

## Test Coverage

### Embedded (`test_embedded.py`) — 20 tests

| Class | Tests | What's verified |
|-------|-------|----------------|
| `TestEmbeddedWorkspaceList` | 4 | StaffMember-based listing; `is_platform_admin`; management workspace flagged |
| `TestEmbeddedWorkspaceCreate` | 3 | Direct DB creation; `id` in response; slug uniqueness |
| `TestEmbeddedTokenExchange` | 3 | Returns JWT + `embedded=true`; 404 for unknown; 400 for missing param |
| `TestEmbeddedSuspendResume` | 2 | Suspend → `is_active=False`; resume → `is_active=True` |
| `TestEmbeddedSubscription` | 1 | New workspace has no subscription |
| `TestEmbeddedPlans` | 2 | Public endpoint; returns list |
| `TestEmbeddedSSO` | 2 | Unknown/empty domain → `sso_enabled=false` |
| `TestEmbeddedPermission` | 3 | Unauthenticated blocked from list / create / token-exchange |

### Standalone (`test_standalone.py`) — 20 passed + 1 skip

| Class | Tests | What's verified |
|-------|-------|----------------|
| `TestStandaloneWorkspaceList` | 3 | PlatformMembership-based listing; superuser is admin; cluster/region fields present |
| `TestStandaloneTokenExchange` | 4 | Cross-server HTTP call; workspace JWT works on workspace server; no membership → 403; missing param → 400 |
| `TestStandaloneWorkspaceCreate` | 2 | Creation via API; slug uniqueness |
| `TestStandaloneSuspendResume` | 1 | Full suspend → resume cycle |
| `TestStandaloneSubscription` | 1 | Subscription endpoint accessible |
| `TestStandalonePlans` | 2 | Public endpoint; structure validation |
| `TestStandaloneSSO` | 2 | Unknown/empty domain → false |
| `TestStandaloneInternalAuth` | 2 | No API key → 403; wrong key → 403 |
| `TestStandalonePermission` | 3 | Unauthenticated blocked from all endpoints |
| `TestStandaloneCrossServer` | 1 (skip) | Create → exchange → access flow (skipped: no auto-membership on create) |
