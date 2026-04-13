---
phase: 06-cli-install
plan: 01
subsystem: cli
tags: [argparse, install, diagnostics, rules, ascii]

# Dependency graph
requires:
  - phase: 01-storage-foundation
    provides: atomic_write, filelock, dump_frontmatter
  - phase: 03-rules-engine
    provides: _parse_rule_file, _compile_rule_pattern
  - phase: 04-pretool-hook
    provides: check_kill_switch, marker_path, hook-errors.log contract
  - phase: 05-mcp-server
    provides: cyrus serve (used by doctor's MCP canary)
provides:
  - cyrus init (CLI-01 + CLI-02 idempotent install)
  - cyrus doctor (CLI-03 7-check diagnostic + --json mode)
  - cyrus add-rule (CLI-04 flag-driven rule writer with regex validation)
  - cyrus list-rules (CLI-05 ASCII table with BROKEN flagging)
  - _cliutil module (format_table, merge_claude_settings, backup_file, write_json_atomic, say)
  - ASCII-only output discipline (CLI-07)
affects:
  - Phase 06-02 (install-test job will run `cyrus init` + `cyrus doctor` on fresh VMs)
  - Phase 07 (release) gates on these commands existing and being green in CI

# Tech tracking
tech-stack:
  added: []  # stdlib only -- no new runtime dependencies
  patterns:
    - "ASCII-only CLI output with + | - ASCII table dividers, cp1252-safe on Windows"
    - "Idempotent settings.json merge via deep-copy + nested-hook scan"
    - "Timestamped .bak file creation before any destructive write"
    - "Each new CLI command split into cyrus._<name> module for testability; cli.py stays a thin argparse router"

key-files:
  created:
    - src/cyrus/_cliutil.py (ASCII table + settings merge + atomic JSON + say)
    - src/cyrus/_init.py (cyrus init implementation)
    - src/cyrus/_doctor.py (cyrus doctor: 7 checks + --json)
    - tests/test_cliutil.py (19 tests)
    - tests/test_init.py (11 tests)
    - tests/test_doctor.py (13 tests)
    - tests/test_addrule.py (7 tests)
    - tests/test_listrules.py (5 tests)
  modified:
    - src/cyrus/cli.py (added init, doctor, add-rule, list-rules subparsers + ASCII cleanup)

key-decisions:
  - "Split each Phase 6 subcommand into cyrus._<name> private module so cli.py stays a lazy-import router and tests can drive runs without touching argparse"
  - "merge_claude_settings uses copy.deepcopy and scans every nested hooks[*].command -- never mutates the user's dict"
  - "cyrus init writes backup BEFORE merge, only when the file already exists -- missing-file case is not a backup candidate"
  - "cyrus doctor recent_hook_errors is informational (ok=True with count) rather than a hard fail -- surfacing errors matters more than failing the install"
  - "add-rule validates regex via _rulesutil._compile_rule_pattern BEFORE any filesystem write so a bad pattern leaves zero side effects"
  - "list-rules flags BROKEN rules in the output table but exits 0 -- the whole point is to surface the mess for the user to fix"
  - "cli.py pre-existing em-dashes replaced with `--` to satisfy CLI-07 ASCII purity (Rule 2 deviation)"

patterns-established:
  - "Every new cyrus CLI command: module cyrus._<cmd>.run(argv) called from cli.py via lazy import"
  - "ASCII-only source: scrub em-dashes (U+2014) and smart quotes on the way in; grep -nP '[^\\x00-\\x7F]' in CI"
  - "CLI tests: tempdir + CYRUS_HOME env patch + patch.object(Path, 'home', return_value=...) to avoid scribbling on the developer's ~/.claude"

requirements-completed: [CLI-01, CLI-02, CLI-03, CLI-04, CLI-05, CLI-07]

# Metrics
duration: ~25min
completed: 2026-04-12
---

# Phase 06 Plan 01: CLI Core (init/doctor/add-rule/list-rules) Summary

**Zero-friction install path: `cyrus init` + `cyrus doctor` + `cyrus add-rule` + `cyrus list-rules` with idempotent settings.json merge, 7-check diagnostic, regex-validated rule creation, and ASCII-only output for Windows cp1252 compatibility**

## Performance

- **Duration:** ~25 min
- **Tasks:** 4 (all TDD pairs, 8 commits of test/feat pattern)
- **New tests:** 55 (19 cliutil + 11 init + 13 doctor + 7 addrule + 5 listrules)
- **Full suite:** 337 tests pass (up from 282 baseline)
- **Files created:** 8 (3 source, 5 test modules)
- **Files modified:** 1 (src/cyrus/cli.py)

## Accomplishments

- `cyrus init` creates ~/.cyrus/ tree, writes default config.json, merges PreToolUse hook into ~/.claude/settings.json with timestamped backup; idempotent second run leaves exactly one cyrus hook entry.
- `cyrus doctor` runs 7 diagnostic checks (python_version, cyrus_on_path, cyrus_home_writable, settings_hook_registered, mcp_canary, kill_switch, recent_hook_errors) with ASCII `[OK]/[FAIL]` output and `--json` mode for CI consumption.
- `cyrus add-rule` validates slug-style names, compiles regex before any filesystem write, refuses name collisions, writes frontmatter via the existing storage.dump_frontmatter + atomic_write pair.
- `cyrus list-rules` prints an ASCII table (NAME/SEVERITY/MATCHES/PATTERN/STATUS) with `+-|` box drawing; broken rules get STATUS=BROKEN without failing the command.
- Shared `_cliutil` module ships format_table, merge_claude_settings, backup_file, write_json_atomic, say -- ASCII-pure, stdlib-only, used by init + list-rules.

## Task Commits

Each task was a TDD pair (test → feat):

1. **Task 1: _cliutil helpers**
   - `7854a95` test(06-01): add failing tests for _cliutil
   - `1ef256f` feat(06-01): add _cliutil helpers (ASCII table, settings merge, atomic JSON write)

2. **Task 2: cyrus init**
   - `1e83b54` test(06-01): add failing tests for cyrus init
   - `1e08146` feat(06-01): add cyrus init (CLI-01, CLI-02)

3. **Task 3: cyrus doctor**
   - `eef8471` test(06-01): add failing tests for cyrus doctor
   - `cfbc1a8` feat(06-01): add cyrus doctor with 7 checks + --json mode (CLI-03, CLI-07)

4. **Task 4: cyrus add-rule + list-rules**
   - `5eb0fde` test(06-01): add failing tests for add-rule and list-rules
   - `8483472` feat(06-01): add cyrus add-rule and list-rules (CLI-04, CLI-05)

## Files Created/Modified

**Created:**
- `src/cyrus/_cliutil.py` (219 lines) -- format_table, merge_claude_settings, backup_file, write_json_atomic, say
- `src/cyrus/_init.py` (114 lines) -- run(argv) for `cyrus init`; mkdir tree, config.json, settings.json merge
- `src/cyrus/_doctor.py` (283 lines) -- collect_checks(), _mcp_canary(), CheckResult dataclass, run(argv)
- `tests/test_cliutil.py` (224 lines, 19 tests)
- `tests/test_init.py` (211 lines, 11 tests)
- `tests/test_doctor.py` (251 lines, 13 tests)
- `tests/test_addrule.py` (166 lines, 7 tests)
- `tests/test_listrules.py` (119 lines, 5 tests)

**Modified:**
- `src/cyrus/cli.py` -- added init/doctor/add-rule/list-rules subparsers and dispatch branches; added `_cmd_add_rule` and `_cmd_list_rules` helpers; replaced pre-existing em-dashes with ASCII equivalents.

## Decisions Made

- **Each subcommand lives in its own cyrus._<name> module** (not inside cli.py). Keeps cli.py a thin argparse router with lazy imports so `cyrus hook run` cold-start stays fast. Also makes tests drive `_init.run([])` directly without re-parsing argparse trees.
- **merge_claude_settings deep-copies on entry.** Never mutates the user's dict, even on the idempotent (changed=False) path. Test-enforced via `self.assertEqual(existing, original_deepcopy)`.
- **Backup is gated on file existence.** If `~/.claude/settings.json` doesn't exist, no `.bak` file is created -- nothing to back up. Test: `test_handles_missing_claude_dir`.
- **doctor's recent_hook_errors never hard-fails.** A 24h error count is informational; surfacing it matters more than refusing to call the install healthy. Kill-switch is the authoritative "something is wrong" signal.
- **add-rule validates regex before touching the filesystem.** `_compile_rule_pattern(pattern, anchored=...)` raises; we catch, write stderr, exit 2, leave disk untouched. Test: `test_invalid_regex_rejected`.
- **list-rules flags broken rules with STATUS=BROKEN.** Exit 0 because the whole point is to surface problems. Row detail is the exception string truncated to 40 chars.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] Scrubbed pre-existing em-dashes from src/cyrus/cli.py**

