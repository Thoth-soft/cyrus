# Roadmap: Cyrus

## Overview

Cyrus is a zero-dependency, local-first AI memory system whose differentiator is hook-level rules enforcement that survives `--dangerously-skip-permissions` in Claude Code. The journey from nothing to v0.1.0 on PyPI runs through eight phases: a non-code decision gate (Phase 0) that resolves the PyPI naming and Python-version blockers, three foundational library phases (storage, search, rules) that build the bedrock with no user-visible value, the **PreToolUse hook ahead of the MCP server** so the differentiator gets dogfooded on day 7 instead of day 30, then the MCP server, the install-experience CLI, and finally a polish-and-release phase that ships v0.1.0 to PyPI with a README, threat model, and example rules library. Every phase except 0 has a hard exit criterion tied to observable user behavior or measurable performance, and the whole thing targets ~2,000 lines of Python stdlib only.

## Phases

**Phase Numbering:**
- Integer phases (0, 1, 2, ...): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [x] **Phase 0: Setup & Naming Gate** - Resolve PyPI name conflict, lock Python 3.11 minimum, scaffold repo and CI (no application code)
- [ ] **Phase 1: Storage Foundation** - `cyrus.storage`, `cyrus.paths`, `cyrus.logutil` — atomic writes, frontmatter, filelock, `~/.cyrus/` taxonomy (1/2 plans done)
- [ ] **Phase 2: Search Engine** - `cyrus.search` with TF × recency scoring, ReDoS guard, and 10k-file p95 < 500ms benchmark
- [ ] **Phase 3: Rules Engine** - `cyrus.rules` pure-logic module: load, parse, tool-scoped match, precedence, compile cache, dry-run
- [ ] **Phase 4: PreToolUse Hook (THE DIFFERENTIATOR)** - `cyrus.hook` with fail-open policy, lazy imports, p50 < 50ms / p95 < 150ms CI gate, end-to-end Claude Code block test, dogfooding exit
- [ ] **Phase 5: MCP Server** - Newline-delimited JSON-RPC stdio server exposing 6 `cyrus_*` tools, with Windows hardening and stdout-pollution lint gate
- [ ] **Phase 6: CLI & Install Experience** - `cyrus init`, `cyrus doctor`, `cyrus add-rule`, `cyrus list-rules`, `cyrus hook bench`; fresh-VM install test on Windows + macOS + Linux
- [ ] **Phase 7: Polish, Docs & Release v0.1.0** - README with demo and threat model, example rules library, CHANGELOG, GitHub release tag, PyPI publish

## Phase Details

### Phase 0: Setup & Naming Gate
**Goal**: Resolve the two non-negotiable blockers (PyPI name + Python version) and stand up the empty-but-correct repository scaffolding so Phase 1 can start writing code without making structural decisions mid-flight.
**Depends on**: Nothing (first phase)
**Requirements**: SETUP-01, SETUP-02, SETUP-03, SETUP-04, SETUP-05
**Success Criteria** (what must be TRUE):
  1. A final PyPI package name is chosen, logged in PROJECT.md Key Decisions, and a v0.0.0 placeholder package owned by the user is live on PyPI under that name.
  2. `pyproject.toml` exists, declares Python 3.11+ as the minimum, uses hatchling, and has zero runtime dependencies (`[project.dependencies]` empty or absent).
  3. The GitHub repo at `github.com/Mo-Hendawy/<name>` has MIT LICENSE, README skeleton, and CONTRIBUTING.md committed to main.
  4. CI matrix is configured for Windows + macOS + Linux × Python 3.11, 3.12, 3.13 and runs successfully on a no-op placeholder test.
**Note**: This is a **decision gate**, not a coding phase. Success means "decisions logged + names reserved + scaffolding exists." There is no application code to test here.
**Plans**: 2 plans
Plans:
- [ ] 00-01-PLAN.md — Repository scaffolding: pyproject.toml, src/ layout, LICENSE, README, CONTRIBUTING, CI matrix, placeholder tests
- [ ] 00-02-PLAN.md — PyPI name reservation (v0.0.0 publish) and PROJECT.md decisions finalization
**UI hint**: no

