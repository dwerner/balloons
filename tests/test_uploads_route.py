"""Tests for the auth-gated image uploads route (GET /uploads/{filename}).

Covers the two security-critical surfaces:
  1. resolve_upload_path -- path traversal / separator rejection.
  2. HttpAuthServer._handle_upload -- auth enforcement + serving.
"""

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from service.http_server import HttpAuthServer, ServerConfig, resolve_upload_path
from service.jwt_auth import JWTAuth, JWTConfig


# ---------------------------------------------------------------------------
# 1. Path resolver (the security boundary)
# ---------------------------------------------------------------------------


class TestResolveUploadPath:
    def test_serves_real_file(self, tmp_path):
        f = tmp_path / "shot.png"
        f.write_bytes(b"\x89PNG data")
        resolved = resolve_upload_path(tmp_path, "shot.png")
        assert resolved is not None
        assert resolved.read_bytes() == b"\x89PNG data"

    def test_rejects_path_separators(self, tmp_path):
        assert resolve_upload_path(tmp_path, "a/b.png") is None
        assert resolve_upload_path(tmp_path, "a\\b.png") is None

    def test_rejects_dot_segments(self, tmp_path):
        assert resolve_upload_path(tmp_path, "..") is None
        assert resolve_upload_path(tmp_path, ".") is None
        assert resolve_upload_path(tmp_path, "../secret") is None

    def test_rejects_empty(self, tmp_path):
        assert resolve_upload_path(tmp_path, "") is None

    def test_rejects_missing_file(self, tmp_path):
        assert resolve_upload_path(tmp_path, "nope.png") is None

    def test_rejects_directory(self, tmp_path):
        (tmp_path / "adir").mkdir()
        assert resolve_upload_path(tmp_path, "adir") is None

    def test_traversal_escape_is_blocked(self, tmp_path):
        # A file that exists OUTSIDE the dir must not be reachable even though
        # the naive (base / filename) join would resolve to it.
        outside = tmp_path.parent / "outside.png"
        outside.write_bytes(b"secret")
        try:
            assert resolve_upload_path(tmp_path, "../outside.png") is None
        finally:
            outside.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# 2. The route handler
# ---------------------------------------------------------------------------


def _png_bytes() -> bytes:
    return b"\x89PNG\r\n\x1a\n" + b"fake-image-bytes"


def _make_server(tmp_path, *, enabled: bool) -> HttpAuthServer:
    jwt_auth = JWTAuth(JWTConfig(enabled=enabled, secret="test-secret-0123456789abcdef0123456789abcdef", expiration_seconds=3600))
    config = ServerConfig(
        host="localhost", port=0, tls_enabled=False, tls_cert_path=None, tls_key_path=None
    )
    return HttpAuthServer(
        config=config, auth_routes=None, jwt_auth=jwt_auth, upload_dir=tmp_path
    )


def _app_for(server: HttpAuthServer) -> web.Application:
    app = web.Application()
    app.router.add_get("/uploads/{filename}", server._handle_upload)
    return app


@pytest.fixture
def upload_file(tmp_path):
    f = tmp_path / "shot.png"
    f.write_bytes(_png_bytes())
    return tmp_path, "shot.png"


async def test_enabled_requires_token(upload_file):
    tmp_path, name = upload_file
    server = _make_server(tmp_path, enabled=True)
    async with TestClient(TestServer(_app_for(server))) as client:
        resp = await client.get(f"/uploads/{name}")
        assert resp.status == 401


async def test_enabled_serves_with_valid_token(upload_file):
    tmp_path, name = upload_file
    server = _make_server(tmp_path, enabled=True)
    token = server._jwt_auth.generate_token("user-1")
    async with TestClient(TestServer(_app_for(server))) as client:
        resp = await client.get(f"/uploads/{name}", headers={"Authorization": f"Bearer {token}"})
        assert resp.status == 200
        assert await resp.read() == _png_bytes()
        assert "immutable" in resp.headers.get("Cache-Control", "")


async def test_enabled_rejects_bad_token(upload_file):
    tmp_path, name = upload_file
    server = _make_server(tmp_path, enabled=True)
    async with TestClient(TestServer(_app_for(server))) as client:
        resp = await client.get(f"/uploads/{name}", headers={"Authorization": "Bearer garbage"})
        assert resp.status == 401


async def test_enabled_rejects_traversal_even_with_token(upload_file):
    tmp_path, _ = upload_file
    server = _make_server(tmp_path, enabled=True)
    token = server._jwt_auth.generate_token("user-1")
    async with TestClient(TestServer(_app_for(server))) as client:
        # aiohttp normalizes the path, so hit the resolver via a name that
        # survives routing but is rejected by the resolver.
        resp = await client.get("/uploads/..%2Fsecret.png", headers={"Authorization": f"Bearer {token}"})
        assert resp.status in (401, 404)  # either rejected at routing or resolver


async def test_disabled_serves_without_token(upload_file):
    tmp_path, name = upload_file
    server = _make_server(tmp_path, enabled=False)
    async with TestClient(TestServer(_app_for(server))) as client:
        resp = await client.get(f"/uploads/{name}")
        assert resp.status == 200
        assert await resp.read() == _png_bytes()


async def test_missing_file_404(upload_file):
    tmp_path, _ = upload_file
    server = _make_server(tmp_path, enabled=False)
    async with TestClient(TestServer(_app_for(server))) as client:
        resp = await client.get("/uploads/missing.png")
        assert resp.status == 404