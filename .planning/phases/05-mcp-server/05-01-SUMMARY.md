---
phase: 05-mcp-server
plan: 01
subsystem: mcp-server-protocol-layer
tags: [mcp, jsonrpc, stdio-hardening, tools, schemas, tdd]
dependency-graph:
  requires:
    - sekha.storage (save_memory, atomic_write, dump_frontmatter, parse_frontmatter)
    - sekha.search (search, SearchResult)
    - sekha._rulesutil (_compile_rule_pattern)
    - sekha.paths (CATEGORIES, category_dir, sekha_home)
    - sekha.logutil (get_logger)
  provides:
    - sekha.jsonrpc (harden_stdio, parse, emit, emit_error, JsonRpcError, error code constants, ACCEPTED_PROTOCOL_VERSIONS)
    - sekha.schemas (TOOLS, TOOLS_BY_NAME)
    - sekha.tools (6 handlers + HANDLERS dispatch)
  affects:
    - Plan 05-02 server.py will import harden_stdio + parse + emit + emit_error + HANDLERS + TOOLS
tech-stack:
  added: []
  patterns:
    - "Lazy import of sekha.search inside sekha_search handler (keeps sekha_status cheap)"
    - "TextIOWrapper(write_through=True) for protocol channel — blocking reader demands immediate flush"
    - "Path scope check via Path.relative_to() for sekha_delete — refuses arbitrary FS access"
    - "Pre-flight regex compile for sekha_add_rule BEFORE any disk I/O (MCP-09 hard requirement)"
key-files:
  created:
    - src/sekha/jsonrpc.py
    - src/sekha/schemas.py
    - src/sekha/tools.py
    - tests/test_jsonrpc.py
    - tests/test_schemas.py
    - tests/test_tools.py
  modified: []
decisions:
  - "JsonRpcError subclasses ValueError (not a new exception hierarchy) — keeps the try/except surface in the server loop tiny: `except ValueError as e: emit_error(..., getattr(e, 'code', INTERNAL_ERROR), ...)`"
  - "Protected stdout wraps real_stdout.buffer in write_through=True — Claude Code's stdio reader blocks on readline(); any buffering between us and the fd hangs the handshake forever"
  - "Windows branch of harden_stdio swallows OSError/AttributeError/ValueError on msvcrt.setmode — tests wrap stdio in BytesIO which has no fileno(); real processes still get the binary-mode fix"
  - "sekha_delete is scope-checked via Path.relative_to(sekha_home()) — an attacker with Claude hijack cannot call sekha_delete('/etc/passwd')"
  - "sekha_delete returns {success: False, error: ...} for missing/scope violations rather than raising — callers expect these as data, not exceptions"
  - "sekha_add_rule routes pattern through sekha._rulesutil._compile_rule_pattern (anchored=True) so rules that load successfully later also compile here"
  - "sekha_search is a lazy import inside the handler — sekha.search pulls in re/heapq/dataclasses which we don't want to pay on every sekha_status call"
  - "TOOLS_BY_NAME built from TOOLS at import time so the two definitions can never drift out of sync"
metrics:
  duration: 6 minutes
  completed: 2026-04-13
  commits: 6
  tests_added: 44
  tests_total: 260
  lint_gate: zero print() hits across jsonrpc.py, schemas.py, tools.py
---

# Phase 5 Plan 01: MCP Server Protocol Layer Summary

Built the MCP server's protocol layer — stdio hardening, JSON-RPC parse/emit helpers, hand-written JSON schemas for the 6 `sekha_*` tools, and 6 handler functions that delegate to existing library code — as three clean modules behind 44 new TDD tests, with the hard CI lint gate (no stray `print(` anywhere in the protocol files) passing on a zero-hit grep.

## What Was Built