### Phase 1: Storage Foundation
**Goal**: Build the bedrock library every other component depends on — atomic markdown file storage with hand-rolled frontmatter, cross-platform filelock, and the `~/.cyrus/` directory taxonomy. Zero user-visible value, but every downstream phase breaks if this has bugs.
**Depends on**: Phase 0
**Requirements**: STORE-01, STORE-02, STORE-03, STORE-04, STORE-05, STORE-06, STORE-07
**Success Criteria** (what must be TRUE):
  1. A test program can call the library, create a memory in any of the 5 fixed categories (`sessions/`, `decisions/`, `preferences/`, `projects/`, `rules/`), and the resulting file appears on disk with `YYYY-MM-DD_<id>_<slug>.md` naming and valid hand-parsed frontmatter.
  2. The `CYRUS_HOME` environment variable cleanly redirects all storage to a temporary location for tests.
  3. A 100-parallel-write stress test against a single file completes with zero corruption and zero partial writes (verified in CI on all three OSes).
  4. Cross-process file locking using `fcntl` on POSIX and `msvcrt` on Windows is exercised in the test suite and serializes concurrent writers without deadlock.
**Plans**: TBD
**UI hint**: no

### Phase 2: Search Engine
**Goal**: Deliver `cyrus.search` — a pure-stdlib full-text search built on `os.walk` + `re.compile` with term-frequency × recency × filename-match scoring, ReDoS protection, and benchmarked performance against a synthetic 10k-file corpus. Proves the "grep is good enough" thesis empirically.
**Depends on**: Phase 1
**Requirements**: SEARCH-01, SEARCH-02, SEARCH-03, SEARCH-04, SEARCH-05, SEARCH-06
**Success Criteria** (what must be TRUE):
  1. A test program can search a populated `~/.cyrus/` and get back a ranked list of memories with snippet excerpts (matched line ± context) for the top-N hits, scored by TF × recency × filename match.
  2. Optional filters for `category=`, date range, and tags reduce the result set as expected.
  3. A malicious regex query (catastrophic backtracking pattern) is killed by the ReDoS guard within a fixed timeout and surfaces a clear error rather than hanging the process.
  4. The 10k-file synthetic benchmark runs in CI and asserts p95 search latency under 500ms on warm cache. The benchmark data is checked in or generated deterministically from a seed.
**Plans**: 2 plans
Plans:
- [x] 02-01-PLAN.md — Core search: _searchutil helpers + public search() API with filters, scoring, snippet extraction, and ReDoS guard (SEARCH-01/02/03/04/06)
- [x] 02-02-PLAN.md — Deterministic 10k-file corpus generator + CYRUS_BENCH-gated p95<500ms benchmark (SEARCH-05)
**UI hint**: no

### Phase 3: Rules Engine
**Goal**: Build `cyrus.rules` as a pure-logic module — no I/O orchestration, no hook integration, just "given a tool name and tool input, which rules match and which severity wins?" This is the brain of the differentiator and ships as a testable unit before any process-level wiring.
**Depends on**: Phase 1
**Requirements**: RULES-01, RULES-02, RULES-03, RULES-04, RULES-05, RULES-06, RULES-07, RULES-08
**Success Criteria** (what must be TRUE):
  1. Given a directory of well-formed rule files, the engine loads them, parses frontmatter strictly (loud errors to stderr, invalid rules skipped not silenced), and exposes a `match(tool_name, tool_input)` API that returns the winning rule or none.
  2. Tool-scoped, anchored-by-default regex matching is verified in the test suite — including the `*` wildcard for `matches` and the `anchored: false` opt-out.
  3. Precedence is exhaustively tested: `block` beats `warn`; among blocks, highest priority wins; ties resolve to first-match and log the tie.
  4. The compiled-rules cache invalidates correctly when any file in the rules directory changes mtime, and `cyrus rule test <rule> <tool> <input>` evaluates a rule end-to-end without executing anything.
  5. `CYRUS_PAUSE=<rule-name>` (or a `cyrus pause` marker file) suppresses a single rule for the duration of the override and restores it cleanly when removed.
