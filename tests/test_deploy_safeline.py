"""Unit tests for SafeLine WAF static resource deployment script."""

from __future__ import annotations

import base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
import urllib.parse

import pytest

from scripts.deploy_safeline import (
    SafeLineClient,
    _redact,
    collect_web_assets,
    deploy_static_site,
)


class _MockSafeLineState:
    def __init__(self) -> None:
        self.expected_token = "secret-token-xyz-999"
        self.sites = [
            {"id": 1, "comment": "proxy", "server_names": ["api.example.com"], "type": 0},
            {"id": 5, "comment": "水印网站", "server_names": ["watermark.zak-cloud.top"], "type": 1},
        ]
        # Pre-existing server-side verification files that MUST NOT be deleted
        self.files: dict[str, bytes] = {
            "/BingSiteAuth.xml": b"<bing/>",
            "/google6969.html": b"google-site-verification",
        }
        self.dirs: set[str] = {"/"}
        self.requests: list[tuple[str, str]] = []


def _start_mock_safeline(state: _MockSafeLineState):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _send(self, code: int, payload: dict):
            raw = json.dumps(payload).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def _check_auth(self) -> bool:
            if self.headers.get("X-SLCE-API-TOKEN") != state.expected_token:
                self._send(401, {"data": {}, "err": "unauthorized", "msg": "bad token"})
                return False
            return True

        def do_GET(self):
            state.requests.append(("GET", self.path))
            if not self._check_auth():
                return
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path == "/api/open/site":
                self._send(200, {"data": {"data": state.sites}, "err": None, "msg": ""})
                return
            if parsed.path == "/api/open/site/5/static":
                q = urllib.parse.parse_qs(parsed.query)
                target = q.get("path", [""])[0]
                if target == "/":
                    items = []
                    for d in sorted(state.dirs):
                        if d != "/" and d.count("/") == 1:
                            items.append({"dir": True, "name": d.lstrip("/"), "size": 4096})
                    for fp, data in sorted(state.files.items()):
                        if fp.count("/") == 1:
                            items.append({"dir": False, "name": fp.lstrip("/"), "size": len(data)})
                    self._send(200, {"data": items, "err": None, "msg": ""})
                    return
            self._send(404, {"data": {}, "err": "not-found", "msg": "not found"})

        def do_POST(self):
            state.requests.append(("POST", self.path))
            if not self._check_auth():
                return
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            if self.path == "/api/open/site/5/static":
                assert not body.get("zip"), "Must not use destructive zip upload on root"
                path = body["path"]
                if body.get("dir"):
                    state.dirs.add(path)
                else:
                    state.files[path] = base64.b64decode(body["page"])
                self._send(200, {"data": None, "err": None, "msg": ""})
                return
            self._send(404, {"data": {}, "err": "not-found", "msg": "not found"})

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{port}"


def test_collect_web_assets_skips_hidden_and_requires_index(tmp_path: Path):
    (tmp_path / "index.html").write_text("<h1>Hi</h1>", encoding="utf-8")
    (tmp_path / ".DS_Store").write_bytes(b"junk")
    (tmp_path / ".hidden").mkdir()
    (tmp_path / ".hidden" / "secret.txt").write_text("no", encoding="utf-8")
    (tmp_path / "js").mkdir()
    (tmp_path / "js" / "app.js").write_text("console.log(1);", encoding="utf-8")

    dirs, files = collect_web_assets(tmp_path)
    assert dirs == ["/js"]
    assert [p for p, _ in files] == ["/index.html", "/js/app.js"]

    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    with pytest.raises(ValueError, match="index.html"):
        collect_web_assets(empty_dir)


def test_deploy_preserves_verification_files_and_verifies_sizes(tmp_path: Path):
    (tmp_path / "index.html").write_text("<html>ok</html>", encoding="utf-8")
    (tmp_path / "llms.txt").write_text("# BatchWatermark", encoding="utf-8")
    (tmp_path / "js").mkdir()
    (tmp_path / "js" / "app.js").write_bytes(b"export const x = 1;")

    state = _MockSafeLineState()
    server, url = _start_mock_safeline(state)
    try:
        client = SafeLineClient(url, state.expected_token, retries=1)
        result = deploy_static_site(client, tmp_path, domain="watermark.zak-cloud.top")

        assert result["site_id"] == 5
        assert result["dirs"] == 1
        assert result["files"] == 3
        assert result["verified_root_files"] == 2
        assert state.files["/index.html"] == b"<html>ok</html>"
        assert state.files["/llms.txt"] == b"# BatchWatermark"
        assert state.files["/js/app.js"] == b"export const x = 1;"
        # Existing verification files remain untouched
        assert state.files["/BingSiteAuth.xml"] == b"<bing/>"
        assert state.files["/google6969.html"] == b"google-site-verification"
    finally:
        server.shutdown()


def test_rejects_non_static_site_and_redacts_secrets(tmp_path: Path):
    (tmp_path / "index.html").write_text("ok", encoding="utf-8")

    state = _MockSafeLineState()
    server, url = _start_mock_safeline(state)
    try:
        client = SafeLineClient(url, state.expected_token, retries=1)
        with pytest.raises(RuntimeError, match="not a static hosting site"):
            deploy_static_site(client, tmp_path, domain="api.example.com")

        bad_client = SafeLineClient(url, "wrong-secret-token-12345", retries=1)
        with pytest.raises(RuntimeError) as exc_info:
            bad_client.list_sites()
        assert "wrong-secret-token-12345" not in str(exc_info.value)
    finally:
        server.shutdown()

    redacted = _redact(
        "Failed connecting to https://waf.secret.example/api with key abcdef123456",
        ["https://waf.secret.example", "abcdef123456"],
    )
    assert "waf.secret.example" not in redacted
    assert "abcdef123456" not in redacted
    assert "[REDACTED]" in redacted
