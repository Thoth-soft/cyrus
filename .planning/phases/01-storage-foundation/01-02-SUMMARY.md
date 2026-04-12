---
phase: 01-storage-foundation
plan: 02
subsystem: storage
tags: [atomic-write, filelock, frontmatter, fcntl, msvcrt, blake2b, stdlib, unittest]

# Dependency graph
requires:
  - phase: 01-storage-foundation
    provides: cyrus.paths (cyrus_home, category_dir, CATEGORIES), cyrus.logutil (get_logger)
provides:
  - cyrus.storage.atomic_write (fsync + os.replace, same-dir temp file)
  - cyrus.storage.filelock (cross-platform context manager, 5s default timeout, FilelockTimeout)
  - cyrus.storage.parse_frontmatter / dump_frontmatter (YAML subset, round-trip safe)
  - cyrus.storage.slugify (NFKD ASCII-fold, 40-char cap)
  - cyrus.storage.make_memory_path (YYYY-MM-DD_<8hex>_<slug>.md via blake2b-4)
  - cyrus.storage.save_memory (composes all above; single public write API)
affects: [02-search-local, 03-rules-engine, 04-hook-prehook, 05-mcp-server]

# Tech tracking
tech-stack:
  added: []  # stdlib only — zero new dependencies
  patterns:
    - "Atomic write dance: write to sibling temp, fsync, os.replace"
    - "Cross-platform filelock via sys.platform gate at IMPORT time (not runtime)"
    - "Hand-rolled YAML subset — reject complex input loudly, never silently"
    - "Deterministic frontmatter serialization (sorted keys) for stable diffs"
    - "TDD with unittest: RED commit → GREEN commit per task"

key-files:
  created:
    - src/cyrus/storage.py (386 lines — the whole public storage API)
    - tests/test_storage.py (358 lines — 43 tests including STORE-07 stress)
  modified: []

key-decisions:
  - "blake2b(seed, digest_size=4) — stdlib, 8 hex chars, deterministic with same seed"
  - "Temp file lives in SAME directory as target so os.replace is truly atomic"
  - "Lock files never deleted on release — cleanup races cause more harm than the footprint"
  - "Platform primitive chosen at import time (sys.platform == 'win32'), not each call"
  - "ISO timestamps kept as strings through parse/dump — round-trip lossless"
  - "bool checked BEFORE int in _dump_value because bool is an int subclass in Python"
  - "msvcrt.locking requires a priming byte; filelock writes b'\\0' if lock file is empty"
  - "extra_metadata cannot override core fields (id/category/created/updated/tags)"

patterns-established:
  - "Public API: lowercase snake_case functions, FilelockTimeout is the only new exception"
  - "Module docstring explains WHY + key invariants (not a bullet list of functions)"
  - "All file I/O flows through atomic_write + filelock — never a naked open()"
  - "Testing pattern: _TempHomeMixin sets CYRUS_HOME to tempfile.mkdtemp per-test"

requirements-completed: [STORE-01, STORE-02, STORE-03, STORE-04, STORE-05, STORE-07]

# Metrics
duration: 9min
completed: 2026-04-12
---

# Phase 1 Plan 02: Storage Foundation Summary

**`cyrus.storage` — atomic markdown writes with hand-rolled frontmatter, cross-platform filelock (fcntl/msvcrt), blake2b-hashed filenames, and a 100-parallel-write stress test that runs in ~1.0s with zero corruption.**

## Performance

- **Duration:** ~9 min
- **Started:** 2026-04-12T22:32:00Z
- **Completed:** 2026-04-12T22:41:07Z
- **Tasks:** 3 (Task 3 was verification-only, no commit)
- **Files modified:** 2 (`src/cyrus/storage.py`, `tests/test_storage.py`)

## Accomplishments
- `save_memory(category, content, ...)` is the single public write API every downstream phase will use
- 100-thread stress test against a single file: final content matches exactly one writer, never interleaved — STORE-07 proven locally
- 100-thread stress test across distinct files: 100 unique parseable files, zero lost writes
- Hand-rolled YAML subset parser: ~60 lines, CRLF tolerant, round-trip lossless
- Zero pip dependencies added (pyproject.toml untouched)
- Total test count jumped from 19 to 62 (43 new tests in this plan)

## Public API

```python
# Exceptions
FilelockTimeout(TimeoutError)          # lock not acquired within timeout

# Primitives
atomic_write(path, content, *, encoding="utf-8") -> None
filelock(path, *, timeout=5.0) -> ContextManager[None]

# Filename helpers
slugify(text, *, max_len=40) -> str
make_memory_path(category, title, *, when=None, seed=None) -> Path

# Frontmatter (YAML subset)
parse_frontmatter(text) -> tuple[dict[str, Any], str]
dump_frontmatter(metadata, body) -> str

# High-level write API
save_memory(category, content, *, title=None, tags=None, source=None,
            extra_metadata=None) -> Path
```

## Frontmatter Subset Supported

Parser/dumper handle only this subset (everything else rejected with ValueError):

| Value type | Parse example | Dump example |
|-----------|---------------|--------------|
| String (bare) | `id: abc` → `"abc"` | `"abc"` → `id: abc` |
| String (quoted, has `:`) | `url: "https://ex.com:80"` → `"https://ex.com:80"` | `"https://ex.com:80"` → `url: "https://ex.com:80"` |
| Integer | `count: 42` → `42` | `42` → `count: 42` |
| Boolean | `active: true` → `True` | `True` → `active: true` |
| Flat flow list | `tags: [a, b]` → `["a", "b"]` | `["a", "b"]` → `tags: [a, b]` |
| ISO timestamp | `created: 2026-04-13T10:00:00+00:00` → kept as str | str → emitted as-is |
| Empty list | `tags: []` → `[]` | `[]` → `tags: []` |

