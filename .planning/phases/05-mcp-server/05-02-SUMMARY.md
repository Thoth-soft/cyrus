---
phase: 05-mcp-server
plan: 02
subsystem: mcp-server
tags: [mcp, jsonrpc, stdio, server, cli, subprocess-tests, tdd]
requires:
  - sekha.jsonrpc (Plan 05-01: parse/emit/harden_stdio/error codes)
  - sekha.schemas (Plan 05-01: TOOLS list)
  - sekha.tools   (Plan 05-01: HANDLERS dispatch table)
  - sekha.cli     (Phase 4: argparse router with `hook` subcommand)
provides:
  - sekha.server.handle_request (pure JSON-RPC dispatcher)
  - sekha.server.main (long-lived stdio loop)
  - sekha serve (CLI subcommand — registered in pyproject console_scripts)
affects:
  - src/sekha/server.py (created)
  - src/sekha/cli.py (modified — `serve` subparser + lazy dispatch)
  - tests/test_server.py (created — 22 tests: 14 unit + 8 subprocess)
tech-stack:
  added: []
  patterns:
    - "Lazy heavy-import policy — sekha.tools/.schemas lazy-imported inside _tools_*() helpers so harden_stdio runs first in main()"
    - "Pure-function dispatcher — handle_request(dict) -> dict|None — testable without subprocess spin-up"
    - "Subprocess integration tests over binary pipes (bufsize=0) — catch stdout-buffering + Windows-CRLF regressions real unit tests miss"
    - "threading.Timer watchdog per subprocess read — hung readlines fail fast instead of wedging CI"
key-files:
  created:
    - src/sekha/server.py
    - tests/test_server.py
  modified:
    - src/sekha/cli.py
decisions:
  - "Unknown protocolVersion falls back to _PREFERRED_VERSION=2025-03-26 (client sends '9999-01-01' -> server echoes '2025-03-26'); handshake NEVER returns a JSON-RPC error on version-mismatch — Claude Code tolerates echo-back of a version it doesn't know"
  - "Unknown tool name -> JSON-RPC METHOD_NOT_FOUND (-32601) error, NOT MCP isError payload — per spec, tools/call is-not-a-tool is a hard JSON-RPC error so Claude Code can invalidate its cached tools list"
  - "Handler runtime exceptions -> MCP-style {content, isError: true} payload (spec-compliant), handler TypeError (bad kwargs) -> JSON-RPC INVALID_PARAMS (-32602) so arg-shape bugs round-trip cleanly"
  - "Lazy imports: sekha.tools/.schemas imported inside _tools_list/_tools_call only — keeps the window between main() start and harden_stdio() impossibly small"
  - "Subprocess tests use bufsize=0 + text=False on pipes — exercises the real msvcrt.setmode binary path on Windows, not a Python text-wrapper shortcut"
  - "threading.Timer watchdog (8s read timeout, 5s shutdown timeout) — a hung server surfaces as AssertionError with stderr drain, not a wedged CI job"
metrics:
  duration: "~25min (including RED/GREEN for both tasks, CI wait, smoke tests)"
  completed: 2026-04-13
---

# Phase 5 Plan 02: MCP Server Main Loop + `sekha serve` CLI + Subprocess Integration Tests Summary

**One-liner:** Long-lived MCP stdio JSON-RPC 2.0 server at `sekha.server` wired into CLI as `sekha serve`, validated by 22 tests including 8 subprocess integration tests that spawn real `python -m sekha.cli serve` processes to prove stdout-pollution survival, protocol-version negotiation across three versions, and clean shutdown on stdin EOF.

## What Landed

### `src/sekha/server.py` (293 lines)

- `handle_request(request: dict) -> dict | None` — pure dispatcher over
  JSON-RPC dicts. Routes `initialize`, `notifications/initialized`,
  `notifications/cancelled`, `tools/list`, `tools/call`, `ping` and a
  METHOD_NOT_FOUND fall-through for anything else (e.g. `prompts/list`,
  `resources/list`). Never raises — every error path returns a
  well-formed JSON-RPC response or None for notifications.
- `_initialize(params)` — echoes `protocolVersion` back when in
  `ACCEPTED_PROTOCOL_VERSIONS` = `{2025-11-25, 2025-03-26, 2024-11-05}`;
  otherwise falls back to `2025-03-26`. serverInfo reports
  `importlib.metadata.version("sekha")` or `0.0.0` in dev checkouts.
- `_tools_call(params)` — lazy-imports `sekha.tools.HANDLERS`, dispatches
  by name, wraps handler TypeError as INVALID_PARAMS and any other
  exception as MCP-style `{content, isError: true}`. Unknown tool name
  raises JsonRpcError(METHOD_NOT_FOUND).
- `main()` — calls `harden_stdio()` FIRST (before any sekha.tools /
  .schemas / .search / .storage import reaches the module because those
  are all lazy-imported inside the `_tools_*` helpers). Then blocks on
  stdin, parsing every non-blank line into a JSON-RPC request, and
  emitting responses through the protected real-stdout handle.
  Gracefully exits 0 on KeyboardInterrupt, BrokenPipeError, or EOF.

### `src/sekha/cli.py` (changes)

- `_build_parser()` now registers `sub.add_parser("serve", ...)`
  alongside the existing `hook` subparser tree.
- `main()` adds a `serve` dispatch branch that lazy-imports
  `sekha.server.main` so hook cold-start stays unaffected.

### `tests/test_server.py` (589 lines, 22 tests)

- `TestHandleRequest` (13 tests) — pure-function coverage of every
  method dispatch path, request-id preservation, INVALID_REQUEST on
  missing method, isError on handler exception, METHOD_NOT_FOUND on
  unknown tool / unknown method.
- `TestCli` (1 test) — confirms `_build_parser().parse_args(["serve"])`
  lands with `args.command == "serve"`.
- `TestServerSubprocess` (8 tests) — spawns real
  `python -m sekha.cli serve` subprocesses over binary pipes
  (`bufsize=0`, `text=False`) and drives full handshakes. Watchdog
  kills hung processes at 8s; clean shutdown verified at 5s.

## Phase 5 Exit Criteria — Verification Matrix

| Exit Criterion                                                | Verified By                                                                               |
| ------------------------------------------------------------- | ----------------------------------------------------------------------------------------- |
| Scripted JSON-RPC handshake into real server subprocess       | `test_full_handshake_plus_tools_list_plus_status`                                         |
| All 3 protocol versions accepted + echoed                     | `test_handshake_with_all_three_protocol_versions` (subTest per version)                   |
| 6 sekha_* tools discoverable via tools/list; each round-trips | `test_tools_list_returns_six_tools` + `test_full_handshake_plus_tools_list_plus_status` + Plan 05-01 `tests/test_tools.py` |
| HARD CI LINT GATE: no `print(` in server.py / tools.py / jsonrpc.py / schemas.py | `grep -rE "^\s*print\(" src/sekha/server.py src/sekha/tools.py src/sekha/jsonrpc.py src/sekha/schemas.py` returns zero |
| stdio hardening: stdout swapped to stderr, Windows binary + UTF-8 | Plan 05-01 `test_harden_stdio_survives_stray_print` + `test_stray_print_in_handler_does_not_corrupt_protocol_stream` |
| notifications/cancelled mid-call doesn't leak; ping round-trips | `test_notifications_cancelled_does_not_crash` + `test_ping_round_trip`                   |

## Manual Smoke Test (copy-paste ready for README/Phase 7)

```bash
(
  echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"test","version":"1"}}}'
  echo '{"jsonrpc":"2.0","method":"notifications/initialized"}'
  echo '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}'
) | python -m sekha.cli serve 2>/dev/null | head -1
```

Expected first-line output (single line, no wrapping, `version` may differ
in source checkouts that haven't been `pip install -e .`'d — `0.0.0`
fallback is expected):

```json
{"jsonrpc":"2.0","id":1,"result":{"protocolVersion":"2025-03-26","serverInfo":{"name":"sekha","version":"0.0.0"},"capabilities":{"tools":{}}}}
```

## Hard CI Lint Gate (for Phase 6 CI wiring)

```bash
grep -rE "^\s*print\(" src/sekha/server.py src/sekha/tools.py src/sekha/jsonrpc.py src/sekha/schemas.py
```

MUST exit non-zero (no matches found). Any `print(` at start of line
in those four files corrupts the MCP protocol channel. Wire this gate
into `.github/workflows/test.yml` in Phase 6.

## Subprocess-Test Quirks (Phase 6 doctor / Phase 7 threat-model feed)

- **Windows msvcrt.setmode is only reachable via real file descriptors.**
  The subprocess tests use `bufsize=0` + `text=False` specifically so the
  pipes are OS-level fds, not Python text wrappers. Tests using
  `io.BytesIO` would skip the binary-mode path entirely.
- **Windows handle release is strict.** `tearDown` explicitly closes
  `proc.stdin/stdout/stderr` before `TemporaryDirectory.cleanup()`;
  without that, Windows intermittently raises `PermissionError` on the
  tempdir teardown because the child still held handles. No such issue
  on Linux/macOS.
- **Shim subprocess for stray-print survival.** The killer test
  (`test_stray_print_in_handler_does_not_corrupt_protocol_stream`) cannot
  use `subprocess.Popen([sys.executable, "-m", "sekha.cli", "serve"])` +
  monkeypatching because the tests run in a different Python process.
  Instead it launches `[sys.executable, "-c", shim]` where the shim
  inline-monkeypatches `sekha.tools.HANDLERS["sekha_status"]` before
  calling `sekha.server.main()`. This keeps test code out of production
  (no `SEKHA_TEST_INJECT_PRINT` env var in server.py).
- **No test-skip needed for any platform.** All 22 tests pass on the
  Windows/macOS/Linux × Python 3.11/3.12/3.13 CI matrix (9 cells).

## Test Metrics

- **Before:** 260 tests (Plan 05-01 baseline, 0 failures)
- **After:** 282 tests (+22), 0 failures, 3 skipped (pre-existing
  environmental skips from other plans), runtime 4.0s locally on Windows

## CI Status (9-cell matrix)

All green as of commit `295f05b` (run id 24321161997):

- test (ubuntu-latest, 3.11)  ✓
- test (ubuntu-latest, 3.12)  ✓
- test (ubuntu-latest, 3.13)  ✓
- test (macos-latest, 3.11)   ✓
- test (macos-latest, 3.12)   ✓
- test (macos-latest, 3.13)   ✓
- test (windows-latest, 3.11) ✓
- test (windows-latest, 3.12) ✓
- test (windows-latest, 3.13) ✓

## Deviations from Plan

None — plan executed exactly as written. Task 1's server implementation
was correct on the first RED→GREEN cycle; Task 2's subprocess tests all
passed immediately with zero production-code changes needed in the GREEN
phase, which means the harden_stdio + lazy-import design from Plan 05-01
was already airtight. Commits reflect that: Task 2 has only a
`test(05-02):` commit, not a followup `feat(05-02):` bugfix.

## Commits

| Task | Type  | Message                                                           | Hash      |
| ---- | ----- | ----------------------------------------------------------------- | --------- |
| 1    | RED   | test(05-02): add failing unit tests for sekha.server.handle_request | `bd649b3` |
| 1    | GREEN | feat(05-02): implement sekha.server main loop + CLI serve subcommand | `d98da0c` |
| 2    | RED   | test(05-02): add subprocess integration tests for MCP handshake   | `295f05b` |
| 2    | GREEN | (no production changes required — Task 1 server already correct) | —         |

## Requirements Verified

- **MCP-01** — `sekha serve` entrypoint registered in CLI and dispatches
  to a long-lived `sekha.server.main()` stdio JSON-RPC loop. Verified by
  `test_cli_serve_subcommand_registered` + every `TestServerSubprocess`
  test that successfully completes a handshake.
- **MCP-02** — Three-protocol-version negotiation. Verified by
  `test_initialize_accepts_all_three_versions` (unit) +
  `test_handshake_with_all_three_protocol_versions` (subprocess).
- **MCP-11** — Hard CI lint gate zero matches. Verified by the grep
  command above, run manually at commit time and recommended for
  `.github/workflows/test.yml` in Phase 6.
- **MCP-12** — Subprocess-driven handshake survival. Verified by all 8
  tests in `TestServerSubprocess`, most notably
  `test_stray_print_in_handler_does_not_corrupt_protocol_stream` (the
  MemPalace-killer regression test).

## Handoff to Phase 6 (CLI Polish)

- Registration command for users:
  ```bash
  claude mcp add sekha -- sekha serve
  ```
  No positional args. Server reads stdin until EOF. Set `SEKHA_HOME` env
  var if the user wants a non-default memory location (defaults to
  `~/.sekha/`).
- `sekha doctor` should run the hard CI lint grep against the four
  protocol-critical files as one of its health checks.
- `sekha doctor` should also verify a minimal initialize round-trip by
  spawning `sekha serve` with a 5-second timeout and piping a canonical
  initialize request — reuse the `_spawn_server` + `_read_response`
  pattern from `tests/test_server.py`.
- Phase 7 README / threat-model docs should cite this plan's
  `test_stray_print_in_handler_does_not_corrupt_protocol_stream` as
  the canonical proof that stdio hardening works end-to-end.

## Deferred (MCP v2)

Tracked for Phase 8+ / post-v0.1.0:

- Streaming tool results (`tools/call` chunked progress)
- `prompts/list` + `prompts/get` endpoints
- `resources/list` + `resources/read` endpoints (exposing memories as MCP resources)
- Rate limiting on `tools/call`
- Observability / metrics (per-method latency histograms, request-id traces)
- JSON-RPC batch request support (currently rejected with INVALID_REQUEST per Plan 05-01)

## Self-Check: PASSED

- FOUND: `src/sekha/server.py`
- FOUND: `tests/test_server.py`
- FOUND: `src/sekha/cli.py` (modified)
- FOUND: `.planning/phases/05-mcp-server/05-02-SUMMARY.md`
- FOUND: commit `bd649b3` (Task 1 RED)
- FOUND: commit `d98da0c` (Task 1 GREEN)
- FOUND: commit `295f05b` (Task 2 tests)
- Full suite: 282 passing, 0 failures, 3 pre-existing environmental skips
- Hard CI lint gate: zero matches across server/tools/jsonrpc/schemas
- Smoke test: initialize response parses as well-formed JSON on first line of stdout
- CI matrix: 9/9 cells green on run 24321161997