- **Found during:** Task 2 (after implementing `_init.py` the Task 1+2 files were ASCII-clean, but `grep -nP "[^\x00-\x7F]" src/cyrus/cli.py` returned 6 matches on pre-existing comment/description lines from Phases 4 and 5).
- **Issue:** CLI-07 requires ASCII-only output from new CLI files. The success criteria explicitly grep all four files including cli.py. Pre-existing em-dashes in docstrings and description strings would have caused the final ASCII check to fail.
- **Fix:** Replaced every em-dash (`U+2014`) in cli.py with ASCII `--` or `;` depending on context. The `description=` string users see from `--help` now reads `"Cyrus -- AI memory system with hook-level rules enforcement"`.
- **Files modified:** `src/cyrus/cli.py`
- **Verification:** `python -c "import re; ... grep r'[^\x00-\x7F]' ..."` returns zero matches across all 4 files (_cliutil.py, _init.py, _doctor.py, cli.py).
- **Committed in:** `1e08146` (Task 2 commit, same feature commit -- the ASCII cleanup was required for Task 2 to meet its own acceptance criteria).

---

**Total deviations:** 1 auto-fixed (Rule 2: missing critical for CLI-07 compliance).
**Impact on plan:** Zero. The plan's acceptance criteria demanded this; the only question was whether the scrub happened during Task 2 (when the ASCII grep first mattered) or later. Doing it inline was the lowest-scope option.