### `src/sekha/jsonrpc.py` (209 lines)
The single most protocol-critical file in the codebase. Exposes:
- Error code constants: `PARSE_ERROR=-32700`, `INVALID_REQUEST=-32600`, `METHOD_NOT_FOUND=-32601`, `INVALID_PARAMS=-32602`, `INTERNAL_ERROR=-32603`
- `ACCEPTED_PROTOCOL_VERSIONS = frozenset({"2025-11-25", "2025-03-26", "2024-11-05"})`
- `JsonRpcError(ValueError)` with `.code` attribute
- `parse(line) -> dict` — newline-delimited JSON-RPC, raises `JsonRpcError(PARSE_ERROR)` on bad JSON and `JsonRpcError(INVALID_REQUEST)` on batch arrays / non-object payloads
- `emit(stream, payload)` — `json.dumps(sep=',',':')` + `\n` + `flush()` (no embedded newlines, no stray whitespace)
- `emit_error(stream, request_id, code, message)` — `id=null` when request_id is None
- `harden_stdio() -> TextIOWrapper` — the MemPalace-killer function

`harden_stdio` implements the three fixes MemPalace shipped wrong:
1. Swap `sys.stdout -> sys.stderr` so stray `print()` from any subsequent import goes to stderr harmlessly (Pitfall 2)
2. On Windows, `msvcrt.setmode(fd, O_BINARY)` on stdin + real stdout so CRLF translation cannot mangle JSON (Pitfall 3)
3. Wrap the captured real-stdout buffer in `TextIOWrapper(encoding="utf-8", errors="replace", newline="\n", write_through=True)` so Python 3.14's cp1252 default on Windows cannot `UnicodeEncodeError` us (Pitfall 4)

### `src/sekha/schemas.py` (151 lines)
Source of truth for `tools/list`. `TOOLS` is a 6-element list of `{name, description, inputSchema}` dicts matching `05-CONTEXT.md` verbatim:
- `sekha_save` (category enum = `CATEGORIES`, required `[category, content]`)
- `sekha_search` (required `[query]`, default `limit=10`)
- `sekha_list` (all optional, default `limit=20`)
- `sekha_delete` (required `[path]`)
- `sekha_status` (no params)
- `sekha_add_rule` (severity enum `[block, warn]`, default `priority=50`, default `triggers=[PreToolUse]`, required `[name, severity, matches, pattern, message]`)

`TOOLS_BY_NAME` built from `TOOLS` at import time so they never drift.

### `src/sekha/tools.py` (325 lines)
Six thin-delegate handlers + `HANDLERS` dispatch dict:
- `sekha_save` — passthrough to `save_memory`, returns `{path, id}` (id extracted from filename)
- `sekha_search` — lazy-imports `sekha.search`, serializes `SearchResult` to dict
- `sekha_list` — glob + `parse_frontmatter`, metadata-only (no body), sorted by updated desc, truncated to `limit`
- `sekha_delete` — scope-checked via `Path.relative_to(sekha_home())` — refuses anything outside; returns `{success, path}` or `{success: False, error}`; never raises on missing/scope violations
- `sekha_status` — glob counts + hook-errors.log line count + top-5 recent memories
- `sekha_add_rule` — compiles pattern via `_compile_rule_pattern(anchored=True)` BEFORE any disk I/O; `atomic_write` rule file; returns `{path}`

## Tests Added

| Suite                  | Count | Coverage                                                                 |
| ---------------------- | ----- | ------------------------------------------------------------------------ |
| `tests/test_jsonrpc.py` | 15 (1 skipped on Windows) | Error codes, parse/emit shape, id=null, no embedded newlines, harden_stdio swap + stray print survival + UTF-8 encoding |
| `tests/test_schemas.py` | 11    | List length, sekha_* prefix, top-level keys, required fields, enums, defaults, TOOLS_BY_NAME round-trip |
| `tests/test_tools.py`   | 18    | All 6 handlers: save returns path+id, search filters/limits, list metadata-only, delete scope check, status line count + shape, add_rule regex pre-flight + bad severity |
| **Total**               | **44** | — |

Full suite: 260 tests pass (was 216 at baseline). Zero regressions.

## Commits

| Commit | Type | Description |
| ------ | ---- | ----------- |
| `bce2eb7` | test | add failing tests for sekha.jsonrpc |
| `5bdc15c` | feat | implement sekha.jsonrpc (stdio hardening + parse/emit) |
| `21c0fc0` | test | add failing tests for sekha.schemas |
| `d12b13e` | feat | hand-write JSON schemas for 6 sekha_* tools |
| `dc4f483` | test | add failing tests for sekha.tools handlers |
| `3098d1c` | feat | implement 6 sekha_* tool handlers |

