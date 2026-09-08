"""Single-attempt JSON POST. Never follows redirects, never retries."""

from __future__ import annotations

import http.client
import socket
import urllib.error
import urllib.request
from typing import Mapping
from urllib.parse import urlparse

from grokbot import USER_AGENT
from grokbot.errors import ConfigError, HttpStatusError, RedirectRejected, UnknownOutcome
from grokbot.redact import MIN_KEY_LENGTH, safe_destination, safe_location

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
MAX_BODY_BYTES = 256 * 1024
DEFAULT_TIMEOUT = 30.0
_TRUTHY = frozenset({"1", "true", "yes", "on"})


class _RejectRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Replace the default redirect handler so a 3xx never opens a second URL."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        del req, fp, msg, newurl
        _raise_redirect(code, headers)
        return None

    def http_error_301(self, req, fp, code, msg, headers):
        del req, fp, msg
        _raise_redirect(code, headers)

    http_error_302 = http_error_301
    http_error_303 = http_error_301
    http_error_307 = http_error_301
    http_error_308 = http_error_301


def _raise_redirect(code: int, headers: Mapping[str, str]) -> None:
    location = None
    try:
        location = headers.get("Location") or headers.get("URI")
    except Exception:
        location = None
    raise RedirectRejected(
        "redirect rejected; no follow-up request and no retry",
        http_status=int(code),
        location_safe=safe_location(location if isinstance(location, str) else None),
    )


def loopback_http_allowed(flag: bool, env: Mapping[str, str]) -> bool:
    if flag:
        return True
    raw = env.get("GROK_DISPATCH_ALLOW_LOOPBACK_HTTP", "")
    return raw.strip().lower() in _TRUTHY


def load_url(env: Mapping[str, str]) -> str:
    raw = env.get("GROK_DISPATCH_WEBHOOK_URL")
    if raw is None or not str(raw).strip():
        raise ConfigError("GROK_DISPATCH_WEBHOOK_URL is missing")
    return str(raw).strip()


def load_key(env: Mapping[str, str]) -> str:
    raw = env.get("GROK_DISPATCH_WEBHOOK_KEY")
    if raw is None or not str(raw).strip():
        raise ConfigError("GROK_DISPATCH_WEBHOOK_KEY is missing")
    key = str(raw).strip()
    if len(key) < MIN_KEY_LENGTH:
        raise ConfigError("GROK_DISPATCH_WEBHOOK_KEY is too short")
    return key


def validate_url(url: str, *, allow_loopback_http: bool) -> dict:
    try:
        parsed = urlparse(url)
    except ValueError:
        raise ConfigError("GROK_DISPATCH_WEBHOOK_URL is not a valid URL")
    if parsed.username is not None or parsed.password is not None:
        raise ConfigError("GROK_DISPATCH_WEBHOOK_URL must not contain userinfo")
    if parsed.scheme not in ("https", "http"):
        raise ConfigError("GROK_DISPATCH_WEBHOOK_URL scheme must be https")
    host = (parsed.hostname or "").lower()
    if not host:
        raise ConfigError("GROK_DISPATCH_WEBHOOK_URL host is missing")
    if parsed.scheme == "http":
        if not (allow_loopback_http and host in LOOPBACK_HOSTS):
            raise ConfigError(
                "HTTP URLs are rejected; real endpoints must be HTTPS. "
                "Loopback HTTP is only for synthetic tests with "
                "--allow-loopback-http or GROK_DISPATCH_ALLOW_LOOPBACK_HTTP"
            )
    return safe_destination(url)


def post_json(
    *,
    url: str,
    key: str,
    body: bytes,
    timeout: float,
) -> int:
    if len(body) > MAX_BODY_BYTES:
        raise ConfigError("payload exceeds the 256 KiB client limit")
    headers = {
        "Authorization": "Bearer " + key,
        "Content-Type": "application/json; charset=utf-8",
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
        "Connection": "close",
    }
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    # Empty ProxyHandler: do not forward Authorization through HTTP(S)_PROXY.
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        _RejectRedirectHandler(),
    )
    try:
        with opener.open(request, timeout=timeout) as response:
            status = int(getattr(response, "status", None) or response.getcode())
            _drain(response)
            if 200 <= status < 300:
                return status
            if 300 <= status < 400:
                raise RedirectRejected(
                    "redirect rejected; no follow-up request and no retry",
                    http_status=status,
                    location_safe=None,
                )
            raise HttpStatusError(
                "HTTP error response; remote effect is unknown; no retry",
                http_status=status,
            )
    except RedirectRejected:
        raise
    except HttpStatusError:
        raise
    except urllib.error.HTTPError as exc:
        status = int(exc.code)
        _drain(exc)
        if 300 <= status < 400:
            location = None
            try:
                location = exc.headers.get("Location") if exc.headers is not None else None
            except Exception:
                location = None
            raise RedirectRejected(
                "redirect rejected; no follow-up request and no retry",
                http_status=status,
                location_safe=safe_location(location if isinstance(location, str) else None),
            )
        raise HttpStatusError(
            "HTTP error response; remote effect is unknown; no retry",
            http_status=status,
        )
    except (socket.timeout, TimeoutError):
        raise UnknownOutcome(
            "POST timed out; remote effect is unknown; no retry"
        )
    except (
        urllib.error.URLError,
        ConnectionError,
        BrokenPipeError,
        http.client.HTTPException,
        OSError,
    ):
        raise UnknownOutcome(
            "POST failed or disconnected; remote effect is unknown; no retry"
        )


def _drain(fp: object) -> None:
    read = getattr(fp, "read", None)
    if not callable(read):
        return
    try:
        while True:
            chunk = read(65536)
            if not chunk:
                break
    except Exception:
        return