## Issues Encountered

- **python-3.14 plus Python 3.11+ check.** Initial concern: does doctor's `python_version` check pass on the Claude Code test runner? The runner here is 3.14.3, which satisfies `(3, 11) <=`. CI will verify on 3.11 / 3.12 / 3.13 matrix cells.
- **Subprocess smoke test surfaced that `USERPROFILE` (not `HOME`) is what Python's `Path.home()` reads on Windows.** Our unit tests patch `pathlib.Path.home` directly so this is a smoke-test-only concern, but it's worth noting for Plan 06-02's fresh-VM install test: on Windows we must set `USERPROFILE` too, not just `HOME`.
- **First smoke run wrote into the developer's real `C:\Users\mohab\.claude\settings.json`** because bash `HOME=` doesn't override `USERPROFILE`. The merge was idempotent and a timestamped backup was created alongside; user's prior settings are recoverable. Second smoke run used the proper `USERPROFILE` override and was fully isolated.

## Verification

Final checks run before final commit:

- `python -m unittest discover -s tests`: **337 tests pass** (3 skipped), up from 282 baseline. Zero regressions.
- `grep -nP "[^\x00-\x7F]"` on all four new/modified source files: zero matches, ASCII-only.
- Smoke test in isolated tempdir:
  - `cyrus init` creates `.cyrus/` with 5 category subdirs + config.json.
  - Second `cyrus init` is idempotent: cyrus hook count stays at 1.
  - `cyrus doctor` runs all 7 checks with `[OK]/[FAIL]` prefixes.
  - `cyrus doctor --json` emits parseable JSON with `checks` and `all_ok` keys.
  - `cyrus add-rule --name test-rule --severity warn --matches Bash --pattern abc --message test` succeeds; file appears in rules dir.
  - `cyrus list-rules` renders an ASCII table with the created rule.

## User Setup Required

None -- Phase 6 Plan 01 is the install machinery itself.

## Next Phase Readiness

**Phase 06 Plan 02 (install-test) ready:** the four commands and their exit codes are stable, so the CI matrix cell can do `pip install -e . && cyrus init && cyrus doctor && echo "$?" | grep -q 0-or-1` on Windows/macOS/Linux.

**Phase 07 (release) requires these commands exist** so the README install section actually works as written.

**Known issue carried forward:** doctor's `cyrus_on_path` check uses `shutil.which("cyrus")`. When running via `python -m cyrus.cli` the shim binary may not be on PATH -- doctor will report `[FAIL] cyrus_on_path` in that case. This is correct behavior (the user needs `cyrus` on PATH to run the install instructions), but Plan 06-02 needs to ensure the pip-install puts the shim somewhere PATH resolves on every OS.

## Self-Check: PASSED

All files created exist on disk:
- src/cyrus/_cliutil.py: FOUND
- src/cyrus/_init.py: FOUND
- src/cyrus/_doctor.py: FOUND
- tests/test_cliutil.py: FOUND
- tests/test_init.py: FOUND
- tests/test_doctor.py: FOUND
- tests/test_addrule.py: FOUND
- tests/test_listrules.py: FOUND

All task commits exist in git log:
- 7854a95, 1ef256f: FOUND (Task 1)
- 1e83b54, 1e08146: FOUND (Task 2)
- eef8471, cfbc1a8: FOUND (Task 3)
- 5eb0fde, 8483472: FOUND (Task 4)

---
*Phase: 06-cli-install*
*Completed: 2026-04-12*
