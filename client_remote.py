"""
HTTP client for API integration tests (remote Node or Django API). Base URL from env only.
Mimics DRF test client: .get, .post, .data, .status_code, force_authenticate.
"""
import json
import os
import uuid

import requests


def get_base_url(require=False):
    """Return API base URL from BASE_URL. If require=True, assert it is set for integration tests."""
    base = os.environ.get("BASE_URL") or ""
    if require:
        assert base.strip(), "BASE_URL must be set for API integration tests"
    return base.rstrip("/") if base else ""


class RemoteAPIClient:
    """Mimics DRF client: .request(), .data, .status_code, .generic(), .get, .post."""

    def __init__(self, workspace=None, token=None):
        self.base_url = get_base_url()
        self.workspace = workspace
        self._token = token
        self._customer = None
        # Persist Set-Cookie (e.g. sessionid) across requests for anonymous storefront cart
        self._http = requests.Session()
        # .NET storefront isolates carts by session header when unauthenticated
        self._storefront_cart_session = uuid.uuid4().hex if token is None else None
        # Keep grouped module routes intact so tests hit the same URLs as the Django server.
        self._should_normalize = False

    def _normalize_path(self, path: str) -> str:
        """
        Normalize API integration test paths to match the live server routing.

        The live server now mounts modules under grouped prefixes like:
          /api/v1/shop/, /api/v1/delivery/, /api/v1/finance/, /api/v1/marketing/

        Keep paths unchanged so the tests exercise the real grouped routes directly.
        """
        if not self._should_normalize:
            if not path.startswith("/"):
                path = "/" + path
            return path
        if not path.startswith("/"):
            path = "/" + path

        prefix_map = {
            "/api/v1/shop/": "/api/v1/",
            "/api/v1/delivery/": "/api/v1/",
            "/api/v1/finance/": "/api/v1/",
            "/api/v1/marketing/": "/api/v1/",
        }
        for old, new in prefix_map.items():
            if path.startswith(old):
                return new + path[len(old):]
        return path

    def force_authenticate(self, user=None, token=None):
        if token is not None:
            self._token = token
        elif user is not None and getattr(user, "token", None):
            self._token = user.token
        else:
            self._token = None

    def _headers(self):
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        if self.workspace:
            wid = getattr(self.workspace, "id", None)
            if wid is None and isinstance(self.workspace, dict):
                wid = self.workspace.get("id")
            slug = getattr(self.workspace, "slug", None) or (
                self.workspace.get("slug") if isinstance(self.workspace, dict) else None
            )
            if wid is not None:
                headers["X-Workspace-Id"] = str(wid)
            if slug:
                headers["X-Workspace-Slug"] = str(slug)
        if self._storefront_cart_session:
            headers["X-Bfg-Cart-Session"] = self._storefront_cart_session
        return headers

    def generic(self, method, path, data="", content_type="application/json", **extra):
        path = self._normalize_path(path)
        url = self.base_url + path
        headers = dict(self._headers())
        req_format = (extra or {}).get("format")
        for k, v in (extra or {}).items():
            if k.startswith("HTTP_"):
                key = k.replace("HTTP_", "").replace("_", "-").title()
                headers[key] = v

        if req_format == "multipart":
            files = {}
            form_data = {}
            if isinstance(data, dict):
                for key, value in data.items():
                    # Handle Django SimpleUploadedFile (and similar file-like objects)
                    if hasattr(value, "read") and callable(getattr(value, "read", None)):
                        try:
                            file_bytes = value.read()
                        except Exception:
                            file_bytes = b""
                        try:
                            # Reset pointer if the file object supports it
                            value.seek(0)
                        except Exception:
                            pass
                        filename = getattr(value, "name", key)
                        mime = getattr(value, "content_type", None) or "application/octet-stream"
                        files[key] = (filename, file_bytes, mime)
                    else:
                        form_data[key] = value
            else:
                form_data = data

            # Don't force JSON content-type for multipart; requests needs to set boundary.
            headers.pop("Content-Type", None)
            r = self._http.request(method, url, headers=headers, files=files, data=form_data, timeout=30)
        else:
            body = json.dumps(data) if isinstance(data, dict) else (data or None)
            r = self._http.request(method, url, headers=headers, data=body, timeout=30)
        try:
            out_data = r.json()
        except Exception:
            out_data = r.text or {}
        return _Response(r.status_code, out_data)

    def get(self, path, **kwargs):
        return self.generic("GET", path, **kwargs)

    def post(self, path, data=None, **kwargs):
        return self.generic("POST", path, data=data or {}, content_type="application/json", **kwargs)

    def put(self, path, data=None, **kwargs):
        return self.generic("PUT", path, data=data or {}, **kwargs)

    def patch(self, path, data=None, **kwargs):
        return self.generic("PATCH", path, data=data or {}, **kwargs)

    def delete(self, path, **kwargs):
        return self.generic("DELETE", path, **kwargs)


class _Response:
    def __init__(self, status_code, data):
        self.status_code = status_code
        self.data = data
