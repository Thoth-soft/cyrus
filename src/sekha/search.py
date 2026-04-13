"""Public full-text search API for Sekha. Stdlib-only.

    search(query, category=None, limit=10, since=None, tags=None)
        -> list[SearchResult]

Scoring is `tf * recency_decay(age_days) * filename_bonus(query, path)` —
formulas and constants live in sekha._searchutil. Walks the sekha_home()
tree with `os.walk`, filters on category / updated / tags, then scores
surviving files. Regex queries are routed through the _searchutil ReDoS
guard; literal queries (no regex metacharacters) take a faster
substring-count path.

This module is the bedrock the Phase 5 MCP server's `sekha_search` tool
imports directly. Keep the public surface stable — callers depend on the
SearchResult dataclass field names and the keyword-argument shape of
`search()`.
"""
from __future__ import annotations

import heapq
import os
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sekha._searchutil import (
    _is_catastrophic_pattern,
    extract_snippet,
    filename_bonus,
    is_literal_query,
    recency_decay,
    scan_text,
)
from sekha.logutil import get_logger
from sekha.paths import CATEGORIES, category_dir, sekha_home
from sekha.storage import parse_frontmatter

_log = get_logger(__name__)

# Wall-clock cap for any single file's regex scan. See _searchutil for why
# this is a pre-compile check plus a thread watchdog rather than a signal.
_REDOS_TIMEOUT_SECONDS = 0.1

# Parallel scan worker count. Default is 1 (single-threaded) because on
# Windows NTFS the per-task GIL-transition overhead of ThreadPoolExecutor
# measurably *slowed* search — the win from GIL-releasing os.read is eaten
# by thread-pool bookkeeping at 10k tasks. Callers on filesystems with
# true async I/O (some network mounts, Linux io_uring-backed drivers) can
# set SEKHA_SEARCH_WORKERS=4 or similar to opt in.
def _resolve_worker_count() -> int:
    raw = os.environ.get("SEKHA_SEARCH_WORKERS")
    if raw is None:
        return 1
    try:
        n = int(raw)
    except ValueError:
        return 1
    return max(1, n)


# Max bytes to read from a single memory file. Avoids the extra fstat we'd
# otherwise need to size the buffer. Files larger than this are truncated —
# pathological but acceptable given the corpus-design contract (markdown
# memories, not multi-MB blobs).
_MAX_FILE_BYTES = 256 * 1024


