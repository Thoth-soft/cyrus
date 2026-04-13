---
phase: 04-pretool-hook
plan: 01
subsystem: pretool-hook
tags: [hook, cli, fail-open, kill-switch, stdout-sacred, lazy-imports, TDD]
requires:
  - sekha.rules (Phase 3) — load_rules, evaluate, Rule dataclass
  - sekha.paths (Phase 1) — sekha_home, category_dir
provides:
  - "sekha.cli:main — argparse entry point (satisfies pyproject console script)"
  - "sekha.hook:main / _run / enable / disable"
  - "sekha._hookutil — read_event, emit_block/warn/allow, fail_open, record_error, marker mgmt"
affects:
  - pyproject.toml [project.scripts] sekha = "sekha.cli:main" (already present, now honored)
tech-stack-added: []
patterns:
  - "Lazy-imports discipline: module top of hook.py holds only sys + json; ast-introspection test enforces it."
  - "Stdout-sacred: sys.stdout is swapped to stderr inside _run() before any non-stdlib import; real stdout is passed to emitters explicitly and restored in finally."
  - "Fail-open: top-level try/except around the hook body logs to ~/.sekha/hook-errors.log, warns on stderr, returns 0. Never re-raises."
  - "Kill switch source-of-truth is the error log itself: record_error parses ISO timestamps from the tail; no separate counter file."
  - "CLI Windows cp1252 guard: stdout/stderr.reconfigure(encoding='utf-8', errors='replace') at main() entry (Pitfall 4)."
key-files:
  created:
    - src/sekha/cli.py
    - src/sekha/hook.py
    - src/sekha/_hookutil.py
    - tests/test_cli.py
    - tests/test_hook.py
    - tests/test_hookutil.py
    - tests/fixtures/hook_events/__init__.py
    - tests/fixtures/hook_events/bash_rm_rf.json
    - tests/fixtures/hook_events/write_file.json
    - tests/fixtures/hook_events/read_file.json
  modified: []
decisions:
  - "Kill-switch constants: _KILL_WINDOW_SECONDS=600 (10 min), _KILL_THRESHOLD=3. Source-of-truth is the error-log tail (~40 lines scanned per invocation), not a side counter — crash-safe, zero extra I/O."
  - "Lazy imports of sekha.rules + sekha.paths + sekha._hookutil live inside _run(), not at hook.py module top. Enforced structurally by tests/test_hook.py::TestModuleTopImportsAreLazy (ast-based)."
  - "stdout-sacred discipline: sys.stdout = stderr on entry to _run() so a rogue print() in any transitively imported module cannot corrupt the protocol channel. Real stdout is captured as a local and passed to emit_block/warn explicitly. Restored in finally."
  - "CLI hook bench is registered in argparse but gracefully falls back to a friendly 'not yet implemented' stderr message via ImportError. Plan 04-02 lands the real bench; the ImportError path disappears automatically then — no stub to clean up."
  - "Windows cp1252 guard (Rule 2 deviation from Pitfall 4): stdout/stderr reconfigure to utf-8/replace at CLI entry. Needed because argparse --help output may contain non-ASCII on future commands (init banner, doctor check marks). The hook run subcommand emits only ASCII JSON so it was not affected directly, but the CLI help text already tripped it during manual verification."
metrics:
  duration_seconds: 441
  completed: 2026-04-13T00:32:50Z
  tasks_completed: 3
  tests_before: 175
  tests_after: 215
  new_tests: 40
  commits: 6
---

# Phase 4 Plan 01: PreToolUse Hook Core Summary

**One-liner:** Shipped the Sekha differentiator — `sekha hook run` emits the exact Claude Code `permissionDecision: deny` JSON on stdout (and the reason on stderr, and exit 2) when a block-severity rule matches; fail-open + kill-switch + lazy-imports discipline make it survive being invoked hundreds of times per session without ever locking Claude Code out.

## Goal recap

Build `sekha.cli` (argparse router) + `sekha.hook` (PreToolUse entry) + `sekha._hookutil` (private helpers) so that a real Claude Code install can block tool calls via user-authored rules. Three TDD tasks; each RED→GREEN pair committed atomically.

## What landed

### Module surface

