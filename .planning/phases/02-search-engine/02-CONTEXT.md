# Phase 2: Search Engine - Context

**Gathered:** 2026-04-13
**Status:** Ready for planning
**Mode:** Auto-generated (infrastructure phase detected)

<domain>
## Phase Boundary

Deliver `cyrus.search` — a pure-stdlib full-text search built on `os.walk` + `re.compile` with term-frequency × recency × filename-match scoring, ReDoS protection, and benchmarked performance against a synthetic 10k-file corpus. Proves the "grep is good enough" thesis empirically.

</domain>

<decisions>
## Implementation Decisions

### Module: `cyrus.search`

Public API:
```python
def search(
    query: str,
    category: str | None = None,
    limit: int = 10,
    since: datetime | None = None,
    tags: list[str] | None = None,
) -> list[SearchResult]: ...

@dataclass
class SearchResult:
    path: Path
    score: float
    snippet: str  # matched line + ±1 context line
    metadata: dict  # frontmatter of matched file
```

### Scoring Algorithm

`score = tf * recency_decay * filename_bonus`

- `tf` = count of case-insensitive query matches in body text
- `recency_decay` = `exp(-age_days / 30)` — files touched in last 30 days score ~1.0, older decay fast
- `filename_bonus` = 2.0 if query substring appears in filename slug, else 1.0
- Tie-breaker: most recent `updated` timestamp first

### ReDoS Guard

- Compile user-provided regex patterns with a timeout. Strategy:
  - Pre-validate: reject patterns containing nested quantifiers that look catastrophic (`(a+)+`, `(a*)*`, `(a|a)*`)
  - If regex compiles, run matches via `regex.match()` in a worker thread with `threading.Timer` killing after 100ms per file
  - On timeout, log a warning to stderr, skip that file, continue search
- Simpler fallback: if `query` contains no regex special chars, treat as literal substring — no ReDoS possible

### Filtering

- `category=X` filter: restrict `os.walk` to `~/.cyrus/X/` subdirectory
- `since=datetime` filter: skip files where `frontmatter.updated < since`
- `tags=[...]` filter: all tags must appear in `frontmatter.tags` (AND logic)

### Snippet Extraction

- For each matched file, find the FIRST matching line
- Return matched line + 1 line above + 1 line below (if they exist)
- Truncate each line to 120 chars, add `…` if truncated
- Strip frontmatter delimiters from output

### Performance Budget (STORE-07 Benchmark Target)

- **p95 search latency < 500ms** on 10,000 files, warm cache, mid-range laptop
- Benchmark fixture: generate 10,000 synthetic `.md` files once, cache in `tests/fixtures/10k-corpus/`
- Hit the target using:
  - Bounded result set (`heapq.nlargest(limit, ...)`)
  - Short-circuit on first N results if scored files exceed target
  - Skip files where filename or size suggests no match (stat before read)
  - Read files in binary mode, scan with compiled pattern, decode only for snippet

### Module Layout

```
src/cyrus/
    search.py          # public API + scoring
    _searchutil.py     # private: regex guard, snippet extraction, scoring helpers
tests/
    test_search.py     # unit tests
    test_search_bench.py   # 10k-file benchmark (skipped in fast CI by default)
    fixtures/
        generate_corpus.py  # deterministic 10k-file generator (seeded)
```

### Claude's Discretion

- Exact ReDoS detection heuristic — may start simple (string check for `+)+` and `*)*`) and improve later
- Whether to use `multiprocessing.Pool` or single-threaded — start single-threaded, measure, parallelize only if p95 misses
- Snippet highlight markers (default: no markup; caller can format)
- Whether `search()` returns a generator or list — start with list for simplicity

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `cyrus.paths.cyrus_home()` — home dir resolution
- `cyrus.storage.parse_frontmatter()` — parse frontmatter to dict (for metadata filtering)
- `cyrus.storage.CATEGORIES` — the 5 fixed category names (validate `category=` input)
- `cyrus.logutil.get_logger()` — for ReDoS timeout warnings

### Established Patterns
- Stdlib only, no deps
- `pathlib.Path` only
- `unittest` tests with `CYRUS_HOME=tempfile.mkdtemp()` isolation
- stderr-only logging

### Integration Points
- Phase 5 MCP server's `cyrus_search` tool will call `cyrus.search.search()`
- Phase 4 hook does NOT use search (hook reads rules directly)

</code_context>

<specifics>
## Specific Ideas

- Benchmark must run in CI but may be marked `@unittest.skipUnless(os.environ.get('CYRUS_BENCH'), 'bench')` to keep fast CI fast
- The 10k-file generator must be deterministic — same seed produces same corpus — so regressions are comparable
- Case-insensitive search by default; `case_sensitive=True` flag optional for power users

</specifics>

<deferred>
## Deferred Ideas

- SQLite FTS5 optional index (only if we hit the 10k-file performance wall in practice — deferred to v1.x)
- Fuzzy search (Levenshtein, etc) — not in v1 scope
- Regex ranking (promote regex matches over substring matches) — nice-to-have
- Pagination / cursor-based results — v2

</deferred>

---

*Phase: 02-search-engine*
*Context gathered: 2026-04-13 via infrastructure auto-detection*
