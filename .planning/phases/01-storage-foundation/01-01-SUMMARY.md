---
phase: 01-storage-foundation
plan: 01
subsystem: infra
tags: [pathlib, logging, stdlib, env-override, iso-8601]

# Dependency graph
requires:
  - phase: 00-setup-and-naming-gate
    provides: src-layout scaffolding, pyproject.toml with Python 3.11+, unittest harness
provides:
  - sekha.paths module (sekha_home, category_dir, CATEGORIES)
  - sekha.logutil module (get_logger, stderr-only, ISO timestamp)
  - SEKHA_HOME env override contract
  - SEKHA_LOG_LEVEL env override contract
affects: [01-02-storage, 02-search, 03-rules, 04-hook, 05-server]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Stdlib-only: zero pip deps added (pyproject.toml unchanged)"
    - "pathlib.Path exclusively; os.path banned and grep-verified absent"
    - "Env-var-driven config (SEKHA_HOME, SEKHA_LOG_LEVEL); read on every call, no module caching"
    - "Idempotent per-logger configuration via _sekha_configured attribute tag"
    - "Stderr-only logging; stdout reserved for future MCP protocol stream"

key-files:
  created:
    - src/sekha/paths.py
    - src/sekha/logutil.py
    - tests/test_paths.py
    - tests/test_logutil.py
  modified: []

key-decisions:
  - "sekha_home() reads SEKHA_HOME on every call (no caching) so per-test overrides work without module reload"
  - "category_dir() validates against a fixed 5-tuple CATEGORIES; unknown category raises ValueError listing all valid names"
  - "Invalid SEKHA_LOG_LEVEL silently falls back to INFO (loud config errors would break tooling invoked with odd envs)"
  - "Logger tagged with _sekha_configured attr for idempotent configuration; avoids duplicate-handler stacking on repeated get_logger() calls"
  - "sekha.logutil does NOT import from sekha.paths — keeps logutil dependency-free so it remains safe to call during boot-lint of future MCP server"

patterns-established:
  - "Env-var override pattern: read on every call via os.environ.get, never cache at module load"
  - "Idempotent configuration pattern: tag the configured object (logger, etc.) and skip re-config on subsequent calls"
  - "Stderr-only discipline: explicit StreamHandler(sys.stderr), never logging.basicConfig, never rely on defaults"
  - "Fixed-taxonomy enforcement: tuple constant + validator function; enum replacement for tiny closed sets"

requirements-completed: [STORE-06]

# Metrics
duration: 3min
completed: 2026-04-12
---

# Phase 1 Plan 1: Storage Foundation — paths + logutil Summary

**Stdlib-only `sekha.paths` (SEKHA_HOME-aware home + fixed 5-category taxonomy) and `sekha.logutil` (idempotent stderr-only logger with ISO-8601 UTC timestamps) — 17 new tests green, zero dependencies added.**

## Performance

- **Duration:** ~3 min
- **Started:** 2026-04-12T22:29:18Z
- **Completed:** 2026-04-12T22:31:56Z
- **Tasks:** 3 (2 implementation TDD pairs + 1 verification)
- **Files created:** 4 (2 modules + 2 test files)
- **Files modified:** 0

## Accomplishments

- `sekha.paths.sekha_home()` resolves `~/.sekha/` with `SEKHA_HOME` env override (STORE-06 satisfied)
- `sekha.paths.CATEGORIES` locks the 5-folder taxonomy: `sessions, decisions, preferences, projects, rules`
- `sekha.paths.category_dir()` validates against the taxonomy and raises helpful `ValueError`
- `sekha.logutil.get_logger()` returns an idempotent stderr-only logger with ISO-8601 UTC seconds-precision format
- `SEKHA_LOG_LEVEL` env var honored with silent fallback-to-INFO on unknown values
- 17 new tests (9 paths + 8 logutil) plus 2 pre-existing placeholder tests — all 19 green
- Modules are < 70 lines each (well under the 100-line simplicity target)

## Task Commits

Each task was committed atomically with Red-Green TDD pairs:

1. **Task 1 RED: failing tests for sekha.paths** — `5d679bb` (test)
2. **Task 1 GREEN: implement sekha.paths** — `972d135` (feat)
3. **Task 2 RED: failing tests for sekha.logutil** — `3410594` (test)
4. **Task 2 GREEN: implement sekha.logutil** — `b483c3b` (feat)
5. **Task 3: full-suite regression check** — verification only, no files changed, no commit

No REFACTOR commits were needed — both modules came out clean on the first green pass.

## Files Created/Modified

