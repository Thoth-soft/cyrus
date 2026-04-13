# Cyrus — v1 Requirements

**Project:** Cyrus — zero-dependency AI memory system with hook-level rules enforcement
**Version:** v1.0 (first shippable release)
**Last updated:** 2026-04-11

---

## v1 Requirements

### Setup & Naming (SETUP)

- [ ] **SETUP-01**: Pick and reserve a PyPI package name (current `cyrus` and common variants are taken). Candidates: `cyrus-cc`, `cyrus-hook`, `cyrus-rules`, or unique rename.
- [ ] **SETUP-02**: `pyproject.toml` uses hatchling, declares Python 3.11+, has zero runtime dependencies (`[project.dependencies]` empty or absent).
- [ ] **SETUP-03**: CI matrix runs tests on Windows + macOS + Linux × Python 3.11, 3.12, 3.13. Every build passes before merge to main.
- [ ] **SETUP-04**: GitHub repository at `github.com/Mo-Hendawy/<name>` with MIT LICENSE, README skeleton, CONTRIBUTING.md.
- [ ] **SETUP-05**: PyPI account verified and the reserved name points to a v0.0.0 placeholder package.

### Storage (STORE)

- [x] **STORE-01**: `~/.cyrus/` directory layout uses 5 fixed categories: `sessions/`, `decisions/`, `preferences/`, `projects/`, `rules/`. Created on first run.
- [x] **STORE-02**: Memory files use filename format `YYYY-MM-DD_<id>_<slug>.md` for chronological sort and grep-friendliness.
- [x] **STORE-03**: Memory files have YAML-subset frontmatter (hand-parsed, no PyYAML) with fields: `id`, `category`, `created`, `updated`, `tags`, `source`.
- [x] **STORE-04**: Write operations are atomic (`os.replace` after `fsync` to a temp file in the same directory). No partial writes on crash.
- [x] **STORE-05**: Cross-process file locking uses `fcntl` on POSIX and `msvcrt` on Windows. Concurrent writes serialize without corruption.
- [x] **STORE-06**: `CYRUS_HOME` environment variable overrides the default `~/.cyrus/` location for testing and portable setups. *(Phase 1 / 01-01 — cyrus.paths.cyrus_home)*
- [x] **STORE-07**: Stress test: 100 parallel writes to the same file produce zero corruption. Part of unit test suite.

### Search (SEARCH)

- [x] **SEARCH-01**: Full-text search over all memory files using `re.compile` + `os.walk`. No external search dependencies.
- [x] **SEARCH-02**: Search results ranked by score: term frequency × recency decay × filename match bonus.
- [x] **SEARCH-03**: Results include snippet extraction (matched line ± context) for top-N hits only, not full file content.
- [x] **SEARCH-04**: Regex timeout guard prevents ReDoS on malicious queries (subprocess or signal-based watchdog).
- [ ] **SEARCH-05**: Benchmark: 10,000 generated markdown files, p95 search latency under 500ms warm cache on mid-range laptop.
- [x] **SEARCH-06**: Supports filtering by category (`category=rules`), date range, and tags via optional query parameters.

### Rules Engine (RULES)

- [x] **RULES-01**: Rule files live in `~/.cyrus/rules/*.md` with frontmatter fields: `name`, `severity` (block|warn), `triggers` (list of hook events), `matches` (list of tool names), `pattern` (regex), `priority`, `message`.
- [x] **RULES-02**: Strict frontmatter parser — surfaces parse errors loudly to stderr and skips invalid rules rather than silently ignoring them.
- [x] **RULES-03**: Rule matching is tool-scoped by default (`matches: [Bash]` only fires on Bash tool calls). Wildcard `*` supported.
- [x] **RULES-04**: Rule patterns use anchored regex by default to prevent accidental matching. Unanchored patterns require explicit `anchored: false`.
- [x] **RULES-05**: Precedence rule: `block` severity wins over `warn`. When multiple block rules match, highest priority wins. Tied priorities: first match wins and logs the tie.
- [x] **RULES-06**: Compiled rule cache (pickled `re.Pattern` objects) invalidated when any file in rules directory changes (mtime check).
- [x] **RULES-07**: `cyrus rule test <rule-name> <tool> <input>` dry-run command evaluates a rule without executing anything. For iterative rule development.
- [x] **RULES-08**: Temporary rule override via `CYRUS_PAUSE=<rule-name>` env var or `cyrus pause <rule>` command (sets marker file).