Three clean RED→GREEN TDD pairs. No refactor commit needed — the implementations landed small enough that no extraction was warranted.

## Deviations from Plan

None — plan executed exactly as written. The `<action>` code blocks in `05-01-PLAN.md` were lifted almost verbatim (with docstring embellishment and a minor `required: []` explicit addition to the `sekha_list` schema to satisfy test #7's round-trip assertion cleanly).

Two minor plan-interpretation notes (not deviations):
- The plan said "raises re.error (or returns error)" for `sekha_add_rule` bad-pattern; tests use `assertRaises(Exception)` to accept either — we chose to propagate `re.error` (subclass of `Exception`) since the server loop already converts raises to MCP error responses.
- The plan said `test_parse_valid_json` should assert trailing whitespace is tolerated; split into two tests (`test_parse_valid_json` + `test_parse_tolerates_trailing_whitespace`) for clearer failure attribution. Net coverage equivalent.

## Requirements Verified

| Req    | Covered by                                                                                                          |
| ------ | ------------------------------------------------------------------------------------------------------------------- |
| MCP-03 | `TOOLS` has exactly 6 entries, all `sekha_*`-prefixed (`test_tool_names_are_sekha_prefixed_and_complete`)           |
| MCP-04 | `sekha_save` returns `{path, id}` and persists frontmatter with tags/source (`TestSekhaSave`)                      |
| MCP-05 | `sekha_search` returns `{results: [...]}` ranked; respects category + limit (`TestSekhaSearch`)                    |
| MCP-06 | `sekha_list` returns metadata-only (no `content`/`body` keys); respects category + limit (`TestSekhaList`)         |
| MCP-07 | `sekha_delete` removes file, returns failure on missing, refuses out-of-scope paths (`TestSekhaDelete`)            |
| MCP-08 | `sekha_status` reports `{total, by_category, rules_count, recent, hook_errors}` (`TestSekhaStatus`)                 |
| MCP-09 | `sekha_add_rule` validates regex BEFORE write; broken pattern leaves no file (`test_add_rule_validates_regex_before_write`) |
| MCP-10 | `harden_stdio` swaps stdout->stderr, wraps in UTF-8 TextIOWrapper; stray `print()` survival tested                  |
| MCP-11 | `grep -rE "^\s*print\(" src/sekha/jsonrpc.py src/sekha/schemas.py src/sekha/tools.py` returns **zero hits**         |

## What's NOT In This Plan (Handoff to Plan 05-02)

- `src/sekha/server.py` — the main loop, `initialize` handshake, `tools/list`/`tools/call` dispatch
- `sekha.cli` `serve` subcommand wiring
- Subprocess integration tests (`python -m sekha.cli serve` piped JSON-RPC sequences)
- Windows binary-mode branch coverage (only reachable via real-process subprocess tests; the unit tests skip it because `msvcrt.setmode` needs a real fd)

Plan 05-02 will consume this plan's public surface (`harden_stdio`, `parse`, `emit`, `emit_error`, `HANDLERS`, `TOOLS`) without change.

## Self-Check: PASSED

- `src/sekha/jsonrpc.py`: FOUND (209 lines)
- `src/sekha/schemas.py`: FOUND (151 lines)
- `src/sekha/tools.py`: FOUND (325 lines)
- `tests/test_jsonrpc.py`: FOUND (234 lines, 15 tests)
- `tests/test_schemas.py`: FOUND (116 lines, 11 tests)
- `tests/test_tools.py`: FOUND (282 lines, 18 tests)
- Commits `bce2eb7`, `5bdc15c`, `21c0fc0`, `d12b13e`, `dc4f483`, `3098d1c`: all FOUND in `git log`
- Full suite: **260 tests pass** (216 baseline + 44 new, zero regressions)
- Lint gate: **zero hits** on `grep -rE "^\s*print\(" src/sekha/jsonrpc.py src/sekha/schemas.py src/sekha/tools.py`
- Handler/schema agreement: `set(HANDLERS) == {t['name'] for t in TOOLS}` — **True**
