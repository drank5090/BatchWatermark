"""Deploy static web assets to Chaitin SafeLine WAF (雷池 WAF) via Open API.

Uploads files non-destructively (one by one via Base64 JSON payload) instead of
uploading a ZIP archive to root, because SafeLine's `zip: true` mode clears the
destination directory before extracting — which would erase server-side search
engine verification files (e.g. Google/Bing/Baidu HTML/XML verification files).

Required environment variables (keep in GitHub Actions Secrets):
  SAFELINE_WAF_URL      Base URL of SafeLine WAF console (never printed)
  SAFELINE_API_KEY      SafeLine Open API token (X-SLCE-API-TOKEN, never printed)

Optional environment variables:
  SAFELINE_SITE_DOMAIN  Target static site domain (or pass --domain)
  SAFELINE_SITE_ID      Explicit numeric site ID (overrides domain lookup)
  SAFELINE_INSECURE_TLS Set to '1'/'true' only for self-signed certs (default: false)
"""

from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

IGNORED_NAMES = {".DS_Store", "Thumbs.db", "desktop.ini", ".gitkeep"}


def _redact(text: str, secrets: list[str]) -> str:
    """Replace any secret substring (and secret URL host) with [REDACTED]."""
    out = str(text)
    for secret in secrets:
        if not secret:
            continue
        out = out.replace(secret, "[REDACTED]")
        parsed = urllib.parse.urlparse(secret)
        if parsed.netloc:
            out = out.replace(parsed.netloc, "[REDACTED_HOST]")
    return out


class SafeLineClient:
    """Minimal stdlib-only client for SafeLine WAF static site Open API."""

    def __init__(
        self,
        waf_url: str,
        api_key: str,
        *,
        timeout: int = 30,
        retries: int = 3,
        insecure_tls: bool = False,
    ) -> None:
        self.waf_url = waf_url.strip().rstrip("/")
        self.api_key = api_key.strip()
        self.timeout = timeout
        self.retries = max(1, retries)
        self._secrets = [self.waf_url, self.api_key]

        if not self.waf_url.startswith(("https://", "http://")):
            raise ValueError("SAFELINE_WAF_URL must start with https:// or http://")
        if not self.api_key:
            raise ValueError("SAFELINE_API_KEY must not be empty")

        if insecure_tls:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            self._ssl_ctx = ctx
        else:
            self._ssl_ctx = ssl.create_default_context()

    def request_json(
        self,
        method: str,
        api_path: str,
        payload: dict | None = None,
    ) -> dict:
        url = f"{self.waf_url}{api_path}"
        headers = {
            "X-SLCE-API-TOKEN": self.api_key,
            "Accept": "application/json",
        }
        data = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")

        last_err: Exception | None = None
        for attempt in range(1, self.retries + 1):
            req = urllib.request.Request(url, data=data, headers=headers, method=method)
            try:
                with urllib.request.urlopen(req, context=self._ssl_ctx, timeout=self.timeout) as resp:
                    raw = resp.read().decode("utf-8", "replace")
                    body = json.loads(raw) if raw.strip() else {}
                    if body.get("err"):
                        raise RuntimeError(
                            f"SafeLine API returned error on {method} {api_path}: "
                            f"err={body.get('err')} msg={body.get('msg', '')}"
                        )
                    return body
            except urllib.error.HTTPError as exc:
                err_body = exc.read().decode("utf-8", "replace")[:400]
                msg = _redact(
                    f"HTTP {exc.code} on {method} {api_path}: {err_body}",
                    self._secrets,
                )
                last_err = RuntimeError(msg)
                # Retry only on 429 or 5xx transient errors
                if exc.code not in (429, 500, 502, 503, 504) or attempt == self.retries:
                    raise last_err from None
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                msg = _redact(
                    f"Network error on {method} {api_path}: {exc}",
                    self._secrets,
                )
                last_err = RuntimeError(msg)
                if attempt == self.retries:
                    raise last_err from None

            time.sleep(min(2 ** (attempt - 1), 5))

        raise last_err or RuntimeError(f"Unknown failure on {method} {api_path}")

    def list_sites(self) -> list[dict]:
        resp = self.request_json("GET", "/api/open/site")
        data = resp.get("data")
        if isinstance(data, dict) and isinstance(data.get("data"), list):
            return data["data"]
        if isinstance(data, list):
            return data
        return []

    def resolve_static_site(
        self,
        *,
        domain: str = "",
        site_id: int | None = None,
    ) -> dict:
        sites = self.list_sites()
        matched: dict | None = None

        if site_id is not None:
            matched = next((s for s in sites if s.get("id") == site_id), None)
            if not matched:
                raise RuntimeError(f"No SafeLine site found with id={site_id}")
        else:
            target = domain.strip().lower()
            if not target:
                raise ValueError("Either SAFELINE_SITE_ID or SAFELINE_SITE_DOMAIN must be set")
            for site in sites:
                names = [str(n).strip().lower() for n in (site.get("server_names") or [])]
                if target in names:
                    matched = site
                    break
            if not matched:
                raise RuntimeError(f"No SafeLine site found matching domain '{domain}'")

        if matched.get("type") != 1:
            raise RuntimeError(
                f"SafeLine site id={matched.get('id')} is not a static hosting site "
                f"(expected type=1, got type={matched.get('type')})"
            )
        return matched

    def ensure_dir(self, site_id: int, remote_dir: str) -> None:
        self.request_json(
            "POST",
            f"/api/open/site/{site_id}/static",
            {"path": remote_dir, "dir": True},
        )

    def upload_file(self, site_id: int, remote_path: str, content: bytes) -> None:
        encoded = base64.b64encode(content).decode("ascii")
        self.request_json(
            "POST",
            f"/api/open/site/{site_id}/static",
            {
                "path": remote_path,
                "dir": False,
                "zip": False,
                "page": encoded,
            },
        )

    def list_static_dir(self, site_id: int, remote_dir: str = "/") -> list[dict]:
        query = urllib.parse.urlencode({"path": remote_dir})
        resp = self.request_json("GET", f"/api/open/site/{site_id}/static?{query}")
        data = resp.get("data")
        return data if isinstance(data, list) else []


