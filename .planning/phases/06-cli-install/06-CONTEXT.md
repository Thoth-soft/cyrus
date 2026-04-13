# Phase 6: CLI & Install Experience - Context

**Gathered:** 2026-04-13
**Status:** Ready for planning
**Mode:** Auto-generated (infrastructure phase)

<domain>
## Phase Boundary

Make the install path that MemPalace failed at. Ship `sekha init`, `sekha doctor`, `sekha add-rule`, `sekha list-rules`, plus idempotent settings.json merge and fresh-VM install tests on Win/macOS/Linux.

Exit criterion: a vanilla VM can run `pip install sekha && sekha init && claude mcp add sekha -- sekha serve` with zero manual fixups.

</domain>

<decisions>
## Implementation Decisions

### CLI Commands (add to existing `sekha.cli`)

Already shipped (Phase 4/5): `sekha hook run`, `sekha hook bench`, `sekha hook enable`, `sekha hook disable`, `sekha serve`

Add in Phase 6:
- `sekha init` — one-shot setup
- `sekha doctor` — diagnostic/health check
- `sekha add-rule` — interactive rule wizard
- `sekha list-rules` — show all rules with status

### `sekha init`

Actions (in order):
1. Create `~/.sekha/` tree with 5 category subdirs (reuse `sekha.paths.sekha_home()`)
2. Write default `~/.sekha/config.json` if absent:
   ```json
   {"version": "0.0.0", "hook_enabled": true, "hook_budget_ms": {"p50": 50, "p95": 150}}
   ```
3. Back up `~/.claude/settings.json` → `~/.claude/settings.json.bak.<timestamp>` if exists
4. Merge hook registration into `~/.claude/settings.json`:
   ```json
   {
     "hooks": {
       "PreToolUse": [
         {
           "matcher": "*",
           "hooks": [
             {"type": "command", "command": "sekha hook run"}
           ]
         }
       ]
     }
   }
   ```
   If existing `hooks.PreToolUse` array exists, append (avoid duplicates by matching command string).
5. Print the `claude mcp add` command for user:
   ```
   Next step: register the MCP server:
     claude mcp add sekha -- sekha serve
   ```

**Idempotent:** running twice doesn't duplicate entries. Checks for existing hook matching `sekha hook run` before appending.

**Windows:** uses `pathlib.Path.home()` → `C:\Users\<name>\.claude`. No special casing.

### `sekha doctor`

Validates (each with clear pass/fail output):
1. `python --version` >= 3.11 ✓/✗
2. `sekha` binary on PATH ✓/✗ (checks `shutil.which("sekha")`)
3. `~/.sekha/` exists and is writable ✓/✗
4. `~/.claude/settings.json` has `sekha hook run` registered ✓/✗
5. Canary MCP handshake: spawn `sekha serve`, send `initialize`, parse response, kill ✓/✗
6. Kill switch marker present? ✓/✗ (warn if yes, instruct `sekha hook enable`)
7. Recent hook errors (last 24h) from `~/.sekha/hook-errors.log`: count and show last 3 ✓/✗

Output format: colored pass/fail with ASCII-only chars (cp1252 safe):
```
[OK] Python 3.11.8
[OK] sekha binary on PATH: /usr/local/bin/sekha
[OK] ~/.sekha writable
[OK] Hook registered in ~/.claude/settings.json
[OK] MCP server responds to initialize
[OK] Kill switch not active
[OK] No hook errors in last 24h

All checks passed. Sekha is ready to use.
```

No emoji. No Unicode box-drawing. Just ASCII.

### `sekha add-rule`

Interactive wizard (input() calls), or argparse flags for scripted use:
```
sekha add-rule --name block-docker-prune --severity block --matches Bash --pattern "docker system prune.*-f" --message "Dangerous: forces docker prune without confirmation"
```

Validates:
- Name: alphanumeric + hyphens, doesn't collide with existing file
- Severity: block or warn
- Matches: non-empty list
- Pattern: compiles as regex (test via `re.compile`)
- Message: non-empty
- Priority: int 1-100 (default 50)
- Triggers: default ["PreToolUse"]

Writes to `~/.sekha/rules/<name>.md` via `sekha.storage.save_memory` (or direct write with proper frontmatter).