**Plans**: 1 plan
Plans:
- [x] 03-01-PLAN.md — TDD rules engine: _rulesutil helpers + rules.py public API (load_rules, evaluate, test_rule, clear_cache) + 13 fixtures; covers RULES-01..08
**UI hint**: no

### Phase 4: PreToolUse Hook (THE DIFFERENTIATOR)
**Goal**: Build `cyrus.hook` — the project's moat. A short-lived Python process invoked by Claude Code's PreToolUse hook that reads the JSON event from stdin, evaluates rules, and emits the correct `permissionDecision: deny` JSON to stdout. Ships **before** the MCP server so we discover any blocker on day 7, not day 30. If the hook can't actually block Claude Code in real life, the whole project pivots or dies here.
**Depends on**: Phase 3
**Requirements**: HOOK-01, HOOK-02, HOOK-03, HOOK-04, HOOK-05, HOOK-06, HOOK-07, HOOK-08, HOOK-09, HOOK-10
**Success Criteria** (what must be TRUE):
  1. The hook is registered as a `cyrus hook run` Python console script (no shell scripts), reads the full PreToolUse JSON schema from stdin, and emits the exact `{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": "..."}}` shape on a block — with belt-and-suspenders fallback to stderr + exit 2.
  2. **HARD CI GATE**: `cyrus hook bench` runs 100 invocations on Windows, macOS, and Linux runners and asserts **p50 < 50ms and p95 < 150ms**. The build fails if either threshold is exceeded — this is a blocker, not a warning.
  3. End-to-end integration test: a real Claude Code session is invoked with a "block all Bash" rule installed, attempts a Bash tool call, and the test asserts the call was blocked, the message reached the user, and no command executed. Runs on every release.
  4. Fail-open policy verified: any internal exception in the hook is caught at the top level, logged to `~/.cyrus/hook-errors.log`, surfaced to stderr, and the hook exits 0 (allow). Three consecutive errors auto-disable the hook via a marker file that `cyrus doctor` will later surface.
  5. **Dogfooding exit (felt-experience criterion)**: Mo has personally been blocked by a Cyrus rule while doing real work and appreciated it. This is not a metric — it is a lived experience. The phase does not close until it happens.
**Plans**: 2 plans
Plans:
- [ ] 04-01-PLAN.md — CLI router + hook core (block/warn/allow, fail-open, kill switch, `cyrus hook enable/disable`) covering HOOK-01..07, HOOK-09
- [ ] 04-02-PLAN.md — `cyrus hook bench` (CYRUS_BENCH-gated, platform-aware budget) + HOOK-10 integration-test runbook; covers HOOK-08, HOOK-10
**UI hint**: no

### Phase 5: MCP Server
**Goal**: Build the long-lived MCP server `cyrus.server` over newline-delimited JSON-RPC 2.0, exposing exactly 6 `cyrus_`-prefixed tools: `save`, `search`, `list`, `delete`, `status`, `add_rule`. With the hook already proven, this phase can focus exclusively on stdio framing correctness, Windows hardening, and the JSON-RPC handshake — the boring-but-deadly details that killed MemPalace.
**Depends on**: Phase 4
**Requirements**: MCP-01, MCP-02, MCP-03, MCP-04, MCP-05, MCP-06, MCP-07, MCP-08, MCP-09, MCP-10, MCP-11, MCP-12
**Success Criteria** (what must be TRUE):
  1. A scripted JSON-RPC handshake (`initialize` → `notifications/initialized` → `tools/list` → `tools/call`) piped into the real `cyrus` server subprocess succeeds on Windows, macOS, and Linux. Protocol versions `{2025-11-25, 2025-03-26, 2024-11-05}` are accepted and echoed back.
  2. From within Claude Code, all 6 `cyrus_` tools are discoverable via `tools/list`, and each tool round-trips a real call: save returns an ID, search returns ranked snippets, list returns metadata, delete removes, status reports counts, add_rule validates regex compilation before writing.
  3. **HARD CI LINT GATE**: `grep -r 'print(' src/cyrus/server.py src/cyrus/tools.py` returns zero results. The build fails if a stray `print(` exists. Additionally, at server boot `sys.stdout` is swapped to `sys.stderr` and Windows stdin/stdout is forced to binary mode + UTF-8.
  4. The server survives a `notifications/cancelled` mid-call without leaking state, and `ping` round-trips correctly.
