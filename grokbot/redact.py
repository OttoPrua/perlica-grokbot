"""Strip dispatcher secrets from anything that might be printed."""

from __future__ import annotations

from typing import Iterable, List, Optional, Sequence
from urllib.parse import urlparse


MIN_KEY_LENGTH = 8


def secret_fragments(key: Optional[str]) -> List[str]:
    fragments: List[str] = []
    if not key:
        return fragments
    fragments.append(key)
    fragments.append("Bearer " + key)
    fragments.append("bearer " + key)
    return fragments


def scrub(text: str, secrets: Sequence[str]) -> str:
    out = text
    # Longer secrets first so a prefix cannot leave a residue.
    for secret in sorted((s for s in secrets if s), key=len, reverse=True):
        out = out.replace(secret, "<redacted>")
    return out


def safe_destination(url: str) -> dict:
    parsed = urlparse(url)
    return {
        "scheme": parsed.scheme,
        "host": parsed.hostname,
        "port": parsed.port,
        "path": parsed.path or "/",
    }


def safe_location(raw: Optional[str]) -> Optional[dict]:
    if not raw or not isinstance(raw, str):
        return None
    try:
        parsed = urlparse(raw)
    except ValueError:
        return {"unparsed": True}
    if not parsed.scheme and not parsed.netloc and not parsed.path:
        return {"unparsed": True}
    return {
        "scheme": parsed.scheme,
        "host": parsed.hostname,
        "port": parsed.port,
        "path": parsed.path or "/",
    }


def merge_secrets(*groups: Iterable[str]) -> List[str]:
    seen = []
    for group in groups:
        for item in group:
            if item and item not in seen:
                seen.append(item)
    return seen
