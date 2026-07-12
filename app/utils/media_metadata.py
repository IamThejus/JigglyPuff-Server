"""Parse light metadata (year / quality / HDR) from media folder names.

Library folder names follow release-style conventions, e.g.::

    The.Dark.Knight.Rises.2012.2160p.HDR.BluRay.x265
    Inception (2010) 1080p BluRay x265

Doing this parsing server-side keeps the client dumb and gives one testable
source of truth (spec §2). All three fields are nullable/additive.
"""

from __future__ import annotations

import re

# First 4-digit 19xx/20xx token, optionally wrapped in parentheses. The
# surrounding character class keeps us from matching inside longer digit runs
# (e.g. a resolution like ``21600``).
_YEAR_RE = re.compile(r"(?:^|[^\d])(?:\()?((?:19|20)\d{2})(?:\))?(?:[^\d]|$)")

# Quality tokens in priority order; the first match wins. ``4K`` normalises to
# ``2160p`` per the spec.
_QUALITY_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(?<![a-z0-9])(?:2160p|4k)(?![a-z0-9])", re.IGNORECASE), "2160p"),
    (re.compile(r"(?<![a-z0-9])1080p(?![a-z0-9])", re.IGNORECASE), "1080p"),
    (re.compile(r"(?<![a-z0-9])720p(?![a-z0-9])", re.IGNORECASE), "720p"),
    (re.compile(r"(?<![a-z0-9])480p(?![a-z0-9])", re.IGNORECASE), "480p"),
]

# HDR / Dolby Vision markers (case-insensitive). ``HDR10`` / ``HDR10+`` are
# covered by the ``hdr`` alternative. Word-ish boundaries avoid false hits on
# substrings like "advDVd".
_HDR_RE = re.compile(
    r"(?<![a-z0-9])(?:hdr10\+?|hdr|dv|dovi|dolby[.\s_-]?vision)(?![a-z0-9])",
    re.IGNORECASE,
)


def parse_year(name: str) -> int | None:
    match = _YEAR_RE.search(name)
    return int(match.group(1)) if match else None


def parse_quality(name: str) -> str | None:
    for pattern, normalised in _QUALITY_PATTERNS:
        if pattern.search(name):
            return normalised
    return None


def parse_hdr(name: str) -> bool:
    return bool(_HDR_RE.search(name))


def parse_metadata(name: str) -> tuple[int | None, str | None, bool]:
    """Return ``(year, quality, hdr)`` parsed from a media folder/file name."""

    return parse_year(name), parse_quality(name), parse_hdr(name)