**Plans**: TBD
**UI hint**: no

### Phase 6: CLI & Install Experience
**Goal**: Make the install path that MemPalace failed at. `cyrus init`, `cyrus doctor`, `cyrus add-rule`, `cyrus list-rules`, `cyrus hook bench` — plus an idempotent settings.json merge, ASCII-only output for cp1252 Windows shells, and a real fresh-VM install test on three operating systems. The phase is not done until a vanilla VM can run `pip install <name> && cyrus init && claude mcp add cyrus` with no manual fixups.
**Depends on**: Phase 5
**Requirements**: CLI-01, CLI-02, CLI-03, CLI-04, CLI-05, CLI-06, CLI-07, CLI-08
**Success Criteria** (what must be TRUE):
  1. `cyrus init` creates the full `~/.cyrus/` tree, writes a default `config.json`, backs up and merges hook config into `~/.claude/settings.json`, and prints the exact `claude mcp add cyrus` command for the user — and is fully idempotent across repeated runs.
  2. `cyrus doctor` validates Python version, package on PATH, hook registration, `~/.cyrus/` writability, recent hook errors, and round-trips a canary `initialize` call against the MCP server. Surfaces the kill-switch marker file from Phase 4 if it exists.
  3. `cyrus add-rule` interactive wizard collects name, severity, tool scope, pattern, and message; validates the regex compiles; and writes a well-formed rule file that `cyrus list-rules` then displays with last-modified time and broken-rule flags.
  4. **HARD RELEASE GATE**: Fresh-VM install test passes on vanilla Windows, macOS, and Linux VMs — `pip install <name> && cyrus init && claude mcp add cyrus` succeeds end-to-end with no manual fixups, and all CLI output is ASCII-only (no emoji, cp1252-safe). The phase does not close without this.
**Plans**: TBD
**UI hint**: no

### Phase 7: Polish, Docs & Release v0.1.0
**Goal**: Ship v0.1.0. Replace the README skeleton from Phase 0 with a real one, document the threat model honestly ("consistency enforcer, not security sandbox"), publish the example rules library, write the CHANGELOG, tag the release on GitHub, and publish to PyPI under the reserved name. After this phase the project is real and installable by strangers.
**Depends on**: Phase 6
**Requirements**: DOCS-01, DOCS-02, DOCS-03, DOCS-04, DOCS-05, DOCS-06, DOCS-07
**Success Criteria** (what must be TRUE):
  1. The README contains the install one-liner, a 30-second "add a rule, see it block" demo (text or asciinema), the feature list, the cross-client limitation prominently stated (hook enforcement is Claude Code only), and a link to the examples directory.
  2. A "Threat Model" section in the README clearly states Cyrus is a consistency enforcer, not a security sandbox; explains the AI could bypass via alternate tools; and frames this as by-design.
  3. The `examples/rules/` directory contains at least the four copy-paste-ready rules: `confirm-before-destructive.md`, `no-force-push-main.md`, `always-use-absolute-paths.md`, `require-tests-before-commit.md`.
  4. CONTRIBUTING.md (dev setup, test instructions, PR guidelines) and CHANGELOG.md (Keep a Changelog format, starting at v0.1.0) are committed.
  5. v0.1.0 is tagged on GitHub with release notes, and `pip install <name>` on a clean machine installs the published package.
**Plans**: TBD
**UI hint**: no

## Progress

**Execution Order:**
Phases execute in numeric order: 0 → 1 → 2 → 3 → 4 → 5 → 6 → 7

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 0. Setup & Naming Gate | 2/2 | Complete | 2026-04-12 |
| 1. Storage Foundation | 1/2 | Executing | - |
| 2. Search Engine | 0/2 | Not started | - |
| 3. Rules Engine | 0/1 | Not started | - |
| 4. PreToolUse Hook | 0/2 | Not started | - |
| 5. MCP Server | 0/TBD | Not started | - |
| 6. CLI & Install Experience | 0/TBD | Not started | - |
| 7. Polish, Docs & Release | 0/TBD | Not started | - |