**`src/sekha/cli.py`** — argparse router
- `main(argv: list[str] | None = None) -> int` — accepts explicit argv for test hermeticity.
- Subcommands: `sekha hook {run, bench, enable, disable}`. Every subcommand module is lazy-imported inside its dispatch branch so `sekha --help` never pulls in `sekha.hook`.
- `hook bench` falls back to `"sekha hook bench: not yet implemented (lands in plan 04-02)\n"` on stderr via ImportError. No stub in `sekha.hook` to tear down later.
- Windows cp1252 guard: reconfigures stdout + stderr to `utf-8`/`replace` at entry.

**`src/sekha/hook.py`** — PreToolUse hook
- Module-top imports: `sys`, `json`, `__future__` — nothing else. Enforced by `tests/test_hook.py::TestModuleTopImportsAreLazy` (ast-based).
- `_run(stdin, stdout, stderr) -> int` — core decision loop. Swaps `sys.stdout → stderr` on entry (stdout-sacred), checks kill switch, parses event, calls `load_rules` + `evaluate`, dispatches to `emit_block/warn/allow`. Top-level `except Exception` calls `fail_open` + `record_error`; tripping the threshold creates the kill-switch marker. Always restores `sys.stdout` in `finally`.
- `main()` — thin wrapper around `_run(sys.stdin, sys.stdout, sys.stderr)`.
- `enable()` / `disable()` — clear / create the marker.
- `bench()` intentionally **not** here — landed in plan 04-02.

**`src/sekha/_hookutil.py`** — private helpers (stdlib + `sekha.paths` only)
- `read_event(stream) -> dict` — parses JSON, raises `ValueError` on empty/malformed.
- `emit_block(reason, stdout, stderr) -> 2` — writes the exact deny JSON, writes reason to stderr, returns exit 2 (belt-and-suspenders, HOOK-05).
- `emit_warn(message, stdout) -> 0` — writes the exact additionalContext JSON.
- `emit_allow(stdout) -> 0` — no-op writer (absence = allow).
- `fail_open(exc, stderr) -> 0` — appends `<ISO-8601 UTC> <type>: <msg>\n<traceback>\n\n` to `~/.sekha/hook-errors.log`, writes one-line warning to stderr, returns 0. Creates parent dir.
- `record_error(exc) -> bool` — parses the last 40 log lines and returns True iff ≥3 entries have ISO timestamps within the 600s window. File-as-source-of-truth.
- `create_marker()` / `clear_marker()` / `check_kill_switch()` — idempotent marker management.
- `error_log_path()` / `marker_path()` — SEKHA_HOME-aware path helpers.

### Exact JSON shapes emitted

**Block** (stdout, plus reason to stderr, exit 2):
```json
{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": "<rule.message>"}}
```

**Warn** (stdout, exit 0):
```json
{"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": "<rule.message>"}}
```

**Allow** (empty stdout, exit 0).

### Kill switch
- Window: **600 seconds** (10 minutes)
- Threshold: **3 errors**
- Source-of-truth: the error-log tail, not a side counter file
- Marker: `~/.sekha/hook-disabled.marker`
- `sekha hook enable` removes it; `sekha hook disable` creates it.

### Regression shields (the ones that will matter in 6 months)

1. **`tests/test_hook.py::TestModuleTopImportsAreLazy::test_top_of_hook_py_imports_only_sys_and_json`** — parses `src/sekha/hook.py` with `ast` and asserts module-level imports ⊆ `{sys, json, __future__}`. Catches future regressions where someone "helpfully" moves `from sekha.rules import ...` to the top of the file.

2. **`tests/test_hook.py::TestImportTime::test_import_sekha_hook_is_fast`** — subprocess-runs `python -c "import sekha.hook"` three times, takes the median, fails if wildly over budget. Informational for the formal HOOK-09 budget (<30ms) which is enforced structurally by the ast test.

3. **`tests/test_hook.py::TestStdoutSacred::test_stdout_is_sacred_no_stray_prints`** — installs a block rule, runs `_run`, asserts stdout contains exactly one JSON document and no log-format prefixes (`INFO `, `ERROR `, `WARNING `).

4. **`tests/test_hookutil.py::TestImportHygiene::test_no_heavy_sekha_imports_at_top`** — ast-asserts `_hookutil.py` imports no `sekha.rules / storage / search / logutil`.

5. **`tests/test_cli.py::TestConsoleScript::test_console_script_entry_resolves`** — resolves the `sekha` console script via `importlib.metadata.entry_points` and asserts it points at `sekha.cli:main`. Catches packaging regressions.

## Tests

