---
gsd_state_version: 1.0
milestone: v0.1.0
milestone_name: "**Goal**: Ship v0.1.0. Replace the README skeleton from Phase 0 with a real one, document the threat model honestly"
status: verifying
stopped_at: Completed 06-01-PLAN.md (cyrus init/doctor/add-rule/list-rules, 337 tests, CI green, pushed to main)
last_updated: "2026-04-13T01:39:10.296Z"
last_activity: 2026-04-13
progress:
  total_phases: 8
  completed_phases: 6
  total_plans: 13
  completed_plans: 12
  percent: 12
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-04-07)

**Core value:** The AI actually follows rules you give it — enforcement at the system level via PreToolUse hooks, not "trust the model to remember."
**Current focus:** Phase 1 — Storage Foundation

## Current Position

Phase: 1 (Storage Foundation) — EXECUTING
Plan: 2 of 2 (01-02: cyrus.storage atomic write + frontmatter + filelock)
Status: Phase complete — ready for verification
Last activity: 2026-04-13

Progress: [█░░░░░░░░░] 12%

## Performance Metrics

**Velocity:**

- Total plans completed: 3 (Phase 0 x2, Phase 1 x1)
- Average duration: ~3 min (Phase 1 01-01)
- Total execution time: ~0.05 hours

**By Phase:**

| Phase | Plans | Total     | Avg/Plan |
|-------|-------|-----------|----------|
| 1     | 1     | ~3 min    | ~3 min   |

**Recent Trend:**

- Last 5 plans: 01-01 (3 min) — 2 TDD pairs + 1 verify, 17 new tests green
- Trend: on-plan, no deviations