def collect_web_assets(source_dir: Path) -> tuple[list[str], list[tuple[str, Path]]]:
    """Return sorted remote directory paths and (remote_path, local_path) file tuples."""
    root = source_dir.resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"Source directory not found: {root}")

    dirs: set[str] = set()
    files: list[tuple[str, Path]] = []

    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)
        # Skip hidden files/folders and OS metadata files
        if any(part.startswith(".") or part in IGNORED_NAMES for part in rel.parts):
            continue
        posix_path = "/" + rel.as_posix()
        if path.is_dir():
            dirs.add(posix_path)
        elif path.is_file():
            for parent in rel.parents:
                if parent != Path("."):
                    dirs.add("/" + parent.as_posix())
            files.append((posix_path, path))

    if not any(rp == "/index.html" for rp, _ in files):
        raise ValueError(f"Expected index.html inside {root}; refusing to deploy")

    sorted_dirs = sorted(dirs, key=lambda d: (d.count("/"), d))
    files.sort(key=lambda item: item[0])
    return sorted_dirs, files


def deploy_static_site(
    client: SafeLineClient,
    source_dir: Path,
    *,
    domain: str = "",
    site_id: int | None = None,
    dry_run: bool = False,
) -> dict:
    """Sync all files in source_dir into the matching SafeLine WAF static site."""
    dirs, files = collect_web_assets(source_dir)
    site = client.resolve_static_site(domain=domain, site_id=site_id)
    resolved_id = int(site["id"])
    server_names = ", ".join(site.get("server_names") or [])

    print(
        f"Resolved SafeLine static site: id={resolved_id} "
        f"domains=[{server_names}] comment={site.get('comment', '')!r}"
    )
    print(f"Prepared {len(dirs)} directories and {len(files)} files from {source_dir}")

    if dry_run:
        for d in dirs:
            print(f"  [DRY-RUN] mkdir  {d}")
        for rp, lp in files:
            print(f"  [DRY-RUN] upload {rp} ({lp.stat().st_size} B)")
        return {
            "site_id": resolved_id,
            "dirs": len(dirs),
            "files": len(files),
            "total_bytes": sum(lp.stat().st_size for _, lp in files),
            "dry_run": True,
        }

    for remote_dir in dirs:
        client.ensure_dir(resolved_id, remote_dir)
        print(f"  [DIR ] {remote_dir}")

    total_bytes = 0
    root_expected_sizes: dict[str, int] = {}
    for remote_path, local_path in files:
        raw = local_path.read_bytes()
        client.upload_file(resolved_id, remote_path, raw)
        size = len(raw)
        total_bytes += size
        if remote_path.count("/") == 1:
            root_expected_sizes[remote_path.lstrip("/")] = size
        print(f"  [FILE] {remote_path} ({size:,} B)")

    # Verify root-level files landed with matching byte sizes
    remote_root = client.list_static_dir(resolved_id, "/")
    remote_sizes = {
        entry["name"]: int(entry.get("size", -1))
        for entry in remote_root
        if not entry.get("dir")
    }
    mismatches = [
        f"{name} (expected {exp} B, got {remote_sizes.get(name)})"
        for name, exp in sorted(root_expected_sizes.items())
        if remote_sizes.get(name) != exp
    ]
    if mismatches:
        raise RuntimeError("Post-upload size verification failed: " + "; ".join(mismatches))

    print(
        f"Successfully synced {len(files)} files ({total_bytes:,} B) to SafeLine static site "
        f"id={resolved_id}; verified {len(root_expected_sizes)} root files."
    )
    return {
        "site_id": resolved_id,
        "dirs": len(dirs),
        "files": len(files),
        "total_bytes": total_bytes,
        "verified_root_files": len(root_expected_sizes),
        "dry_run": False,
    }