### PreToolUse Hook (HOOK)

- [x] **HOOK-01**: Hook entry point registered as `cyrus hook run` (Python console script via pyproject.toml). No shell scripts.
- [x] **HOOK-02**: Hook reads JSON event from stdin matching Claude Code's PreToolUse schema (`session_id`, `transcript_path`, `cwd`, `permission_mode`, `hook_event_name`, `tool_name`, `tool_input`, `tool_use_id`).
- [x] **HOOK-03**: On rule match with `severity: block`, hook emits `{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": "<message>"}}` to stdout and exits 0.
- [x] **HOOK-04**: On rule match with `severity: warn`, hook emits `{"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": "<warning>"}}` to stdout and allows the call.
- [x] **HOOK-05**: Belt-and-suspenders: hook also writes blocking reason to stderr and optionally exits 2 as a fallback if stdout JSON is ignored.
- [x] **HOOK-06**: Hook fail-open policy: any exception is caught at top level, logged to `~/.cyrus/hook-errors.log`, a warning written to stderr, and the hook exits 0 (allow). Never locks Claude Code out of tool calls.
- [x] **HOOK-07**: Kill switch: 3 consecutive hook errors cause it to auto-disable by writing a marker file. `cyrus doctor` surfaces this.
- [x] **HOOK-08**: **Performance budget: p50 under 50ms, p95 under 150ms** measured by `cyrus hook bench` over 100 runs on all three OSes. CI gate fails the build if exceeded.
- [x] **HOOK-09**: Lazy imports — top of `hook.py` imports only `sys`, `json`. All other imports inside functions. `python -X importtime cyrus.hook` shows <30ms total import time.
- [x] **HOOK-10**: End-to-end integration test: install a rule that blocks all `Bash` tool calls, invoke Claude Code with a Bash command, assert the block message appears and the command did not execute. Runs on every release.

### MCP Server (MCP)

- [ ] **MCP-01**: MCP server runs over stdio using newline-delimited JSON-RPC 2.0 (NOT Content-Length framed). Implements: `initialize`, `notifications/initialized`, `tools/list`, `tools/call`, `ping`, `notifications/cancelled`.
- [ ] **MCP-02**: Server accepts protocol versions `{2025-11-25, 2025-03-26, 2024-11-05}` and echoes back the version the client sent.
- [ ] **MCP-03**: All 6 MCP tools are prefixed `cyrus_`: `cyrus_save`, `cyrus_search`, `cyrus_list`, `cyrus_delete`, `cyrus_status`, `cyrus_add_rule`. No more, no fewer.
- [ ] **MCP-04**: `cyrus_save` — save memory with required `category`, `content`, optional `tags`, `source`. Returns the new memory ID.
- [ ] **MCP-05**: `cyrus_search` — semantic-free full-text search with required `query`, optional `category`, `limit` (default 10). Returns ranked results with snippets.
- [ ] **MCP-06**: `cyrus_list` — list memories with optional `category`, `limit`, `since`. Returns metadata only (no body).
- [ ] **MCP-07**: `cyrus_delete` — delete memory by ID. Returns success/failure.
- [ ] **MCP-08**: `cyrus_status` — returns total memory count, category breakdown, rules count, recent activity, hook error count.
- [ ] **MCP-09**: `cyrus_add_rule` — create a new rule with required `name`, `severity`, `matches`, `pattern`, `message`. Validates the regex compiles before writing.
- [ ] **MCP-10**: Stdio hardening: at server boot, `sys.stdout` is swapped to `sys.stderr` (any accidental `print()` goes to stderr). Windows stdin/stdout forced to binary mode + UTF-8.
- [ ] **MCP-11**: CI lint rule: `grep -r 'print(' src/cyrus/server.py src/cyrus/tools.py` must return zero results.
- [ ] **MCP-12**: Test harness: scripted JSON-RPC handshake sequences piped into the real server subprocess on all three OSes. Validates initialize → tools/list → tools/call round-trip.

