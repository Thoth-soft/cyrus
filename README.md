# Sekha

Zero-dependency AI memory system with hook-level rules enforcement for Claude Code.

## Why Sekha?

Every AI memory system stores rules. None of them enforce them.

Sekha hooks into Claude Code's PreToolUse event to **actually block** tool calls
that violate your rules -- the AI cannot bypass this, even with
`--dangerously-skip-permissions`. Rules live as plain markdown files in
`~/.sekha/rules/`, so your enforcement policy is as reviewable as any other
config under version control.

[30-second demo: write rule -> claude tries to run rm -rf -> blocked with message]

## Install

```bash
pip install sekha
sekha init
claude mcp add sekha -- sekha serve
```

`sekha init` wires the PreToolUse hook into `~/.claude/settings.json` and
creates `~/.sekha/` for memories and rules. `sekha doctor` will verify the
wiring whenever you want a sanity check.

## Features

- **Persistent memory** across sessions (conversations, decisions, preferences)
  stored as plain markdown files under `~/.sekha/`.
- **Rules enforcement** at the hook level -- cannot be bypassed by the AI,
  not even with `--dangerously-skip-permissions`.
- **Zero dependencies** -- pure Python stdlib, no supply chain surface.
- **Works with any MCP client** for memory (Claude Code, Cursor, Cline,
  Windsurf). Hook-level rule enforcement is Claude Code exclusive in v0.1.0.
- **6 MCP tools**: `sekha_save`, `sekha_search`, `sekha_list`, `sekha_delete`,
  `sekha_status`, `sekha_add_rule`.
- **CLI**: `sekha init`, `sekha doctor`, `sekha add-rule`, `sekha list-rules`,
  `sekha hook run/bench/enable/disable`, `sekha serve`.

## How It Works

[Diagram: Claude Code -> PreToolUse hook -> sekha hook run -> rules engine -> block or allow]

Three processes, all sharing state under `~/.sekha/`:

1. **MCP server** (long-lived, one per Claude Code session) -- serves the
   memory tools.
2. **Hook** (short-lived, per tool call) -- reads the rules directory,
   matches `tool_name` + `pattern`, blocks or warns.
3. **CLI** (one-shot) -- `init`, `doctor`, `add-rule`, `list-rules`,
   `hook bench`, and friends.

The hook is the differentiator. Rules are loaded fresh on each invocation so
edits take effect immediately, and parse errors fail loudly to stderr rather
than silently skipping a rule.

## Example Rules

See [`examples/rules/`](examples/rules/) for copy-paste-ready rules:

- `block-rm-rf.md` -- prevent `rm -rf /`, `rm -rf ~`, `rm -rf *` disasters.
- `block-force-push-main.md` -- no `git push --force` against `main`/`master`.
- `block-drop-table.md` -- refuse `DROP TABLE` in Bash-invoked SQL.
- `warn-no-tests-before-commit.md` -- nudge before `git commit` without tests.
- `warn-no-assumptions.md` -- anti-hallucination reminder on every tool call: explain before acting, no guessing, no assumptions.

Each example is a single-purpose rule with inline commentary explaining how to
tighten or loosen the pattern.

## Threat Model

**Sekha is a consistency enforcer, not a security sandbox.**

The AI could bypass a rule by using a different tool -- if you block `Bash`
with pattern `rm -rf`, the AI could use the `Write` tool to create a deletion
script and then run it with a tool you did not cover. This is intentional.
Sekha scopes rules to `tool_name` deliberately so your policy stays
inspectable instead of hiding behind an opaque allowlist.

Sekha exists to keep the AI honest about *intentions* you have made explicit,
not to prevent a malicious AI from finding creative workarounds. For that,
use OS-level sandboxing (container, VM, seccomp, etc.).

## Cross-Client Support

| Client       | Memory (MCP tools) | Rules Enforcement (hook) |
|--------------|--------------------|--------------------------|
| Claude Code  | Yes                | Yes                      |
| Cursor       | Yes                | No (no hook API)         |
| Cline        | Yes                | No                       |
| Windsurf     | Yes                | No                       |

Hook enforcement is **Claude Code exclusive** in v0.1.0. Memory tools work
everywhere MCP works.

## Docs

- [Integration test runbook](docs/hook-integration-test.md) -- verify the hook
  blocks on your machine, end to end.
- [CHANGELOG](CHANGELOG.md) -- version history.
- [Release runbook](docs/release.md) -- how maintainers cut a version.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT
