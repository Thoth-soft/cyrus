---
phase: 02-search-engine
plan: 01
subsystem: sekha.search
tags: [search, scoring, redos, snippet, stdlib]
requirements_completed: [SEARCH-01, SEARCH-02, SEARCH-03, SEARCH-04, SEARCH-06]
dependency_graph:
  requires:
    - sekha.paths (sekha_home, CATEGORIES, category_dir)
    - sekha.storage.parse_frontmatter
    - sekha.logutil.get_logger
  provides:
    - sekha.search.search
    - sekha.search.SearchResult
    - sekha._searchutil.{is_literal_query, recency_decay, filename_bonus, extract_snippet, scan_file_with_timeout}
  affects:
    - Phase 5 MCP server (sekha_search tool will import sekha.search.search)
    - Plan 02-02 (10k-file benchmark imports this module unchanged)
tech-stack:
  added: []
  patterns:
    - Stdlib-only (re, math, threading, heapq, os.walk, pathlib, dataclasses, datetime)
    - Stderr-only logging via sekha.logutil.get_logger
    - unittest.TestCase with tempfile.mkdtemp + SEKHA_HOME env isolation
    - Public/private module split (search.py vs _searchutil.py)
key-files:
  created:
    - src/sekha/search.py
    - src/sekha/_searchutil.py
    - tests/test_search.py
    - tests/test_searchutil.py
  modified: []
decisions:
  - Pre-reject catastrophic regex shapes before compile rather than relying on thread watchdog (CPython re holds the GIL; thread watchdog cannot preempt)
  - Structural ReDoS guard covers (X+)+, (X*)*, (X+)*, (X*)+, quantifier variants, and (X|Y)* alternation — superset-of-false-positives is acceptable
  - Snippet extraction uses substring (not regex) even when query is regex — keeps snippet path ReDoS-immune
  - heapq.nlargest over (score, updated, idx, result) tuples for bounded result sets + deterministic tie-breaking
  - ISO-8601 lexicographic compare used for since filter (chronological by construction)
metrics:
  duration_seconds: 427
  duration_human: "~7 min"
  tasks_completed: 4
  files_created: 4
  tests_added: 58
  tests_total_after: 120
  completed: "2026-04-12T23:02:26Z"
---

# Phase 2 Plan 01: sekha.search Core Summary

Delivered the public `sekha.search.search()` API and its private scoring/ReDoS-guard helpers in `sekha._searchutil`. Full TDD: RED commits preceded every implementation, and the ReDoS guard pre-rejects catastrophic regex shapes structurally because CPython's `re` holds the GIL and cannot be preempted by a thread watchdog.

## Public API

```python
# src/sekha/search.py

@dataclass
class SearchResult:
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
) -> list[SearchResult]: ...
```

- Empty `query` returns `[]` without raising.
- Invalid `category` raises `ValueError`.
- Results are sorted by `score` desc, tie-broken by `metadata["updated"]` desc (lex ISO-8601 == chronological).

## Scoring

```
score = tf * recency_decay(age_days) * filename_bonus(query, path)
recency_decay(age) = exp(-age / 30)      # 30-day half-life, clamped to 1.0 for age <= 0
filename_bonus(q, p) = 2.0 if q.lower() in p.name.lower() else 1.0
```

Constants: 30-day recency half-life, 2.0 filename-bonus multiplier, 100ms per-file ReDoS timeout (`_REDOS_TIMEOUT_SECONDS`).

## ReDoS Guard — Two Layers

1. **Literal fast path.** `is_literal_query(q)` is True when `q` contains none of `.^$*+?()[]{}|\` — we count matches via `text.lower().count(q.lower())`. No regex, no ReDoS surface.
2. **Regex path.** Before `re.compile`, `_is_catastrophic_pattern(q)` rejects nested-quantifier shapes `(X+)+`, `(X*)*`, `(X+)*`, `(X*)+`, quantifier variants `{n,}`/`{n,m}`, and `(X|Y)*` alternation. On reject: log warning to stderr, return `(0, True)`. Non-catastrophic regexes additionally run under a `threading.Thread` watchdog as a secondary defense for surprises the static check misses.

The structural pre-check is necessary because CPython's `re` is a C extension that holds the GIL for the entire `findall()` call — `t.join(timeout=0.1)` cannot preempt a backtracking loop, it just waits for the GIL the worker never releases. This was discovered by running the plan's thread-watchdog-only design against `(a+)+b` on 30 `a`'s — the test hung for 115 seconds before completing. Adding the pre-check brought that to under 10ms.

## Filters

- `category="rules"` restricts `os.walk` to `sekha_home() / rules/`.
- `since=datetime(2026,1,1,tz=UTC)` skips files where `metadata["updated"] < since.isoformat(timespec="seconds")`.
- `tags=["auth","jwt"]` uses AND logic — all tags must be present in `metadata["tags"]`.

## Frontmatter Fields Consumed

Downstream consumers (including this module and future callers) rely on these keys in every memory file's frontmatter:

| Key       | Type        | Used for                                                   |
| --------- | ----------- | ---------------------------------------------------------- |
| `updated` | ISO-8601 str | recency_decay age calculation + since filter              |
| `tags`    | list[str]   | tags AND-filter                                            |
| `id`, `category`, `created` | str | returned in `SearchResult.metadata`, not scored |

Malformed / missing `updated` is treated as age 0.0 (fresh) rather than penalizing the file.

## Extension Points (Deferred to v2)

- **Regex snippet highlighting.** `extract_snippet` uses substring match for line selection (ReDoS-safe). Callers needing regex-accurate highlight markers can layer that on top.
- **Pagination / cursors.** Current API returns up to `limit` results from a single scan. For 10k+ corpora a cursor token would allow resuming — deferred until benchmark shows need.
- **case_sensitive=True flag.** Everything is case-insensitive in v1 by default. Adding a flag is straightforward — plumb through `is_literal_query`, `extract_snippet`, `scan_file_with_timeout`.
- **SQLite FTS5 index.** Deferred pending the 10k benchmark in Plan 02-02. Only needed if grep misses the 500ms p95 target.

## Test Commands That Gate the Module

```bash
# Unit tests for helpers
python -m unittest tests.test_searchutil -v

