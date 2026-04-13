---
phase: 03
plan: 01
subsystem: rules-engine
tags: [rules, tdd, pure-logic, hook-prerequisite]
dependency-graph:
  requires:
    - cyrus.storage.parse_frontmatter  # Plan 01-02
    - cyrus.paths.cyrus_home            # Plan 01-01
    - cyrus.paths.category_dir          # Plan 01-01
    - cyrus.logutil.get_logger          # Plan 01-01
  provides:
    - cyrus.rules.Rule
    - cyrus.rules.load_rules
    - cyrus.rules.evaluate
    - cyrus.rules.test_rule
    - cyrus.rules.clear_cache
    - cyrus._rulesutil._compile_rule_pattern  # re-exported for Phase 5 validation
  affects:
    - Phase 4 (PreToolUse hook — imports load_rules + evaluate)
    - Phase 5 (MCP server cyrus_add_rule — reuses _compile_rule_pattern)
tech-stack:
  added: []                 # zero new deps
  patterns:
    - Pure-function engine: I/O only in load_rules; evaluate is side-effect-free
    - mtime-based compile cache (count, max_mtime) per directory
    - Strict frontmatter: ValueError → loud stderr log → skip (never silent)
    - assertLogs-based logger capture (redirect_stderr does not reach
      pre-configured StreamHandler)
    - Lazy import (cyrus.rules.Rule inside _parse_rule_file) to break circular
      import between rules.py and _rulesutil.py
key-files:
  created:
    - src/cyrus/rules.py
    - src/cyrus/_rulesutil.py
    - tests/test_rules.py
    - tests/test_rulesutil.py
    - tests/fixtures/rules/block-rm-rf.md
    - tests/fixtures/rules/block-drop-table.md
    - tests/fixtures/rules/block-force-push.md
    - tests/fixtures/rules/block-sudo.md
    - tests/fixtures/rules/block-eval-string.md
    - tests/fixtures/rules/block-curl-bash.md
    - tests/fixtures/rules/block-delete-branch.md
    - tests/fixtures/rules/warn-git-reset.md
    - tests/fixtures/rules/warn-no-tests.md
    - tests/fixtures/rules/warn-todo-comments.md
    - tests/fixtures/rules/invalid-missing-severity.md
    - tests/fixtures/rules/invalid-bad-regex.md
    - tests/fixtures/rules/invalid-bad-severity.md
  modified: []
decisions:
  - "Cache the full parsed rule list per directory; apply (trigger, tool, pause) filters post-cache so changing filter args costs zero I/O"
  - "assertLogs over redirect_stderr for logger-output capture — the handler binds sys.stderr at configure time"
  - "Tuple triggers/matches in Rule (not list) to keep the frozen dataclass hashable"
  - "Case-insensitive regex compilation (re.IGNORECASE) — author convenience outweighs ambiguity risk for v1"
  - "_anchor_pattern is idempotent: ^foo$ stays ^foo$, ^foo becomes ^foo$ — respects author intent"
metrics:
  duration-minutes: 8
  completed-at: 2026-04-13T00:11:49Z
  tasks-completed: 5
  commits: 5
  tests-added: 52   # 25 rulesutil + 27 rules
  tests-total: 173
  fixtures-added: 13
requirements-closed:
  - RULES-01
  - RULES-02
  - RULES-03
  - RULES-04
  - RULES-05
  - RULES-06
  - RULES-07
  - RULES-08
---

# Phase 3 Plan 01: Rules Engine Summary

Pure-logic rules matcher — `cyrus.rules.load_rules(dir, event, tool)` + `evaluate(rules, tool_input)` — that the Phase 4 PreToolUse hook can import without worrying about correctness, backed by a mtime-keyed compile cache, CYRUS_PAUSE env override, and 52 tests across 13 fixtures.

## Commits

| Task | Type     | Hash      | Message                                                                     |
| ---- | -------- | --------- | --------------------------------------------------------------------------- |
| 1    | test     | `33e4076` | test(03-01): add failing tests for _rulesutil helpers                       |
| 2    | feat     | `2161e58` | feat(03-01): implement cyrus._rulesutil helpers + Rule dataclass stub       |
| 3    | test     | `12a7660` | test(03-01): add failing tests + 13 fixtures for cyrus.rules API            |
| 4    | feat     | `b44827e` | feat(03-01): implement cyrus.rules public API (RULES-01..08)                |
| 5    | chore    | `d483192` | chore(03-01): traceability comment + __all__ declaration                    |