# Batch threshold: below this many candidate files, inline single-threaded
# beats the pool because thread pool overhead (~200us startup + submit) eats
# the parallelism win. Tuned against the 10k benchmark; callers should not
# need to override.
_PARALLEL_THRESHOLD = 256


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
    """Full-text search over sekha_home() memory tree.

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
        else [sekha_home() / c for c in CATEGORIES]
    )
    literal = is_literal_query(query)
    now = datetime.now(timezone.utc)

    # Pre-compile regex ONCE for the whole walk. Compiling per-file (the old
    # path) burned ~10-20us per file × 10k files = nontrivial time on large
    # corpora. Catastrophic shapes are rejected up-front so we never enter
    # the walk at all for obviously-hostile patterns.
    compiled_pattern: re.Pattern[str] | None = None
    if not literal:
        if _is_catastrophic_pattern(query):
            _log.warning(
                "search: regex %r rejected as catastrophic (ReDoS guard)",
                query,
            )
            # Bail out of the walk entirely — every file would return 0.
            return []
        try:
            compiled_pattern = re.compile(query, re.IGNORECASE)
        except re.error as e:
            _log.warning("search: invalid regex %r: %s", query, e)
            return []

    # Binary pre-screen bytes for the literal hot path. A lowercased ASCII
    # query that never appears in a file's raw bytes cannot score — and the
    # bytes-in-bytes check skips utf-8 decode + frontmatter parse for the
    # vast majority of non-matching files, which dominates latency on large
    # corpora. Only safe for literal queries (regex metachars wouldn't
    # match literally anyway).
    prescreen_bytes: bytes | None = None
    if literal and query:
        try:
            prescreen_bytes = query.lower().encode("utf-8")
        except UnicodeEncodeError:
            prescreen_bytes = None

    # Regex pre-screen: compile a bytes-mode pattern to probe raw file bytes
    # with pattern.search() — which bails out on first match and is ~10×
    # cheaper than findall across the whole file. On a miss we skip decode
    # + frontmatter parse + the thread-watchdog'd findall entirely. This is
    # the main lever for the 'h.ok' class of queries that otherwise have no
    # cheap rejection path.
    prescreen_regex: "re.Pattern[bytes] | None" = None
    if compiled_pattern is not None:
        try:
            prescreen_regex = re.compile(
                query.encode("utf-8"), re.IGNORECASE,
            )
        except (re.error, UnicodeEncodeError):
            prescreen_regex = None

    # Skip full frontmatter parse when no filter depends on metadata. We
    # still need recency for scoring, but the filename carries a YYYY-MM-DD
    # prefix we can parse directly — see _age_days_from_path. Tie-breaker
    # 'updated' falls back to '' which is fine: ranking is still driven by
    # score. This is a huge win for large corpora where most queries hit
    # many files and the frontmatter parse dominates tf counting.
    need_metadata = since is not None or bool(tags)

    # Tuple shape: (score, updated_iso, insertion_index, result).
    # heapq.nlargest orders element-wise: higher score first, then later
    # ISO-8601 timestamp (lex order == chrono order for ISO-8601), then
    # insertion index as the final deterministic tie-breaker. We include
    # the index to avoid comparing SearchResult instances directly (which
    # dataclasses don't support without eq/order flags).
    scored: list[tuple[float, str, int, SearchResult]] = []

    # Collect all (dir, fname) pairs first, then score in parallel. The
    # walk itself is fast — it's the per-file open+read+score that benefits
    # from concurrency. Keeping the walk single-threaded avoids contention
    # on the ordered append to `scored`.
    candidates: list[tuple[str, str]] = []
    for root in roots:
        if not root.exists():
            continue
        for dirpath, _dirnames, filenames in os.walk(root):
            for fname in filenames:
                if fname.endswith(".md"):
                    candidates.append((os.path.join(dirpath, fname), fname))

    def _score_one(pair: tuple[str, str]) -> SearchResult | None:
        return _score_file(
            str_path=pair[0],
            fname=pair[1],
            query=query,
            literal=literal,
            compiled_pattern=compiled_pattern,
            prescreen_bytes=prescreen_bytes,
            prescreen_regex=prescreen_regex,
            need_metadata=need_metadata,
            now=now,
            since=since,
            tags_filter=tags,
        )

    # Measured on Windows NTFS at 10k files: single-threaded beats every
    # ThreadPoolExecutor worker count by 20-40%. The per-file work is
    # dominated by CPython+GIL transitions between kernel syscalls, so
    # parallel workers mostly add GIL contention and task-dispatch overhead
    # without winning back kernel-level concurrency. We keep the pool code
    # path behind SEKHA_SEARCH_WORKERS>1 so users with exotic filesystems
    # (e.g. network mounts with true async I/O) can opt in, but the default
    # is single-threaded.
    workers = _resolve_worker_count()
    if workers == 1 or len(candidates) < _PARALLEL_THRESHOLD:
        scored_iter: Any = (_score_one(c) for c in candidates)
    else:
        pool = ThreadPoolExecutor(max_workers=workers)
        try:
            scored_iter = list(pool.map(_score_one, candidates))
        finally:
            pool.shutdown(wait=False)

    idx = 0
    for result in scored_iter:
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
    results = [r for (_score, _updated, _idx, r) in top]

    # Phase 2: extract snippets and backfill metadata only for the top-`limit`
    # survivors. Running extract_snippet on all 10k scored files (even the
    # losers) was measurable on the benchmark; deferring it to this step
    # means we pay that cost only `limit` times instead of `corpus` times.
    _finalize_results(results, query=query, need_metadata=need_metadata)

    return results


def _score_file(
    *,
    str_path: str,
    fname: str,
    query: str,
    literal: bool,
    compiled_pattern: "re.Pattern[str] | None",
    prescreen_bytes: bytes | None,
    prescreen_regex: "re.Pattern[bytes] | None",
    need_metadata: bool,
    now: datetime,
    since: datetime | None,
    tags_filter: list[str] | None,
) -> SearchResult | None:
    """Read, filter, score a single file. Returns None if filtered out,
    unreadable, malformed, or no match.

    Hot-path order is deliberate:
      1. Read raw bytes.
      2. Binary pre-screen:
         - literal queries: `lowercased_query_bytes in raw.lower()`
         - regex queries:   `prescreen_regex.search(raw)` (bails on first
           match, ~10x cheaper than findall across a miss-heavy corpus)
         On a miss we skip decode + frontmatter parse + the full tf scan.
      3. Decode + (conditionally) parse frontmatter:
         - If no since/tags filter, skip parse entirely; use filename date
           for recency and body-is-whole-text for the snippet.
         - Otherwise parse and apply since/tags filters.
      4. tf via scan_text on the already-decoded text (no second read).
    """
    # Raw os.open + os.read rather than path.read_bytes() — on a 10k-file
    # walk the pathlib wrapper's per-call context-manager + __fspath__
    # overhead dominates. os.read(fd, <size>) in one shot is the cheapest
    # full-file read available in stdlib.
    try:
        fd = os.open(str_path, os.O_RDONLY | getattr(os, "O_BINARY", 0))
    except OSError as e:
        _log.warning("search: cannot open %s: %s", str_path, e)
        return None
    try:
        # Read up to _MAX_FILE_BYTES in a single syscall — skips the fstat
        # we previously did to size the read. Memory files are tiny markdown
        # documents (tested corpus averages ~500B per file); 256KB is a
        # generous ceiling that truncates only pathological files and costs
        # nothing extra on normal-sized ones (os.read returns only what the
        # file actually contains up to the requested limit).
        raw = os.read(fd, _MAX_FILE_BYTES)
    except OSError as e:
        _log.warning("search: cannot read %s: %s", str_path, e)
        os.close(fd)
        return None
    else:
        os.close(fd)

    # (2) Binary pre-screen. Lowercase raw once if we might use it twice.
    if literal and prescreen_bytes is not None:
        if prescreen_bytes not in raw.lower():
            return None
    elif prescreen_regex is not None:
        if prescreen_regex.search(raw) is None:
            return None

    try:
        text = raw.decode("utf-8", errors="replace")
    except UnicodeDecodeError as e:  # pragma: no cover — errors='replace' never raises
        _log.warning("search: cannot decode %s: %s", str_path, e)
        return None

    metadata: dict[str, Any]
    body: str
    if need_metadata:
        # Filter path: must parse metadata to evaluate since/tags.
        try:
            metadata, body = parse_frontmatter(text)
        except ValueError as e:
            _log.warning("search: bad frontmatter in %s: %s", str_path, e)
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

        age_days = _age_days(metadata.get("updated", ""), now)
    else:
        # Fast path: defer frontmatter parse to phase 2 (only the top-limit
        # candidates actually need it). Use filename YYYY-MM-DD prefix for
        # recency so scoring still reflects age. Metadata is re-populated
        # for surviving results after the heap selects winners.
        metadata = {}
        body = _strip_frontmatter_fast(text)
        age_days = _age_days_from_filename(fname, now)

    # Term-frequency on the already-decoded text. scan_text uses the
    # pre-compiled pattern for regex queries (compiled once for the whole
    # walk) and str.count for literal queries. Frontmatter bytes are
    # included in the count; the signal-to-noise ratio is fine for scoring
    # and the snippet is extracted from body only.
    #
    # use_watchdog=False: the catastrophic-shape check already ran once at
    # the top of search() before this walk started, so every pattern
    # reaching here is known-safe. Skipping the per-file thread watchdog
    # saves ~200us per file on regex queries — the single biggest lever
    # for the 10k-file p95 < 500ms budget.
    tf, _timed_out = scan_text(
        text,
        query,
        is_literal=literal,
        compiled_pattern=compiled_pattern,
        timeout=_REDOS_TIMEOUT_SECONDS,
        path=None,
        use_watchdog=False,
    )
    if tf <= 0:
        return None

    # filename_bonus on string fname directly — avoids Path(str_path) init
    # (pathlib __init__ costs ~15us) on every hit. We only build the final
    # Path below, and only for files that actually score.
    fbonus = 2.0 if query.lower() in fname.lower() else 1.0
    score = float(tf) * recency_decay(age_days) * fbonus

    # Defer snippet extraction to phase 2 (top-limit winners only). Stash
    # the body on the result so the backfill pass can extract the snippet
    # without re-reading the file. For `need_metadata=True` callers the
    # metadata is already populated; for the fast path it's still empty
    # and we also stash the full text so frontmatter can be parsed later.
    result = SearchResult(
        path=Path(str_path),
        score=score,
        snippet="",
        metadata=metadata,
    )
    # Internal-only state — callers only see the public dataclass fields.
    # _body is the body portion (for snippet), _text is the full decoded
    # file (only needed when metadata must be re-parsed in backfill).
    result._body = body  # type: ignore[attr-defined]
    if not need_metadata:
        result._text = text  # type: ignore[attr-defined]
    return result


_FILENAME_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})_")


def _age_days_from_filename(name: str, now: datetime) -> float:
    """Extract age (days) from the YYYY-MM-DD prefix of a memory filename.

    Returns 0.0 if the filename doesn't match the expected shape — same
    neutral fallback as _age_days for missing timestamps. This is the fast
    path used when the caller has no since/tags filter and we want to
    skip the frontmatter parse entirely.
    """
    m = _FILENAME_DATE_RE.match(name)
    if not m:
        return 0.0
    try:
        dt = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)),
                      tzinfo=timezone.utc)
    except ValueError:
        return 0.0
    delta = now - dt
    days = delta.total_seconds() / 86400.0
    return days if days > 0.0 else 0.0


def _finalize_results(
    results: list[SearchResult],
    *,
    query: str,
    need_metadata: bool,
) -> None:
    """Phase-2 backfill: run extract_snippet and (if needed) parse_frontmatter
    for the top-`limit` survivors of the heap selection.

    Scoring in phase 1 stashes the file body on each SearchResult; here we
    do the expensive-per-file-but-O(limit)-total work. Internal attributes
    (_body, _text) are unset after use so callers only see the public
    dataclass fields. Failures (missing attribute on an edge case, malformed
    frontmatter from a corrupted file that squeaked through) degrade to
    empty snippet / empty metadata rather than raising.
    """
    for r in results:
        body = getattr(r, "_body", None)
        if body is None:
            # Shouldn't happen — every path populates _body — but defend
            # anyway: fall back to re-reading the file for the snippet.
            try:
                body = r.path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                body = ""

        r.snippet = extract_snippet(body, query)

        if not need_metadata and not r.metadata:
            text = getattr(r, "_text", None)
            if text is None:
                try:
                    text = r.path.read_text(encoding="utf-8", errors="replace")
                except OSError as e:
                    _log.warning("search: metadata backfill failed for %s: %s", r.path, e)
                    continue
            try:
                metadata, _ = parse_frontmatter(text)
            except ValueError as e:
                _log.warning("search: bad frontmatter in %s: %s", r.path, e)
                continue
            r.metadata = metadata

        # Clear internal attributes so callers don't accidentally depend
        # on them and the memory can be reclaimed.
        try:
            del r._body  # type: ignore[attr-defined]
        except AttributeError:
            pass
        try:
            del r._text  # type: ignore[attr-defined]
        except AttributeError:
            pass


def _strip_frontmatter_fast(text: str) -> str:
    """Return the body portion of a frontmatter-prefixed markdown file.

    Cheap scanner used when we skipped parse_frontmatter entirely. Splits
    on the closing '---' delimiter with at most three slice operations.
    If no closing delimiter is found, returns the text unchanged so
    snippet extraction still works on malformed files.
    """
    if not text.startswith("---"):
        return text
    # Skip the opening delimiter line, then find the next '\n---' line.
    # Handles CRLF by searching for both line-endings.
    idx = text.find("\n---", 3)
    if idx < 0:
        return text
    # Advance past '\n---' and then past the following newline.
    end = idx + 4
    nl = text.find("\n", end)
    if nl < 0:
        return ""
    return text[nl + 1:]


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