# Integration tests for public API
python -m unittest tests.test_search -v

# Full regression suite (must stay green)
python -m unittest discover -s tests -v

# Import smoke test
python -c "from sekha.search import search, SearchResult; print('OK')"
```

58 new tests added; 120 tests total, all green on Windows + Python 3.14 locally.

## Requirements Verified

- **SEARCH-01** — `re.compile` + `os.walk`, zero external deps. Enforced by imports in `src/sekha/search.py` and `src/sekha/_searchutil.py`.
- **SEARCH-02** — `tf * recency_decay * filename_bonus` implemented and locked by `TestSearchScoring` (3 tests).
- **SEARCH-03** — `SearchResult.snippet` = matched line plus or minus 1 context line, 120-char truncation. Covered by `TestExtractSnippet` (8 tests) and `TestSearchSnippetExtraction` (2 tests).
- **SEARCH-04** — catastrophic `(a+)+b` against adversarial body completes in <10ms (was 115s pre-fix). Covered by `TestScanFileWithTimeout.test_catastrophic_pattern_times_out` and `TestSearchReDoS.test_catastrophic_pattern_does_not_hang`.
- **SEARCH-06** — category / since / tags filters covered by `TestSearchFilters` (6 tests). Invalid category raises `ValueError`.
- **SEARCH-05** deferred to Plan 02-02 (10k-file benchmark).

## Commits

| Task | Type | Hash     | Message                                                        |
| ---- | ---- | -------- | -------------------------------------------------------------- |
| 1    | RED  | 5d0c8dc  | test(02-01): add failing tests for _searchutil helpers         |
| 2    | GREEN| bf1d850  | feat(02-01): implement _searchutil helpers with ReDoS guard    |
| 3    | RED  | 220a789  | test(02-01): add failing tests for sekha.search public API     |
| 4    | GREEN| 07823f5  | feat(02-01): implement sekha.search public API                 |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Thread-only ReDoS watchdog cannot work on CPython re**
- **Found during:** Task 2 (Implement _searchutil)
- **Issue:** The plan's spec (and `scan_file_with_timeout` sketch) relied on `threading.Thread` + `t.join(timeout)` to kill a catastrophic regex. But CPython's `re` module is a C extension that holds the GIL for the entire `findall()` call. The main thread's `join(0.1)` never returns within 0.1s — it waits for the GIL the worker never releases. Running the test against `(a+)+b` on 30 `a`'s hung for 115 seconds.
- **Fix:** Added `_is_catastrophic_pattern()` structural pre-check that rejects the classic ReDoS shapes (`(X+)+`, `(X*)*`, `(X+)*`, `(X*)+`, `{n,}`/`{n,m}` variants, `(X|Y)*` alternation) BEFORE `re.compile` + `findall`. This matches CONTEXT.md's explicit guidance: *"Pre-validate: reject patterns containing nested quantifiers that look catastrophic"*. Kept the thread watchdog as secondary defense for regexes the static check misses.
- **Files modified:** src/sekha/_searchutil.py
- **Commit:** bf1d850
- **Result:** Catastrophic test completes in <10ms (was 115s); all 120 tests green.

### Authentication Gates

None.

## Known Stubs

None. Every file is fully wired:
- `search()` uses real `os.walk` over `sekha_home()` and returns real `SearchResult` instances with parsed frontmatter.
- `extract_snippet` returns real body-derived snippets, not placeholders.
- `scan_file_with_timeout` reads real files via `path.read_text`.

## Self-Check: PASSED

- src/sekha/search.py: FOUND
- src/sekha/_searchutil.py: FOUND
- tests/test_search.py: FOUND
- tests/test_searchutil.py: FOUND
- Commit 5d0c8dc: FOUND
- Commit bf1d850: FOUND
- Commit 220a789: FOUND
- Commit 07823f5: FOUND
- `python -m unittest discover -s tests` exits 0 with 120/120 tests passing
- `python -c "from sekha.search import search, SearchResult; print('OK')"` prints OK