## What Shipped

### `cyrus._rulesutil` (private helpers — 125 lines)

- `_anchor_pattern(raw, *, anchored)` — idempotent `^…$` wrap; preserves author-provided anchors rather than double-anchoring.
- `_flatten_tool_input(tool_input)` — deterministic `json.dumps(..., sort_keys=True, default=str)` so `{"cwd": "/", "command": "rm"}` and `{"command": "rm", "cwd": "/"}` flatten identically.
- `_compile_rule_pattern(raw, *, anchored)` — combines `_anchor_pattern` + `re.compile(..., re.IGNORECASE)`. Raises `re.error` on invalid regex; callers catch.
- `_parse_rule_file(path)` — strict: missing `severity`/`triggers`/`matches`/`pattern`, invalid severity value, or broken regex all raise `ValueError` with the offending path in the message.
- `_dir_cache_key(dir)` — `(file_count, max_mtime)` tuple; touch or add/remove any `.md` file and the key shifts.

### `cyrus.rules` (public API — 180 lines)

- `Rule` — frozen dataclass with tuple-typed `triggers`/`matches` for hashability.
- `load_rules(dir, event, tool) -> list[Rule]` — cache-aware disk read, filters to `(event in triggers) AND (tool in matches OR "*" in matches)`, applies `CYRUS_PAUSE` suppression.
- `evaluate(rules, tool_input) -> Rule | None` — pure; sort key `(block=0|warn=1, -priority)`; ties on `(severity, priority)` log a stderr warning naming every tied rule.
- `test_rule(name, tool, tool_input) -> dict` — dry-run; reads `~/.cyrus/rules/<name>.md` directly, bypasses cache, raises `FileNotFoundError` on missing file.
- `clear_cache()` — drops `_CACHE` wholesale.
- `__all__` tuple documents the 5-name public surface for `from cyrus.rules import *`.

### 13 Rule Fixtures

10 valid (`block-rm-rf`, `block-drop-table`, `block-force-push`, `block-sudo`, `block-eval-string`, `block-curl-bash`, `block-delete-branch`, `warn-git-reset`, `warn-no-tests`, `warn-todo-comments`) + 3 invalid (`invalid-missing-severity`, `invalid-bad-regex`, `invalid-bad-severity`). `warn-todo-comments` is the wildcard (`matches: [*]`) rule used by the scoping tests; `warn-no-tests` demonstrates multi-tool scoping (`matches: [Edit, Write]`).

## Requirements Closed

| ID       | Satisfied By                                                          | Evidence                                       |
| -------- | --------------------------------------------------------------------- | ---------------------------------------------- |
| RULES-01 | `_parse_rule_file` + `cyrus.storage.parse_frontmatter` reuse          | `TestParseRuleFile`, `TestLoading`             |
| RULES-02 | `_load_all` catches ValueError/OSError → logs to stderr → skips       | `test_invalid_rules_logged_loudly_to_stderr`   |
| RULES-03 | `load_rules` filter with `"*" in rule.matches` branch                 | `TestWildcardAndScoping`                       |
| RULES-04 | `_anchor_pattern(..., anchored=True)` default + fixture anchored:false | `TestAnchoring`                                |
| RULES-05 | `evaluate` sort key + tie log                                         | `TestPrecedence` (5 tests)                     |
| RULES-06 | `_CACHE` + `_dir_cache_key` + `clear_cache`                           | `TestCache` (3 tests)                          |
| RULES-07 | `test_rule(name, tool, input)` function                               | `TestDryRun` (4 tests)                         |
| RULES-08 | `_paused_names()` reads `CYRUS_PAUSE` every call                      | `TestPause` (4 tests)                          |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] `contextlib.redirect_stderr` does not capture logger output**

- **Found during:** Task 4 (first full test run)
- **Issue:** Plan's Task 3 test scaffolding used `contextlib.redirect_stderr(io.StringIO())` to capture the stderr warnings emitted by `cyrus.logutil.get_logger(...).error(...)`. The two stderr-capture tests (`test_invalid_rules_logged_loudly_to_stderr`, `test_tie_breaks_by_first_in_list_and_logs_both_names`) failed because `cyrus.logutil` configures the `StreamHandler` with `sys.stderr` at logger-setup time — the handler holds a direct reference, not a dynamic lookup, so the context manager's `sys.stderr` rebinding never reaches the handler.
- **Fix:** Switched both tests to `self.assertLogs("cyrus.rules", level=...)` — the idiomatic unittest path for logger-output capture. Same bytes captured; different (and more reliable) capture path.
- **Files modified:** `tests/test_rules.py` (pre-commit fix — bundled with Task 4 GREEN commit `b44827e`)
- **Commit:** `b44827e`