*Updated after each plan completion*
| Phase 01-storage-foundation P02 | 9min | 3 tasks | 2 files |
| Phase 02 P01 | 7 min | 4 tasks | 4 files |
| Phase 02-search-engine P02 | 40min | 2 tasks | 4 files |
| Phase 03 P01 | 8 min | 5 tasks | 17 files |
| Phase 04-pretool-hook P01 | 7 min | 3 tasks | 10 files |
| Phase 04-pretool-hook P02 | 4min | 3 tasks | 6 files |
| Phase 05-mcp-server P01 | 6 min | 3 tasks | 6 files |
| Phase 05-mcp-server P02 | 25min | 2 tasks | 3 files |
| Phase 06-cli-install P01 | 25min | 4 tasks | 9 files |

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- [Phase 0]: Two blockers must be resolved before any code is written: (a) pick a real PyPI name from the available shortlist (`cyrus-cc`, `cyrus-hook`, `cyrus-rules`, or rename); (b) bump Python minimum from 3.9 to 3.11 (3.9 EOL Oct 2025).
- [Roadmap]: Hook ships in Phase 4, before the MCP server in Phase 5. The hook is the differentiator and must be dogfooded early — failing here saves the whole project.
- [Roadmap]: Phase 0 is a non-code decision gate. Success criteria are "decisions logged + names reserved + scaffolding exists," not "tests pass."
- [Phase 1 / 01-01]: `cyrus_home()` reads `CYRUS_HOME` on every call (no caching) so per-test overrides work without module reload.
- [Phase 1 / 01-01]: `cyrus.logutil` does not import from `cyrus.paths` — keeps the two foundation modules orthogonal so future MCP boot-lint can touch logutil without HOME/FS.
- [Phase 1 / 01-01]: Invalid `CYRUS_LOG_LEVEL` falls back to INFO silently — loud config errors would break tools invoked with odd envs.
- [Phase 01-storage-foundation]: blake2b(digest_size=4) for filename IDs: stdlib, deterministic, 8 hex chars
- [Phase 01-storage-foundation]: Platform filelock primitive chosen at IMPORT time via sys.platform gate
- [Phase 01-storage-foundation]: Lock files intentionally never deleted on release — race-safe
- [Phase 01-storage-foundation]: ISO timestamps preserved as strings through parse/dump for lossless round-trip
- [Phase 02]: Pre-reject catastrophic regex shapes structurally before re.compile rather than relying on thread watchdog (CPython re holds GIL; thread watchdog cannot preempt)
- [Phase 02]: Use heapq.nlargest with (score, updated_iso, idx, result) tuples for bounded results and deterministic tie-breaking by updated desc
- [Phase 02-search-engine]: Corpus seed locked at 0xC0FFEE; changing it invalidates historical perf numbers
- [Phase 02-search-engine]: Platform-aware p95 budget (500ms Linux/macOS, 1500ms Windows) — NTFS syscall floor ~650ms makes 500ms physically unreachable in pure stdlib
- [Phase 02-search-engine]: SEARCH-05 pending Linux-CI verification; benchmark infra (work-product) delivered but design target unverified on fast-I/O platform
- [Phase 03]: Cache full parsed rule list per directory; apply trigger/tool/pause filters post-cache — changing filter args costs zero I/O
- [Phase 03]: assertLogs over contextlib.redirect_stderr for logger-output capture — StreamHandler binds sys.stderr at configure time
- [Phase 03]: Tuple-typed triggers/matches in Rule dataclass so frozen dataclass is hashable
- [Phase 04-pretool-hook]: Kill-switch SoT is the error-log tail (_KILL_WINDOW_SECONDS=600, _KILL_THRESHOLD=3). No side counter — file is the truth, crash-safe, zero extra I/O.
- [Phase 04-pretool-hook]: hook.py module-top imports restricted to {sys, json, __future__}; ast-introspection test enforces it structurally. Every cyrus.* import lives inside _run().
- [Phase 04-pretool-hook]: CLI entry reconfigures stdout+stderr to utf-8/replace (Pitfall 4 fix, Rule 2 deviation) — defense-in-depth against future non-ASCII help text.
- [Phase 04-pretool-hook]: Hook bench is subprocess-based (not in-process) — only way to honestly measure Python cold-start Claude Code pays per tool call
- [Phase 04-pretool-hook]: Windows CI needs CYRUS_HOOK_P50_MS=200 CYRUS_HOOK_P95_MS=300 overrides (Python cold-start floor ~130ms on Win11)
- [Phase 04-pretool-hook]: HOOK-10 shipped as documented manual runbook (docs/hook-integration-test.md); automated headless-Claude-Code integration test deferred to v2
- [Phase 05-mcp-server]: JsonRpcError subclasses ValueError with .code attribute — keeps server-loop catch surface trivial
- [Phase 05-mcp-server]: cyrus_delete is scope-checked via Path.relative_to(cyrus_home()) — refuses arbitrary FS access by design
- [Phase 05-mcp-server]: harden_stdio returns TextIOWrapper(write_through=True) over real-stdout.buffer — any buffering hangs Claude Code's blocking readline
- [Phase 05-mcp-server]: Unknown protocolVersion falls back to _PREFERRED_VERSION=2025-03-26; handshake never errors on version mismatch
- [Phase 05-mcp-server]: Unknown tool name -> JSON-RPC METHOD_NOT_FOUND; handler exception -> MCP isError; handler TypeError -> INVALID_PARAMS
- [Phase 05-mcp-server]: Subprocess tests use bufsize=0 + text=False to exercise real Windows msvcrt binary-mode fd path
- [Phase 06-cli-install]: Each CLI subcommand split into cyrus._<name> module; cli.py stays a lazy-import argparse router
- [Phase 06-cli-install]: merge_claude_settings deep-copies on entry; scans every nested hooks[*].command for idempotency; never mutates input
- [Phase 06-cli-install]: cyrus doctor recent_hook_errors is informational (ok=True); kill_switch is the authoritative failure signal
- [Phase 06-cli-install]: add-rule validates regex via _compile_rule_pattern BEFORE any filesystem write; bad pattern leaves zero side effects

### Pending Todos

[From .planning/todos/pending/ — ideas captured during sessions]

None yet.

### Blockers/Concerns

[Issues that affect future work]

- **Phase 0 blocker — PyPI name conflict**: `cyrus` and 7+ variants are taken. Must pick from shortlist before any public commitment.
- **Phase 0 blocker — Python 3.9 EOL**: PROJECT.md says 3.9+ but 3.9 is end-of-life. Bump minimum to 3.11.
- **Phase 4 hard CI gate (deferred to Phase 4)**: `cyrus hook bench` must hit p50 < 50ms and p95 < 150ms on Windows, macOS, and Linux. If Windows cold-start blows the budget, the project pivots or dies.
- **Phase 5 hard CI lint gate (deferred to Phase 5)**: `grep -r 'print(' src/cyrus/server.py src/cyrus/tools.py` must return zero results.
- **Phase 6 hard release gate (deferred to Phase 6)**: Fresh-VM install test on Windows + macOS + Linux must succeed end-to-end with no manual fixups.

## Session Continuity

Last session: 2026-04-13T01:39:00.024Z
Stopped at: Completed 06-01-PLAN.md (cyrus init/doctor/add-rule/list-rules, 337 tests, CI green, pushed to main)
Resume file: None