### CLI & Install Experience (CLI)

- [ ] **CLI-01**: `cyrus init` — creates `~/.cyrus/` tree, writes default `config.json`, backs up + merges hook config into `~/.claude/settings.json`, prints the `claude mcp add cyrus` command for the user.
- [ ] **CLI-02**: `cyrus init` is idempotent: running it twice doesn't duplicate settings.json entries or overwrite existing data.
- [ ] **CLI-03**: `cyrus doctor` — validates install: Python version OK, package on PATH, hook registered in settings.json, ~/.cyrus/ writable, recent hook errors surfaced, MCP server tested with a canary `initialize` call.
- [ ] **CLI-04**: `cyrus add-rule` — interactive wizard that prompts for name, severity, tool scope, pattern, message, then validates and writes the rule file.
- [ ] **CLI-05**: `cyrus list-rules` — shows all rules with name, severity, tool scope, and last-modified time. Flags broken rules.
- [ ] **CLI-06**: `cyrus hook bench` — runs the hook 100 times with realistic rules and prints p50/p95/p99 latency. Exit code non-zero if p50 > 50ms or p95 > 150ms.
- [ ] **CLI-07**: All CLI output is ASCII-only (no emoji). Windows cp1252 safe. Tested on fresh Windows VM.
- [ ] **CLI-08**: Fresh-VM install test: on vanilla Windows, macOS, and Linux VMs, `pip install <name> && cyrus init && claude mcp add cyrus` succeeds end-to-end with no manual fixups. Part of release checklist.

### Documentation & Release (DOCS)

- [ ] **DOCS-01**: README includes: install one-liner, 30-second "add a rule, see it block" demo, feature list, cross-client limitation prominently stated (hook enforcement is Claude Code only), link to examples.
- [ ] **DOCS-02**: Threat model section in README: Cyrus is a consistency enforcer, not a security sandbox. AI could bypass via alternate tools. This is by design.
- [ ] **DOCS-03**: Example rules library (`examples/rules/`): `confirm-before-destructive.md`, `no-force-push-main.md`, `always-use-absolute-paths.md`, `require-tests-before-commit.md`. Copy-paste ready.
- [ ] **DOCS-04**: CONTRIBUTING.md with dev setup, test instructions, PR guidelines.
- [ ] **DOCS-05**: CHANGELOG.md following Keep a Changelog format, starting at v0.1.0.
- [ ] **DOCS-06**: Tagged v0.1.0 release on GitHub with release notes.
- [ ] **DOCS-07**: Published to PyPI with the reserved name, installable via `pip install <name>`.

---

## v2 Requirements (Deferred)

- Auto-save hook (Stop event triggered) — risk of mid-task junk memories; design properly in v2
- Per-project memory directories (`.cyrus/` alongside code)
- Memory tagging and tag-based search
- Export/import memories (JSON, zip archive)
- Optional SQLite FTS5 index if search performance hits the 10k-file wall
- `cyrus pause <rule>` as a first-class command (v1 uses env var override)
- `updatedInput` hook output to rewrite tool inputs before execution (not just block)

---

## Out of Scope (v1 and beyond)