### `sekha list-rules`

Shows all rules in `~/.sekha/rules/` as a table:
```
NAME                  SEVERITY  MATCHES  PATTERN              STATUS
block-rm-rf           block     Bash     rm\s+-rf\s+/         OK
block-force-push      block     Bash     git.*push.*--force   OK
warn-no-tests         warn      Bash     git commit           OK
broken-rule           ?         ?        ?                    BROKEN (no severity)
```

Flags broken rules (ones that failed to parse in `sekha.rules.load_rules`).

### Fresh-VM Install Test (HARD RELEASE GATE)

Requirement CLI-08: on vanilla Win/macOS/Linux VMs:
```bash
pip install sekha==0.0.0
sekha init
claude mcp add sekha -- sekha serve
```
...must succeed end-to-end with no manual fixups.

**Implementation in Phase 6:** since v0.0.0 isn't on PyPI yet (deferred from Plan 00-02), we test with editable install locally:
```bash
# On fresh VM:
pip install -e /path/to/sekha
sekha init
# Verify ~/.sekha/ created, settings.json updated, no errors
```

CI job: add `install-test` matrix cell that does `pip install -e .` + `sekha init` + `sekha doctor` on each OS × Python version, asserts exit 0 on all.

### ASCII-Only Output (Cp1252 Safe)

Windows cmd.exe uses cp1252 encoding by default. Our CLI output must not include:
- Emoji (☒ ✓ ✗ 🚀)
- Unicode box-drawing (╭ ├ ╯)
- Arrows (→ ← ↑ ↓)

Use ASCII equivalents:
- `[OK]` / `[FAIL]` / `[WARN]` instead of ✓/✗/⚠
- `-->` instead of →
- `|` `+` `-` for tables (or just indent)

Ship a `force_utf8()` helper in `sekha._cliutil` that attempts `sys.stdout.reconfigure("utf-8")` but falls back gracefully if not possible.

### Module Layout

Expand existing `sekha.cli`:
```
src/sekha/
    cli.py          # existing — add init, doctor, add-rule, list-rules commands
    _cliutil.py     # NEW — ASCII table formatting, settings.json merge, etc
    _init.py        # NEW — init command implementation (kept separate for testability)
    _doctor.py      # NEW — doctor command implementation
```

### Claude's Discretion

- Whether `sekha init` opens an interactive prompt or just runs with defaults (suggest: default run, `--interactive` flag for wizard mode)
- Whether to suggest running `sekha doctor` after init (suggest: yes, print "Verify with: sekha doctor")
- Whether `sekha add-rule` prompts interactively when no flags given, or errors out (suggest: interactive wizard if TTY, error if not)

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `sekha.storage.save_memory`, `sekha.storage.CATEGORIES` — for rule file writes
- `sekha.rules.load_rules` — for list-rules parsing
- `sekha.paths.sekha_home()` — home dir
- `sekha.cli` — existing argparse router, ADD subcommands
- `sekha.server` — for doctor canary test (spawn + handshake)
- `sekha.hook` — for doctor kill-switch check

### Established Patterns
- Stdlib only
- pathlib.Path
- unittest
- ASCII-only output for Windows compat

### Integration Points
- `~/.claude/settings.json` — hooks registration merge
- `~/.sekha/` — config file + rule file writes
- Cross-platform: Windows cmd.exe, macOS Terminal, Linux bash all must work

</code_context>

<specifics>
## Specific Ideas

- Test fresh-VM install via CI matrix (add a new job cell `install-test` that runs on all 3 OSes)
- Backup `settings.json` before merge — always — with timestamp in filename
- `sekha init` must handle case: no `~/.claude/settings.json` exists yet (create fresh with hooks block)
- `sekha doctor --json` flag for machine-readable output (nice-to-have for CI)

</specifics>

<deferred>
## Deferred Ideas

- Web-based config UI — v2 (anti-feature)
- Auto-update sekha — v2
- Interactive "rule builder" that suggests rules based on recent Bash history — v2
- Telemetry opt-in — v2 (privacy concerns)

</deferred>

---

*Phase: 06-cli-install*
*Context gathered: 2026-04-13 via infrastructure auto-detection*