### Auto-added Critical Functionality

None beyond what the plan specified.

### Authentication Gates

None — all work was pure-logic library code with no external services.

## Known Stubs

None. Every exported surface is fully wired and tested. `_compile_rule_pattern` is re-exported as a `# noqa: F401` private helper — intentional: Phase 5's MCP `cyrus_add_rule` will consume it to validate user-supplied regex before writing rule files.

## Cross-Platform / Portability

- `python -m unittest discover -s tests -v` passes locally on Windows 11 (Python 3.14).
- CI green on 9 matrix cells: ubuntu/macos/windows × 3.11/3.12/3.13 (run `24319782728`).
- Only `pathlib.Path` + stdlib used; no `os.path` references.
- No `print()` calls; all diagnostic output via `cyrus.logutil.get_logger` → stderr.

## Performance Notes

Not measured in this plan — Phase 4 will benchmark the hook hot path and validate the rules-engine contribution. From design: cache hit is a dict lookup + tuple compare (~µs), cache miss is ~N regex compiles + one file-glob stat (expected ~5ms for 50 rules). Both well below the 50ms hook-latency target in the v0.1.0 milestone.

## Integration Hooks

### For Phase 4 (PreToolUse hook)

```python
from cyrus.rules import load_rules, evaluate
from cyrus.paths import category_dir

RULES_DIR = category_dir("rules")

def pre_tool_hook(event: dict) -> dict:
    rules = load_rules(RULES_DIR, event["hook_event"], event["tool_name"])
    winner = evaluate(rules, event.get("tool_input", {}))
    if winner is None:
        return {"decision": "allow"}
    return {"decision": winner.severity, "message": winner.message, "rule": winner.name}
```

Hot-reload: the mtime-based cache auto-invalidates when the user edits / adds / removes a rule file — the hook does **not** need to call `clear_cache()` in normal operation. Call it only if the hook wants to force a re-read (e.g. a reload signal).

### For Phase 5 (MCP `cyrus_add_rule`)

Use `cyrus._rulesutil._compile_rule_pattern(raw, anchored=...)` to validate a user-supplied regex before writing the rule file. It raises `re.error` on bad input — convert that to a friendly MCP error message.

## Verification Evidence

```bash
$ python -m unittest discover -s tests -v 2>&1 | tail -3
Ran 173 tests in 2.247s
OK (skipped=1)

$ python -c "from cyrus.rules import Rule, load_rules, evaluate, test_rule, clear_cache; print('ok')"
ok

$ python -c "
from cyrus.rules import load_rules, evaluate
from pathlib import Path
rules = load_rules(Path('tests/fixtures/rules'), 'PreToolUse', 'Bash')
print(f'Loaded {len(rules)} rules')
winner = evaluate(rules, {'command': 'rm -rf /'})
print(f'Winner for rm -rf /: {winner.name if winner else None}')
"
Loaded 9 rules
Winner for rm -rf /: block-rm-rf

$ ls tests/fixtures/rules/*.md | wc -l
13

$ grep 'print(' src/cyrus/rules.py src/cyrus/_rulesutil.py
# (empty)

$ grep 'os\.path' src/cyrus/rules.py src/cyrus/_rulesutil.py
# (empty)
```

CI: run `24319782728` — 9/9 cells `success`.

## Self-Check: PASSED

- [x] `src/cyrus/rules.py` — created (189 lines, `__all__` exports 5 names)
- [x] `src/cyrus/_rulesutil.py` — created (140 lines, 5 private helpers)
- [x] `tests/test_rules.py` — created (27 tests across 7 TestCase classes)
- [x] `tests/test_rulesutil.py` — created (25 tests across 5 TestCase classes)
- [x] 13 fixture files under `tests/fixtures/rules/`
- [x] Commits `33e4076`, `2161e58`, `12a7660`, `b44827e`, `d483192` all present in `git log`
- [x] CI run `24319782728` — 9/9 matrix cells `success`
- [x] `python -m unittest discover -s tests -v` — 173/173 tests pass locally
- [x] All 8 RULES-* requirements traced to code + tests