- `src/sekha/paths.py` (56 lines) — `sekha_home()`, `category_dir()`, `CATEGORIES`
- `src/sekha/logutil.py` (66 lines) — `get_logger()` + `_IsoUtcFormatter` + `_resolve_level()`
- `tests/test_paths.py` (89 lines) — `TestSekhaHome` (6 tests), `TestCategories` (3 tests)
- `tests/test_logutil.py` (78 lines) — `TestGetLogger` (8 tests)

## Public API (for plan 01-02 to import)

```python
# src/sekha/paths.py
from sekha.paths import sekha_home, category_dir, CATEGORIES

CATEGORIES: Final[tuple[str, ...]]  # ("sessions", "decisions", "preferences", "projects", "rules")
def sekha_home() -> Path: ...        # absolute, resolved; honors $SEKHA_HOME; no caching; does NOT mkdir
def category_dir(category: str) -> Path:  # raises ValueError on unknown category
```

```python
# src/sekha/logutil.py
from sekha.logutil import get_logger

def get_logger(name: str) -> logging.Logger:
    # Idempotent; single StreamHandler(sys.stderr); format:
    #   "<YYYY-MM-DDTHH:MM:SS+00:00> <LEVEL> <name>: <message>"
    # propagate=False; level from SEKHA_LOG_LEVEL (default INFO, invalid->INFO)
```

## Decisions Made

- **No caching of `sekha_home()`**: every call re-reads `os.environ["SEKHA_HOME"]` so tests can override the home dir per-test without mutating the module table. Cost: one env lookup per call (negligible). Benefit: no test infrastructure hacks.
- **Invalid `SEKHA_LOG_LEVEL` falls back silently**: loud errors during logger construction would break any tool invoked with a malformed env. Log-level misconfig is not critical enough to crash on.
- **`sekha.logutil` does not import `sekha.paths`**: keeps the two foundation modules orthogonal. Future boot-lint of the MCP server can import `sekha.logutil` without touching the filesystem or HOME env.
- **Explicit `StreamHandler(sys.stderr)` instead of default-arg `StreamHandler()`**: stream default is stderr in CPython but the source is ambiguous across implementations — explicit is safer and grep-verifiable.
- **Logger tagged with `_sekha_configured` attribute**: chose attribute-tagging over checking `len(logger.handlers) == 0` because other code (test harness, third-party libs) could add its own handlers and we want to leave them alone.

## Deviations from Plan

None — plan executed exactly as written. All interface blocks, acceptance criteria, and test counts matched the plan specification. Test count breakdown:
- Plan expected "7+ paths tests" → delivered 9
- Plan expected "8 logutil tests" → delivered 8

## Issues Encountered

None. Both TDD cycles went RED → GREEN on first attempt; no REFACTOR needed; no test flakiness observed.

## Verification Evidence

```
$ python -m unittest discover -s tests -v 2>&1 | tail -3
Ran 19 tests in 0.009s
OK

$ python -c "from sekha.paths import sekha_home; print(sekha_home())"
C:\Users\mohab\.sekha

$ python -c "from sekha.logutil import get_logger; get_logger('test').info('hello')"
2026-04-12T22:31:52+00:00 INFO test: hello        # <-- emitted to stderr, stdout empty

$ grep -n "os\.path\|sys\.stdout\|logging\.basicConfig" src/sekha/paths.py src/sekha/logutil.py
# (no matches — forbidden patterns confirmed absent)
```

## User Setup Required

None — no external services or credentials involved.

## Next Phase Readiness

- Plan 01-02 (`sekha.storage`: atomic write + frontmatter + filelock) can now import:
  - `from sekha.paths import sekha_home, category_dir, CATEGORIES`
  - `from sekha.logutil import get_logger`
- CI matrix (Windows + macOS + Linux × Python 3.11/3.12/3.13) will re-verify cross-platform correctness on push; local Windows/Python-3.14 run already green.
- Zero pip dependencies added — `pyproject.toml` untouched. Downstream plans can continue assuming stdlib-only.

## Self-Check: PASSED

- `src/sekha/paths.py` — exists (56 lines)
- `src/sekha/logutil.py` — exists (66 lines)
- `tests/test_paths.py` — exists (89 lines, 9 tests)
- `tests/test_logutil.py` — exists (78 lines, 8 tests)
- Commits `5d679bb`, `972d135`, `3410594`, `b483c3b` — all present in `git log` on `main`
- `python -m unittest discover -s tests -v` — exit 0, 19 tests OK
- `grep` for `os.path`, `sys.stdout`, `logging.basicConfig`, `from sekha.paths` (inside logutil) — all return zero matches

---
*Phase: 01-storage-foundation*
*Completed: 2026-04-12*