| Suite               | Count | Status |
|---------------------|-------|--------|
| `test_hookutil`     | 21    | pass   |
| `test_hook`         | 11    | pass   |
| `test_cli`          | 10    | pass   |
| **New this plan**   | **42**| **pass** |
| Whole project       | 215   | pass (1 skipped) |

> The objective's expectation was "200+ tests" — we're at 215. No regressions in Phases 1-3.

## Performance observed (dev machine, Windows 11 + Python 3.14)

- `python -X importtime -c "import sekha.hook"` cumulative self-time for `sekha.hook`: **~13-19ms** across runs. Well under the 30ms HOOK-09 budget.
- No `sekha.rules`, `sekha.paths`, `sekha.logutil`, or `sekha.storage` appear in the import trace when just `sekha.hook` is imported — lazy-imports work as designed.
- End-to-end `python -m sekha.cli hook run` with a benign event and empty SEKHA_HOME completed under 300ms wall clock (most of that is Python cold-start). Baseline for plan 04-02 bench to beat on p50/p95.

## Smoke tests executed

```bash
# Block
echo '{"session_id":"t",...,"tool_name":"Bash","tool_input":{"command":"rm -rf /"},...}' \
  | SEKHA_HOME=/tmp/sekha-smoke python -m sekha.cli hook run
# -> stderr: "rm -rf is blocked by Sekha"
# -> stdout: {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": "rm -rf is blocked by Sekha"}}
# -> exit 2

# Allow
echo '{...,"tool_name":"Bash","tool_input":{"command":"ls -la"},...}' \
  | SEKHA_HOME=/tmp/sekha-smoke python -m sekha.cli hook run
# -> stderr: empty
# -> stdout: empty
# -> exit 0
```

Both passed.

## Deviations from Plan

### Auto-fixed issues

**1. [Rule 2 - Critical functionality] Added Windows cp1252 guard in cli.py**

- **Found during:** Task 3 manual verification of `python -m sekha.cli hook --help`.
- **Issue:** Help text originally contained `→` (U+2192). On Windows cp1252 (default stdout encoding for Python 3.14 when attached to some bash wrappers), writing `→` raised `UnicodeEncodeError: 'charmap' codec can't encode character '\u2192'` and crashed the CLI before argparse could even print usage. This is exactly Pitfall 4 from `.planning/research/PITFALLS.md` (BLOCKER severity).
- **Fix:** Two parts.
  1. Replaced the `→` in help strings with ASCII alternatives (`to`, `-`).
  2. Added `stream.reconfigure(encoding="utf-8", errors="replace")` for stdout + stderr at the top of `cli.main()` as defense-in-depth for future subcommands (Phase 6 init/doctor banners may contain non-ASCII).
- **Files modified:** `src/sekha/cli.py`.
- **Commit:** `4e23ec7` (folded into the Task 3 GREEN commit rather than a separate fix commit — the fix was discovered + applied before GREEN was committed).

No other deviations. Tasks 1 and 2 executed exactly per the plan.

## Authentication gates

None encountered — this plan is fully offline.

## Known Stubs

None. `sekha hook bench` is deliberately not stubbed in `sekha.hook` — the CLI catches ImportError and surfaces a friendly message until plan 04-02 lands the real implementation. This is documented as intentional behavior and tested in `tests/test_cli.py::test_hook_bench_without_impl_returns_friendly_error`.

## Next

**Plan 04-02** (next): implement `sekha.hook.bench` (p50/p95/p99 over 100 subprocess invocations) and automate the block-all-bash integration test. This plan's shape enables it — `sekha.hook.bench` will simply be added; no existing code needs to change.

## Self-Check: PASSED

- `src/sekha/cli.py` — FOUND
- `src/sekha/hook.py` — FOUND
- `src/sekha/_hookutil.py` — FOUND
- `tests/test_cli.py` — FOUND
- `tests/test_hook.py` — FOUND
- `tests/test_hookutil.py` — FOUND
- `tests/fixtures/hook_events/{__init__,bash_rm_rf,write_file,read_file}` — FOUND
- Commit `70bae97` (test Task 1) — FOUND
- Commit `ad1e9ba` (feat Task 1) — FOUND
- Commit `8f2d93c` (test Task 2) — FOUND
- Commit `64d7ea3` (feat Task 2) — FOUND
- Commit `2205278` (test Task 3) — FOUND
- Commit `4e23ec7` (feat Task 3) — FOUND
- Full test suite: 215 tests pass (0 regressions)
