"""Canonical dispatcher targets and public aliases.

The existing cloud dispatcher defaults a missing or unknown target to infra.
This client defaults a missing target to infra and **rejects unknown names**
so it cannot claim a route it did not send.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from grokbot.errors import InputError

CANONICAL_TARGETS = ("infra", "kb", "timely", "daily", "weekly", "github")

# daily and weekly remain distinct values even though the cloud side may
# map both onto one periodic bot.
ALIASES = {
    "infra": "infra",
    "基建": "infra",
    "cloud": "infra",
    "本地基建": "infra",
    "kb": "kb",
    "knowledge": "kb",
    "知识库": "kb",
    "timely": "timely",
    "时效": "timely",
    "news": "timely",
    "时效信息": "timely",
    "daily": "daily",
    "日报": "daily",
    "weekly": "weekly",
    "周报": "weekly",
    "github": "github",
    "gh": "github",
    "contributor": "github",
}


def known_target_rows() -> List[Dict[str, object]]:
    rows = []
    for canonical in CANONICAL_TARGETS:
        aliases = sorted(
            name for name, mapped in ALIASES.items() if mapped == canonical and name != canonical
        )
        rows.append({"target": canonical, "aliases": aliases})
    return rows


def resolve_target(raw: Optional[str]) -> Tuple[str, Optional[str], bool, bool]:
    """Return (canonical, original_or_none, defaulted, normalized)."""
    if raw is None:
        return "infra", None, True, False
    text = raw.strip()
    if not text:
        raise InputError("target is empty; omit the flag to default to infra")
    canonical = ALIASES.get(text)
    if canonical is None:
        known = ", ".join(CANONICAL_TARGETS)
        raise InputError(
            "unknown target rejected (client fail-closed; not sent, not mapped to infra). "
            "known targets: " + known
        )
    return canonical, text, False, text != canonical
