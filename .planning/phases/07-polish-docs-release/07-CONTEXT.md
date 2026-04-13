# Phase 7: Polish, Docs & Release v0.1.0 - Context

**Gathered:** 2026-04-13
**Status:** Ready for planning
**Mode:** Auto-generated (release/docs phase)

<domain>
## Phase Boundary

Ship v0.1.0. Replace the README skeleton with a real one, write the threat model, publish example rules, update CHANGELOG, tag the GitHub release. After this phase, strangers can `pip install sekha` and use it confidently.

Note: actual PyPI publish is still blocked on user's PyPI token (Plan 00-02). Phase 7 preps everything for release and tags the GitHub release — PyPI upload is the final user-initiated step.

</domain>

<decisions>
## Implementation Decisions

### Real README.md

Replace the 13-line skeleton with a proper README:

```markdown
# Sekha

Zero-dependency AI memory system with hook-level rules enforcement for Claude Code.

## Why Sekha?

Every AI memory system stores rules. None of them enforce them.

Sekha hooks into Claude Code's PreToolUse event to **actually block** tool calls that violate your rules — the AI cannot bypass this, even with `--dangerously-skip-permissions`.

[30-second demo showing: write rule → claude tries to run rm -rf → blocked with message]

## Install

```bash
pip install sekha
sekha init
claude mcp add sekha -- sekha serve
```

## Features

- **Persistent memory** across sessions (conversations, decisions, preferences) stored as plain markdown files in `~/.sekha/`
- **Rules enforcement** at the hook level — cannot be bypassed by the AI
- **Zero dependencies** — pure Python stdlib
- **Works with any MCP client** — Claude Code, Cursor, Cline, etc (hook enforcement is Claude Code only)
- **6 MCP tools**: sekha_save, sekha_search, sekha_list, sekha_delete, sekha_status, sekha_add_rule
- **CLI**: sekha init, sekha doctor, sekha add-rule, sekha list-rules, sekha hook bench

## How It Works

[Diagram: Claude Code → PreToolUse hook → sekha hook run → rules engine → block or allow]

Three processes, all sharing state via `~/.sekha/`:
1. **MCP server** (long-lived, one per Claude Code session) — serves memory tools
2. **Hook** (short-lived, per-tool-call) — enforces rules, blocks violations
3. **CLI** (one-shot) — init, doctor, add-rule, etc

## Example Rules

See `examples/rules/` for copy-paste rules like:
- `block-rm-rf.md` — prevent `rm -rf /` disasters
- `block-force-push-main.md` — no force push to main
- `warn-no-tests.md` — warn before commit without tests
- `block-drop-table.md` — prevent DROP TABLE in SQL queries

## Threat Model

**Sekha is a consistency enforcer, not a security sandbox.**

The AI could bypass a rule by using a different tool — if you block `Bash` with pattern `rm -rf`, the AI could use the `Write` tool to create a deletion script. This is intentional.

Sekha exists to keep the AI honest about *intentions* you've made explicit, not to prevent a malicious AI from finding creative workarounds. For that, use OS-level sandboxing.

## Cross-Client Support

| Client | Memory (MCP tools) | Rules Enforcement (hook) |
|--------|---------------------|---------------------------|
| Claude Code | ✓ | ✓ |
| Cursor | ✓ | ✗ (no hook API) |
| Cline | ✓ | ✗ |
| Windsurf | ✓ | ✗ |

Hook enforcement is **Claude Code exclusive** in v0.1.0. Memory tools work everywhere MCP works.

## Docs

- [Integration test runbook](docs/hook-integration-test.md) — verify the hook blocks on your machine
- [CHANGELOG](CHANGELOG.md) — version history

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT
```

### CHANGELOG.md

Create in Keep a Changelog format:

```markdown
# Changelog

All notable changes to Sekha will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.1.0] - 2026-04-XX

### Added

- **Memory system**: save/search/list/delete memories via MCP tools
- **Rules engine**: load rules from `~/.sekha/rules/`, match by tool_name + pattern
- **PreToolUse hook**: enforce rules at the hook level (blocks violations)
- **MCP server**: newline-delimited JSON-RPC over stdio, 6 tools
- **CLI**: init, doctor, add-rule, list-rules, hook run/bench/enable/disable, serve
- **Zero dependencies** — pure Python stdlib
- **Cross-platform**: Windows, macOS, Linux (Python 3.11+)

### Performance

- Hook cold-start: p50 <50ms / p95 <150ms on Linux/macOS (Windows: p95 <300ms platform-adjusted)
- Search: 10k-file corpus, sub-second p95 warm cache

### Quality

- 337 tests, 9-cell CI matrix (3 OS × 3 Python), fresh-VM install test
- Zero runtime dependencies
- TDD throughout
```

### Example Rules (`examples/rules/`)

Ship 4 copy-paste-ready rules with commentary:

1. `block-rm-rf.md` — blocks `rm -rf` with root or wildcard paths
2. `block-force-push-main.md` — blocks `git push --force` to main
3. `block-drop-table.md` — blocks SQL `DROP TABLE` in Bash/query tools
4. `warn-no-tests-before-commit.md` — warns on `git commit` without recent test run

Each example rule has a header comment explaining use case and variations.

### GitHub Release

1. Tag `v0.1.0` on GitHub main
2. Release notes copy from CHANGELOG's 0.1.0 section
3. Attach built `.whl` and `.tar.gz` as release assets (`python -m build`)

### PyPI Publish (User Action)

Documented in `docs/release.md`:
```bash
python -m pip install --upgrade build twine
python -m build
TWINE_USERNAME=__token__ TWINE_PASSWORD=$PYPI_TOKEN python -m twine upload dist/*
```

Note: Plan 00-02 (PyPI name reservation) is also unblocked by this step — publishing v0.1.0 reserves the name as a side effect.

### Integration Test Dogfooding

Phase 4 Plan 04-02 shipped `docs/hook-integration-test.md` — user walks through it once, confirms "Mo has been blocked by a rule and appreciated it" (Phase 4 exit criterion).

This is the v0.1.0 release gate that remains user-driven.

### Module/File Layout

No new modules. Only:
- `README.md` (rewrite)
- `CHANGELOG.md` (new)
- `examples/rules/*.md` (4 files, new)
- `docs/release.md` (new — PyPI publish instructions)

### Claude's Discretion

- Whether to add a small animated GIF demo in README (suggest: leave as text for v0.1.0, add GIF in v0.1.1)
- Whether to include benchmark numbers table in README (suggest: yes, they're impressive)
- Whether to mention MemPalace by name (suggest: no — be positive about own thing, don't bash others publicly)

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `tests/fixtures/rules/*.md` — existing rule fixtures can be base for examples/rules/
- `docs/hook-integration-test.md` — existing runbook
- All existing code ships as-is

### Established Patterns
- ASCII-only in everything (even docs should avoid problematic Unicode)
- Factual, no marketing fluff
- Show don't tell (code examples > descriptions)

### Integration Points
- GitHub release via `gh release create v0.1.0`
- PyPI publish still blocked on user's token
- Tag is the release

</code_context>

<specifics>
## Specific Ideas

- README should lead with the differentiator — rules enforcement is the headline, memory is supporting cast
- Don't bury the "zero dependencies" claim — it's a feature
- Link to `docs/hook-integration-test.md` as the go-to for skeptics who want to verify the block claim themselves
- Example rules should have exactly one job each — not bundled rule sets

</specifics>

<deferred>
## Deferred Ideas

- GIF demo — v0.1.1 (too time-consuming for v0.1.0)
- Blog post announcement — user's call
- HackerNews / r/ClaudeCode submission — user's call
- Demo video — v0.1.1+

</deferred>

---

*Phase: 07-polish-docs-release*
*Context gathered: 2026-04-13 via infrastructure auto-detection*