- **Vector / semantic search** — adds ChromaDB/embedding-model dependencies. Not what we want.
- **Custom compression dialects (AAAK-style)** — clever but unreadable. Plain markdown wins.
- **Knowledge graphs / temporal triples** — overkill, adds complexity without clear payoff.
- **Entity detection / auto-classification** — fragile, fails on real data.
- **Conversation mining from external sources** (Slack, ChatGPT exports) — scope creep.
- **GUI / dashboard** — files in a folder. Users browse with any editor.
- **Cloud sync / multi-device** — local files only. Users sync via git/Dropbox/iCloud.
- **Non-MCP CLI-only workflows** — CLI is a thin wrapper for debugging, not the primary interface.
- **Support for Claude Code versions older than the current release** — protocol drift makes this a maintenance nightmare.
- **Multi-user / team-shared memory** — not a multi-tenant system. Single-user local-first only.

---

## Traceability

**Coverage:** 63 of 63 v1 requirements mapped to phases (100%). No orphans.

| REQ-ID | Phase | Status |
|--------|-------|--------|
| SETUP-01 | Phase 0 | Pending |
| SETUP-02 | Phase 0 | Pending |
| SETUP-03 | Phase 0 | Pending |
| SETUP-04 | Phase 0 | Pending |
| SETUP-05 | Phase 0 | Pending |
| STORE-01 | Phase 1 | Complete |
| STORE-02 | Phase 1 | Complete |
| STORE-03 | Phase 1 | Complete |
| STORE-04 | Phase 1 | Complete |
| STORE-05 | Phase 1 | Complete |
| STORE-06 | Phase 1 / 01-01 | Complete (2026-04-12) |
| STORE-07 | Phase 1 | Complete |
| SEARCH-01 | Phase 2 | Complete |
| SEARCH-02 | Phase 2 | Complete |
| SEARCH-03 | Phase 2 | Complete |
| SEARCH-04 | Phase 2 | Complete |
| SEARCH-05 | Phase 2 | Pending |
| SEARCH-06 | Phase 2 | Complete |
| RULES-01 | Phase 3 | Complete |
| RULES-02 | Phase 3 | Complete |
| RULES-03 | Phase 3 | Complete |
| RULES-04 | Phase 3 | Complete |
| RULES-05 | Phase 3 | Complete |
| RULES-06 | Phase 3 | Complete |
| RULES-07 | Phase 3 | Complete |
| RULES-08 | Phase 3 | Complete |
| HOOK-01 | Phase 4 | Complete |
| HOOK-02 | Phase 4 | Complete |
| HOOK-03 | Phase 4 | Complete |
| HOOK-04 | Phase 4 | Complete |
| HOOK-05 | Phase 4 | Complete |
| HOOK-06 | Phase 4 | Complete |
| HOOK-07 | Phase 4 | Complete |
| HOOK-08 | Phase 4 | Complete |
| HOOK-09 | Phase 4 | Complete |
| HOOK-10 | Phase 4 | Complete |
| MCP-01 | Phase 5 | Pending |
| MCP-02 | Phase 5 | Pending |
| MCP-03 | Phase 5 | Pending |
| MCP-04 | Phase 5 | Pending |
| MCP-05 | Phase 5 | Pending |
| MCP-06 | Phase 5 | Pending |
| MCP-07 | Phase 5 | Pending |
| MCP-08 | Phase 5 | Pending |
| MCP-09 | Phase 5 | Pending |
| MCP-10 | Phase 5 | Pending |
| MCP-11 | Phase 5 | Pending |
| MCP-12 | Phase 5 | Pending |
| CLI-01 | Phase 6 | Pending |
| CLI-02 | Phase 6 | Pending |
| CLI-03 | Phase 6 | Pending |
| CLI-04 | Phase 6 | Pending |
| CLI-05 | Phase 6 | Pending |
| CLI-06 | Phase 6 | Pending |
| CLI-07 | Phase 6 | Pending |
| CLI-08 | Phase 6 | Pending |
| DOCS-01 | Phase 7 | Pending |
| DOCS-02 | Phase 7 | Pending |
| DOCS-03 | Phase 7 | Pending |
| DOCS-04 | Phase 7 | Pending |
| DOCS-05 | Phase 7 | Pending |
| DOCS-06 | Phase 7 | Pending |
| DOCS-07 | Phase 7 | Pending |
