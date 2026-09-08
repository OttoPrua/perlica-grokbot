"""Fail if public product files contain host paths or filled secrets."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PRODUCT_PATHS = (
    "README.md",
    "Makefile",
    ".gitignore",
    "bin",
    "docs",
    "examples",
    "grokbot",
    "skills",
)
PATH_PATTERNS = (
    re.compile("/" + "Users" + "/"),
    re.compile("/home/" + r"[A-Za-z0-9._-]+"),
)
FILLED_SECRET = re.compile(
    r"GROK_DISPATCH_WEBHOOK_KEY\s*=\s*(?!<)(?!synth-)\S+"
)


def _walk_product():
    for rel in PRODUCT_PATHS:
        path = REPO / rel
        if path.is_file():
            yield path
            continue
        if not path.is_dir():
            continue
        for child in path.rglob("*"):
            if child.is_file() and "__pycache__" not in child.parts:
                yield child


class PrivacyScanTests(unittest.TestCase):
    def test_public_product_files_have_no_private_paths_or_filled_keys(self) -> None:
        hits = []
        for path in _walk_product():
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            rel = path.relative_to(REPO).as_posix()
            for pattern in PATH_PATTERNS:
                if pattern.search(text):
                    hits.append("%s matches %s" % (rel, pattern.pattern))
            for match in FILLED_SECRET.finditer(text):
                hits.append("%s has filled webhook key assignment" % rel)
        self.assertEqual(hits, [])
