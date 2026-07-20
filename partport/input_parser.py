"""Normalize LCSC part numbers pasted as text or URLs."""

from __future__ import annotations

import re

LCSC_CODE_RE = re.compile(r"(?i)(?<![A-Z0-9])C\d+(?![A-Z0-9])")
TOKEN_SPLIT_RE = re.compile(r"[,;\s]+")


def parse_codes(text: str) -> list[str]:
    """Return unique, normalized LCSC codes in first-seen order.

    Codes embedded in URLs or surrounding prose are accepted. Plain tokens that
    are not valid LCSC codes are ignored and can be reported by ``invalid_tokens``.
    """
    found = [match.group(0).upper() for match in LCSC_CODE_RE.finditer(text)]
    return list(dict.fromkeys(found))


def invalid_tokens(text: str) -> list[str]:
    """Return non-empty plain tokens that contain no valid LCSC code."""
    invalid: list[str] = []
    for token in TOKEN_SPLIT_RE.split(text.strip()):
        token = token.strip()
        if token and not LCSC_CODE_RE.search(token):
            invalid.append(token)
    return invalid
