# Show HN post

## Title (<= 80 chars)

Show HN: Sekha – actually block Claude Code from running rm -rf via PreToolUse hooks

## URL

https://github.com/Thoth-soft/sekha

## Body

Leave blank (HN rewards bare Show HN posts with no body).

## Planned first comment (to seed the thread, post immediately after submission)

```
Author here. Built this after Claude Code ignored a CLAUDE.md rule one too many
times and wiped a /tmp directory I was actively using.

Quick context:
- Claude Code ships a PreToolUse hook that can return `permissionDecision: "deny"`.
  That decision is enforced even with `--dangerously-skip-permissions`. No memory
  system I looked at (MemPalace, Mem0, Letta, Zep, Basic Memory) uses it.
- Sekha loads rules as plain markdown from `~/.sekha/rules/`, runs as a short
  subprocess on every tool call, matches `tool_name` + regex against `tool_input`,
  returns the deny. Python stdlib only, zero runtime deps.
- v0.1.0 shipped today. 337 tests, 9-cell CI (Win/mac/Linux x Python 3.11/3.12/3.13),
  hook latency p50 <50ms on Linux/macOS.

Scope honesty (also in the README threat model):
- Hard enforcement only covers regex-matchable tool-input patterns (`rm -rf`,
  `git push --force`, `DROP TABLE`). Those are locked.
- Behavioral rules like "always confirm before acting" remain prompt-level and
  the AI can ignore them. I proved this embarrassingly by having the AI violate
  such a rule while building the project. That class of rule needs something
  beyond PreToolUse (a "PreReason" hook doesn't exist).

Install: `pip install sekha && sekha init && claude mcp add sekha -- sekha serve`

MIT, constructive feedback very welcome - particularly from anyone who's tried
to solve this differently and hit walls.
```

## Submission timing

- Tuesday or Wednesday
- 08:00 - 09:30 PT (peaks traffic, avoids the morning dead zone before 07:30 PT
  when fewer people vote)
- Stay online and responsive for 4-6 hours after post. Replies within 10 min
  dramatically improve thread quality.

## Response scripts for likely comments

- "Why not just use --dangerously-skip-permissions and tell Claude to be
  careful?"
  -> That was what I did before. Claude listened ~70% of the time. 30% of
  `rm -rf` invocations hitting production data is bad odds. Hook-level deny
  is not 100% either (AI can use a different tool) but it closes the
  destructive-command class of foot-guns at the boundary.

- "What about Cursor/Cline/Continue?"
  -> Memory tools (MCP) work anywhere MCP works. Hook enforcement is
  Claude Code-only in v0.1.0. The cross-client table in README makes this
  explicit.

- "Can it block X?"
  -> If X shows up as a regex match in a Claude Code tool_input, yes.
  Example rules in `examples/rules/` cover rm -rf, force-push, DROP TABLE,
  and an anti-hallucination reminder. Rules are just markdown, easy to add.

- "Does it slow everything down?"
  -> Measured p50 <50ms / p95 <150ms on Linux/macOS, p95 ~300ms on Windows
  (Python cold-start floor). `cyrus hook bench` ships as a command so you
  can measure on your own box.

- "Why Egyptian mythology?"
  -> Org is Thoth-soft (Thoth = scribe god of writing/knowledge). Sekha =
  Egyptian-etymology memory/remembrance word (caveat: not verified in English
  Wiktionary, proper Egyptological dictionary would confirm). The thematic
  fit: Thoth records, Sekha remembers.
