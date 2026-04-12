"""Public full-text search API for Cyrus. Stdlib-only.

    search(query, category=None, limit=10, since=None, tags=None)
        -> list[SearchResult]

Scoring is `tf * recency_decay(age_days) * filename_bonus(query, path)` —
formulas and constants live in cyrus._searchutil. Walks the cyrus_home()
tree with `os.walk`, filters on category / updated / tags, then scores
surviving files. Regex queries are routed through the _searchutil ReDoS
guard; literal queries (no regex metacharacters) take a faster
substring-count path.

This module is the bedrock the Phase 5 MCP server's `cyrus_search` tool
imports directly. Keep the public surface stable — callers depend on the
SearchResult dataclass field names and the keyword-argument shape of
`search()`.
"""
from __future__ import annotations

import heapq
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cyrus._searchutil import (
    extract_snippet,
    filename_bonus,
    is_literal_query,
    recency_decay,
    scan_file_with_timeout,
)
from cyrus.logutil import get_logger
from cyrus.paths import CATEGORIES, category_dir, cyrus_home
from cyrus.storage import parse_frontmatter

_log = get_logger(__name__)

# Wall-clock cap for any single file's regex scan. See _searchutil for why
# this is a pre-compile check plus a thread watchdog rather than a signal.
_REDOS_TIMEOUT_SECONDS = 0.1


@dataclass
class SearchResult:
    """A single hit from `search()`.

    - path: absolute Path to the matched .md file
    - score: tf * recency_decay * filename_bonus (see _searchutil)
    - snippet: matched line plus up to 1 line above and 1 below, each
      truncated to 120 chars
    - metadata: parsed frontmatter dict (id, category, created, updated,
      tags, and any extras the file declares)
    """

    path: Path
    score: float
    snippet: str
    metadata: dict[str, Any] = field(default_factory=dict)


def search(
    query: str,
    category: str | None = None,
    limit: int = 10,
    since: datetime | None = None,
    tags: list[str] | None = None,
) -> list[SearchResult]:
    """Full-text search over cyrus_home() memory tree.

    Returns up to `limit` SearchResult objects ordered by score descending,
    tie-broken by `metadata["updated"]` descending (lexicographic ISO-8601
    is chronological). An empty query returns [] without raising.

    Raises ValueError if `category` is not None and not in CATEGORIES.
    """
    if not query:
        return []
    if category is not None and category not in CATEGORIES:
        raise ValueError(
            f"Unknown category {category!r}. Valid: {CATEGORIES}"
        )

    roots = (
        [category_dir(category)]
        if category is not None
        else [cyrus_home() / c for c in CATEGORIES]
    )
    literal = is_literal_query(query)
    now = datetime.now(timezone.utc)

    # Tuple shape: (score, updated_iso, insertion_index, result).
    # heapq.nlargest orders element-wise: higher score first, then later
    # ISO-8601 timestamp (lex order == chrono order for ISO-8601), then
    # insertion index as the final deterministic tie-breaker. We include
    # the index to avoid comparing SearchResult instances directly (which
    # dataclasses don't support without eq/order flags).
    scored: list[tuple[float, str, int, SearchResult]] = []

    idx = 0
    for root in roots:
        if not root.exists():
            continue
        for dirpath, _dirnames, filenames in os.walk(root):
            for fname in filenames:
                if not fname.endswith(".md"):
                    continue
                path = Path(dirpath) / fname
                result = _score_file(
                    path=path,
                    query=query,
                    literal=literal,
                    now=now,
                    since=since,
                    tags_filter=tags,
                )
                if result is None:
                    continue
                scored.append(
                    (
                        result.score,
                        result.metadata.get("updated", ""),
                        idx,
                        result,
                    )
                )
                idx += 1

    top = heapq.nlargest(limit, scored)
    return [r for (_score, _updated, _idx, r) in top]


def _score_file(
    *,
    path: Path,
    query: str,
    literal: bool,
    now: datetime,
    since: datetime | None,
    tags_filter: list[str] | None,
) -> SearchResult | None:
    """Read, filter, score a single file. Returns None if filtered out,
    unreadable, malformed, or no match."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        _log.warning("search: cannot read %s: %s", path, e)
        return None

    try:
        metadata, body = parse_frontmatter(text)
    except ValueError as e:
        _log.warning("search: bad frontmatter in %s: %s", path, e)
        return None

    # since filter — ISO-8601 lex compare is chronological
    if since is not None:
        updated_str = metadata.get("updated", "")
        if not updated_str or updated_str < since.isoformat(timespec="seconds"):
            return None

    # tags filter — AND logic
    if tags_filter:
        file_tags = metadata.get("tags", [])
        if not isinstance(file_tags, list):
            return None
        if not all(t in file_tags for t in tags_filter):
            return None

    # Term-frequency via the ReDoS-guarded scanner. scan_file_with_timeout
    # reads the whole file (including frontmatter), but frontmatter matches
    # are rare and minor enough that counting over the full text is
    # acceptable. The snippet below is extracted from body only.
    tf, _timed_out = scan_file_with_timeout(
        path,
        query,
        timeout=_REDOS_TIMEOUT_SECONDS,
        is_literal=literal,
    )
    if tf <= 0:
        return None

    age_days = _age_days(metadata.get("updated", ""), now)
    score = float(tf) * recency_decay(age_days) * filename_bonus(query, path)

    snippet = extract_snippet(body, query)
    return SearchResult(
        path=path,
        score=score,
        snippet=snippet,
        metadata=metadata,
    )


def _age_days(updated_iso: str, now: datetime) -> float:
    """Convert an ISO-8601 `updated` field to age in days relative to `now`.

    Returns 0.0 on missing/unparseable values so a malformed file isn't
    penalized by an astronomical age (which would zero out its decay
    score). Naive timestamps are treated as UTC.
    """
    if not updated_iso:
        return 0.0
    try:
        dt = datetime.fromisoformat(updated_iso)
    except ValueError:
        return 0.0
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    delta = now - dt
    return delta.total_seconds() / 86400.0