def _parse_bool_env(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Deploy web/ static assets to SafeLine WAF.")
    parser.add_argument("--source", default="web", help="Local static directory (default: web)")
    parser.add_argument(
        "--domain",
        default=os.environ.get("SAFELINE_SITE_DOMAIN", ""),
        help="Target SafeLine static site domain",
    )
    parser.add_argument(
        "--site-id",
        type=int,
        default=int(os.environ["SAFELINE_SITE_ID"]) if os.environ.get("SAFELINE_SITE_ID") else None,
        help="Optional explicit SafeLine site ID (overrides --domain lookup)",
    )
    parser.add_argument("--timeout", type=int, default=30, help="HTTP request timeout in seconds")
    parser.add_argument("--retries", type=int, default=3, help="Retry attempts for transient errors")
    parser.add_argument("--dry-run", action="store_true", help="Resolve site and list files without uploading")
    args = parser.parse_args(argv)

    waf_url = os.environ.get("SAFELINE_WAF_URL", "").strip()
    api_key = os.environ.get("SAFELINE_API_KEY", "").strip()
    if not waf_url or not api_key:
        print(
            "ERROR: SAFELINE_WAF_URL and SAFELINE_API_KEY environment variables must be configured.",
            file=sys.stderr,
        )
        return 1

    try:
        client = SafeLineClient(
            waf_url,
            api_key,
            timeout=args.timeout,
            retries=args.retries,
            insecure_tls=_parse_bool_env("SAFELINE_INSECURE_TLS", False),
        )
        deploy_static_site(
            client,
            Path(args.source),
            domain=args.domain,
            site_id=args.site_id,
            dry_run=args.dry_run,
        )
        return 0
    except Exception as exc:
        safe_msg = _redact(str(exc), [waf_url, api_key])
        print(f"ERROR: SafeLine static deployment failed: {safe_msg}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
