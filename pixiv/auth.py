"""Pixiv OAuth 2.0 PKCE authentication module."""

import os
import re
import sys
import json
import base64
import hashlib
import secrets
import webbrowser
import urllib.parse
from datetime import datetime
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler

import httpx


PIXIV_CLIENT_ID = "MOBrBDS8blbauoSck0ZfDbtuzpyT"
PIXIV_CLIENT_SECRET = "lsACyCD94FhDUtGTXi3QzcFE2uU1hqtDaKeqrdwj"
PIXIV_HASH_SECRET = "28c1fdd170a5204386cb1313c7077b34f83e4aaf4aa829ce78c231e05b0bae2c"
PIXIV_REDIRECT_URI = "https://app-api.pixiv.net/web/v1/users/auth/pixiv/callback"

LOGIN_URL = "https://app-api.pixiv.net/web/v1/login"
TOKEN_URL = "https://oauth.secure.pixiv.net/auth/token"

ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
FALLBACK_ENV = Path(__file__).resolve().parent.parent / ".env"


def _load_env():
    """Load .env file and return a dict of values. Checks pixiv-mcp/.env first, then qq-bot/.env."""
    result = {}
    for candidate in (ENV_PATH, FALLBACK_ENV):
        if candidate and candidate.exists():
            for line in candidate.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    k, v = line.split("=", 1)
                    k = k.strip()
                    if k not in result:
                        result[k] = v.strip().strip("\"'")
    return result


def _save_env(data: dict):
    """Save env values, preserving existing unmodified keys."""
    existing = _load_env()
    existing.update(data)
    lines = [f"{k}={v}\n" for k, v in sorted(existing.items())]
    ENV_PATH.write_text("".join(lines), encoding="utf-8")


def get_refresh_token() -> str | None:
    """Read refresh token from .env."""
    return _load_env().get("PIXIV_REFRESH_TOKEN")


def save_refresh_token(token: str):
    """Save refresh token to .env."""
    _save_env({"PIXIV_REFRESH_TOKEN": token})


def get_phpsessid() -> str | None:
    """Read PHPSESSID from .env."""
    return _load_env().get("PIXIV_PHPSESSID")


def get_access_token() -> str | None:
    """Read current access token from .env (optional cache)."""
    return _load_env().get("PIXIV_ACCESS_TOKEN")


def save_access_token(token: str):
    """Save access token to .env."""
    _save_env({"PIXIV_ACCESS_TOKEN": token})


def _generate_pkce_pair() -> tuple[str, str]:
    """Generate (code_verifier, code_challenge) for PKCE."""
    code_verifier = secrets.token_urlsafe(64)[:128]
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = (
        base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    )
    return code_verifier, code_challenge


def _get_authorize_url(code_challenge: str, state: str) -> str:
    """Build the Pixiv OAuth authorization URL."""
    params = {
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "client": "pixiv-android",
    }
    return f"{LOGIN_URL}?{urllib.parse.urlencode(params)}"


def _exchange_code_for_token(code: str, code_verifier: str) -> dict:
    """Exchange authorization code for access + refresh tokens."""
    local_time = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S+00:00")
    client_hash = hashlib.md5(
        (local_time + PIXIV_HASH_SECRET).encode("utf-8")
    ).hexdigest()

    data = {
        "client_id": PIXIV_CLIENT_ID,
        "client_secret": PIXIV_CLIENT_SECRET,
        "code": code,
        "code_verifier": code_verifier,
        "grant_type": "authorization_code",
        "redirect_uri": PIXIV_REDIRECT_URI,
        "include_policy": "true",
        "get_secure_url": 1,
    }
    headers = {
        "user-agent": "PixivIOSApp/8.5.0 (iOS 16.4; iPhone14,6)",
        "x-client-time": local_time,
        "x-client-hash": client_hash,
    }
    with httpx.Client() as client:
        r = client.post(TOKEN_URL, data=data, headers=headers)
        if r.status_code != 200:
            raise RuntimeError(
                f"Token exchange failed (HTTP {r.status_code}): {r.text}"
            )
        return r.json()


def _refresh_access_token(refresh_token: str) -> dict:
    """Refresh access token using refresh token."""
    from pixivpy3 import AppPixivAPI

    api = AppPixivAPI()
    result = api.auth(refresh_token=refresh_token)
    save_access_token(api.access_token)
    return result


def run_pkce_flow() -> str:
    """Run the full PKCE OAuth flow interactively.

    Returns the refresh token.
    """
    code_verifier, code_challenge = _generate_pkce_pair()

    auth_url = _get_authorize_url(code_challenge, "")
    print(f"Opening browser to:\n{auth_url}\n")
    webbrowser.open(auth_url)

    print("Log in to Pixiv in the browser and authorize the app.")
    print()
    print("登录后，浏览器可能会跳转到类似:")
    print("  pixiv://account/login?code=xxxxxxxxxx")
    print("把这个完整的 URL（包括 pixiv:// 开头）粘贴到下面。")
    print()
    print("如果浏览器没有跳转，打开开发者工具(F12) → Network 标签")
    print("筛选 callback? 或 pixiv://，找到 code= 后面的值粘贴即可。")
    print()

    redirect_result = input("Paste the redirect URL / code here: ").strip()

    code = None

    if redirect_result.startswith("pixiv://") or redirect_result.startswith("http"):
        parsed = urllib.parse.urlparse(redirect_result)
        for source in (parsed.query, parsed.fragment or ""):
            params = urllib.parse.parse_qs(source)
            if "code" in params:
                code = params["code"][0]
                break

    if not code:
        # Maybe it's a raw code
        import re
        match = re.search(r"code=([\w-]+)", redirect_result)
        if match:
            code = match.group(1)

    if not code:
        code = redirect_result.strip()

    if not code or len(code) < 10:
        print(f"\n无法从输入中提取 authorization code: {redirect_result}")
        raise RuntimeError("Failed to extract authorization code")

    print(f"\nExchanging authorization code for tokens...")
    token_data = _exchange_code_for_token(code, code_verifier)

    refresh_token = token_data.get("refresh_token")
    access_token = token_data.get("access_token")

    if not refresh_token:
        raise RuntimeError(f"No refresh_token in response: {token_data}")

    save_refresh_token(refresh_token)
    if access_token:
        save_access_token(access_token)

    print(f"Success! Refresh token saved to: {ENV_PATH}")
    return refresh_token


if __name__ == "__main__":
    run_pkce_flow()
