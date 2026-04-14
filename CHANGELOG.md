# Changelog

All notable changes to Sekha will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Changed

- **README + Threat Model clarified** -- split "what Sekha enforces" into
  two explicit categories:
  - **Hard enforcement**: regex-matchable tool-input patterns (e.g., `rm -rf`,
    `git push --force`). Survives `--dangerously-skip-permissions`.
  - **Soft reminders**: behavioral rules ("always confirm", "no assumptions")
    remain prompt-level and the AI can ignore them.
- Previous phrasing implied all rule classes were hard-enforced. That was
  inaccurate and is now corrected.

### Removed

- **`examples/rules/warn-no-assumptions.md`** -- removed from the example set.
  The rule fires on every tool call (`pattern: .*`, `matches: *`) which turned
  out to be noise rather than enforcement. Broad warn-severity rules lose
  their signal value after a few tool calls (AI tunes out repeated identical
  context). Narrow-scope warn rules or block-severity rules on specific
  patterns are the recommended approach. Lesson documented in threat model.

## [0.1.0] - 2026-04-12

### Added

- **Memory system**: save/search/list/delete memories via MCP tools, stored as
  plain markdown under `~/.sekha/`.
- **Rules engine**: load rules from `~/.sekha/rules/`, match by `tool_name` +
  `pattern`, with `block` and `warn` severities.
- **PreToolUse hook**: enforce rules at the hook level (blocks violations,
  survives `--dangerously-skip-permissions`). Kill-switch auto-disables the
  hook if it errors repeatedly in a short window.
- **MCP server**: newline-delimited JSON-RPC over stdio, 6 `sekha_` tools
  (`sekha_save`, `sekha_search`, `sekha_list`, `sekha_delete`, `sekha_status`,
  `sekha_add_rule`).
- **CLI**: `sekha init`, `sekha doctor`, `sekha add-rule`, `sekha list-rules`,
  `sekha hook run/bench/enable/disable`, `sekha serve`.
- **Zero dependencies** -- pure Python stdlib, no third-party runtime imports.
- **Cross-platform**: Windows, macOS, Linux on Python 3.11, 3.12, 3.13.

### Performance

- Hook cold-start: p50 `<` 50ms / p95 `<` 150ms on Linux/macOS (Windows p95
  `<` 300ms, platform-adjusted for Python cold-start floor).
- Search: 10k-file corpus, p95 `<` 500ms warm cache on Linux/macOS.

### Quality

- 337+ tests across a 9-cell CI matrix (3 OS x 3 Python versions).
- Fresh-VM install test on Windows, macOS, and Linux (CLI-08 release gate).
- Zero runtime dependencies enforced in `pyproject.toml`.
- TDD throughout -- tests written before implementation for every behavior.

[0.1.0]: https://github.com/Thoth-soft/sekha/releases/tag/v0.1.0
