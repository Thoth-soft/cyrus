# Phase 1: Storage Foundation - Context

**Gathered:** 2026-04-13
**Status:** Ready for planning
**Mode:** Auto-generated (infrastructure phase detected)

<domain>
## Phase Boundary

Build the bedrock library every other component depends on — atomic markdown file storage with hand-rolled frontmatter, cross-platform filelock, and the `~/.cyrus/` directory taxonomy. Zero user-visible value, but every downstream phase breaks if this has bugs.

Delivers: `cyrus.storage`, `cyrus.paths`, `cyrus.logutil` — three pure-stdlib modules with a thoroughly-tested public API. No MCP, no hook, no CLI in this phase.

</domain>

<decisions>
## Implementation Decisions

### Package Layout
- Code lives in `src/cyrus/` (per existing src-layout scaffolding)
- Tests mirror structure at `tests/` — `test_storage.py`, `test_paths.py`, `test_logutil.py`
- Only three modules shipped in this phase; `cli.py`, `hook.py`, `server.py` etc come later
- Every module imports only from stdlib — no relative imports to modules not yet built

### Storage Module (`cyrus.storage`)
- **Atomic write:** `os.replace()` after `os.fsync()` to a same-directory temp file. Never leaves partial files on crash.
- **Frontmatter parser:** Hand-rolled ~80-line YAML-subset parser — supports scalar strings/ints/bools, flat lists, ISO-8601 timestamps. No nested objects. Reject with clear error on anything complex.
- **Frontmatter dumper:** Strict output — always emits `---` delimiters, sorts keys deterministically for stable diffs.
- **Filelock:** `fcntl.flock()` on POSIX, `msvcrt.locking()` on Windows. Pick at import time based on `sys.platform`. Context manager API: `with filelock(path):`.
- **Taxonomy:** Exactly 5 fixed category folders under `~/.cyrus/`: `sessions/`, `decisions/`, `preferences/`, `projects/`, `rules/`. Enforced by API — no arbitrary categories.
- **Filename format:** `YYYY-MM-DD_<id>_<slug>.md` where `<id>` is an 8-char hash and `<slug>` is lowercase-hyphenated title (max 40 chars).

### Paths Module (`cyrus.paths`)
- `cortex_home()` returns `Path` pointing to `~/.cyrus/` by default
- `CYRUS_HOME` env var overrides — useful for testing and portable installs
- Always use `pathlib.Path`, never `os.path` (banned by CONTRIBUTING.md already)
- Return resolved absolute paths, never relative
- Serialize paths to JSON via `.as_posix()` to avoid Windows `C:\\\\Users\\\\...` backslash chaos (per research PITFALLS.md)

### Logutil Module (`cyrus.logutil`)
- Thin wrapper over `logging` — configures structured stderr-only output
- `get_logger(name)` returns a logger that always writes to `sys.stderr`
- Never to stdout (stdout is reserved for MCP protocol in later phases)
- Format: `<ISO timestamp> <level> <module>: <message>` — minimal, parseable

### Testing Strategy
- All tests use `unittest` (stdlib) — no pytest
- `CYRUS_HOME` pointed at `tempfile.mkdtemp()` for isolation — each test gets a fresh sandbox
- **100-parallel-write stress test** per STORE-07 — use `ThreadPoolExecutor` to hammer the same file, assert zero corruption and zero partial writes
- Tests must run on Windows, macOS, and Linux (CI already configured from Phase 0)
- Target: >90% line coverage for these three modules (measured via `coverage.py` dev-only, not a runtime dep)

### Claude's Discretion
- Exact hash algorithm for filename IDs (suggest blake2b with 8-byte digest — stdlib, fast)
- Exact timestamp format in log output (suggest `datetime.now(UTC).isoformat(timespec='seconds')`)
- Whether to add a `cyrus.io` subpackage for file ops or keep flat (suggest flat — only 3 modules)
- Whether to ship a helper like `storage.save_memory(category, content, ...)` or require callers to build filenames manually (suggest helper — ergonomics)

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `src/cyrus/__init__.py` — already exports `__version__`
- `src/cyrus/py.typed` — PEP 561 marker, no changes needed
- `pyproject.toml` — already declares Python 3.11+, hatchling, zero deps
- `tests/test_placeholder.py` — validate that we can add alongside without conflicts
- CI workflow — already runs `python -m unittest discover -s tests -v` on 9 matrix cells

### Established Patterns
- Stdlib-only (no deps)
- src/ layout
- unittest for testing
- Stderr-only logging (per CONTRIBUTING.md)
- `pathlib.Path` banned from `os.path` per CONTRIBUTING.md

### Integration Points
- `~/.cyrus/` directory rooted via `cyrus.paths.cortex_home()` — all file I/O goes through this
- Downstream modules (`search`, `rules`, `hook`, `server`) will import from `cyrus.storage` and `cyrus.paths`
- No external services, no network, no database

</code_context>

<specifics>
## Specific Ideas

- Filename convention **must** be grep-friendly (per research ARCHITECTURE.md): `grep -rl '<tag>' ~/.cyrus/` should work
- Frontmatter **must** be round-trippable: `dump(parse(text)) == text` for all well-formed inputs
- Atomic write **must** tolerate the process being killed mid-write — partial temp file is OK, corrupt destination is not
- Filelock **must** time out — never deadlock. Suggest 5-second default timeout.

</specifics>

<deferred>
## Deferred Ideas

- Compiled-rules pickle cache (Phase 3 or 4 concern, not storage)
- SQLite FTS5 optional index (Phase 2 decision, not this phase)
- `cyrus list-categories` CLI (Phase 6)

</deferred>

---

*Phase: 01-storage-foundation*
*Context gathered: 2026-04-13 via infrastructure auto-detection*