**Rejected:** nested dicts, nested lists, block scalars, anchors, aliases, multi-line strings.

## Task Commits

1. **Task 1 RED: failing tests for primitives** — `24d3104` (test)
2. **Task 1 GREEN: atomic_write, filelock, slugify, make_memory_path** — `7d31aa3` (feat)
3. **Task 2 RED: failing tests for frontmatter + save_memory + stress** — `e226178` (test)
4. **Task 2 GREEN: parse_frontmatter, dump_frontmatter, save_memory** — `d928aec` (feat)
5. **Task 3: verification only — no commit** (full suite ran, smoke test passed, pyproject.toml diff empty)
6. **Plan metadata: SUMMARY.md + STATE.md + REQUIREMENTS.md** — `d1bf76e` (docs)
7. **Post-push fix: path-resolution robustness in one test** — `efc25f3` (fix, Rule 1 deviation)

## Files Created/Modified
- `src/cyrus/storage.py` — 386 lines, entire public storage API
- `tests/test_storage.py` — 358 lines, 43 tests across 7 TestCase classes

## Stress Test Observations

STORE-07 runtime on local Windows 11 machine (Python 3.13, ThreadPoolExecutor max_workers=20):

| Test | Writers | Target | Time |
|------|---------|--------|------|
| `test_100_parallel_save_memory` | 100 | 100 distinct files | ~0.6s |
| `test_100_parallel_same_file` | 100 | 1 shared file | ~0.4s |
| **Combined TestConcurrentWrites** | — | — | **~1.0s** |

Zero corruption, zero partial writes, zero deadlocks observed. Useful as a baseline for Phase 2 search benchmarks.

## Decisions Made

All decisions were specified in 01-CONTEXT.md or the plan's `<action>` block. No novel decisions required. See the `key-decisions` frontmatter for the full list with rationale.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Made `test_cyrus_home_respected` robust to path resolution**
- **Found during:** Post-push CI verification (Task 3 follow-up)
- **Issue:** The test used `str(p).startswith(self._tmp)` to verify files land under the CYRUS_HOME tempdir. On Linux this worked, but CI failed on macOS and Windows:
  - **macOS:** `tempfile.mkdtemp()` returns `/var/folders/...` but `cyrus_home()` calls `.resolve()` which rewrites `/var` → `/private/var`, so the raw string comparison fails.
  - **Windows:** short-name / casing normalization can diverge between the tempdir string and the resolved path.
  - Failed cells: macOS 3.11/3.13, Windows 3.11/3.12/3.13 (5 of 9).
- **Fix:** Replaced the raw-string comparison with `p.resolve().is_relative_to(Path(self._tmp).resolve())`, which is the real invariant we wanted to assert.
- **Files modified:** `tests/test_storage.py`
- **Verification:** All 9 CI matrix cells green on run `24318207975` after the fix.
- **Committed in:** `efc25f3` (standalone fix commit, after `d1bf76e` plan-docs commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 bug — flaky test expectation, production code unchanged)
**Impact on plan:** None. Production code in `cyrus.storage` is byte-identical to what Task 2 shipped. The deviation was discovered only because the plan mandated "push and let CI prove cross-platform correctness" — exactly the control the plan intended.

## Issues Encountered

- Initial local run (Windows 11) passed all 43 tests, masking the cross-platform issue in `test_cyrus_home_respected` (the test was logically close-enough on Windows but not bulletproof). CI caught it on all non-local cells. One 8-line patch resolved all 5 failing cells with no changes to `src/cyrus/storage.py`.

## User Setup Required

None — zero external services, zero credentials, zero new dependencies.

## Next Phase Readiness

- **Phase 2 (search):** can `from cyrus.storage import parse_frontmatter` to index existing memories and `save_memory` to write the FTS index metadata
- **Phase 3 (rules):** will `save_memory(category="rules", ...)` with compiled-rule pickles referenced in frontmatter
- **Phase 4 (hook):** reads via `parse_frontmatter`; writes via `save_memory`
- **Phase 5 (MCP server):** all stdout stays clean because `cyrus.logutil` routes everything to stderr and `save_memory` only emits INFO log lines (also stderr)

No blockers. CI will confirm cross-platform correctness on the next push (9 matrix cells: Windows/macOS/Linux × 3.11/3.12/3.13).

## Self-Check: PASSED

- `src/cyrus/storage.py` exists (386 lines)
- `tests/test_storage.py` exists (358 lines, 43 tests)
- Commits verified: `24d3104`, `7d31aa3`, `e226178`, `d928aec` all present in `git log`
- `python -m unittest discover -s tests -v` — 62 tests, OK
- `python -c "from cyrus.storage import save_memory, parse_frontmatter, dump_frontmatter, atomic_write, filelock, FilelockTimeout, slugify, make_memory_path"` — ok
- Smoke test produced file `/sessions/2026-04-12_21394292_end-to-end-smoke.md` matching the required regex
- `git diff pyproject.toml` is empty (zero-dep constraint intact)

---
*Phase: 01-storage-foundation*
*Completed: 2026-04-12*
