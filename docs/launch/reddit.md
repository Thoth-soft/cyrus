# Reddit launch post

Subreddit: r/ClaudeAI (primary), possibly r/LocalLLaMA if feeling brave.

## Title

I built a tool to actually block Claude Code from running destructive
commands, instead of just asking nicely

## Body

Anyone else keep telling Claude "please don't touch anything in /etc" and
then staring at a broken system five minutes later?

I shipped Sekha v0.1.0 today: https://github.com/Thoth-soft/sekha

It uses Claude Code's PreToolUse hook + `permissionDecision: "deny"` to
hard-block tool calls matching user-defined rules. As far as I can tell it's
the only AI memory system in the ecosystem that actually blocks at the hook
level instead of just seeding the system prompt and hoping. The key thing
about the PreToolUse deny path: it's enforced even when you run
`--dangerously-skip-permissions`, so the rule wins.

What works (hard enforcement):

- Regex-matchable tool-input patterns. `rm -rf`, `git push --force`,
  `DROP TABLE`, `curl | bash`, whatever you write.
- Rules are plain markdown in `~/.sekha/rules/`. Frontmatter for severity,
  tool scope, pattern; body is the message Claude sees when blocked.

What doesn't work (honest):

- Behavioral rules like "always confirm before acting" or "no guessing" stay
  prompt-level. The AI can ignore them. There's no PreReason hook and
  nothing I ship today fixes that class. README threat model explains why.

Quick facts:

- Zero runtime dependencies (pure Python stdlib)
- Python 3.11+
- Cross-platform, 9-cell CI matrix (Win/mac/Linux x 3.11/3.12/3.13)
- 337 tests
- Hook latency: p50 under 50ms on Linux/macOS, ~300ms on Windows (Python
  cold-start floor)
- MIT, pip install sekha

Install:

```
pip install sekha
sekha init
claude mcp add sekha -- sekha serve
```

Feedback I'd find valuable:

- Rule patterns you want to ship for common foot-guns
- Weird edge cases: does Claude Code behave different for you than it does
  for me?
- Other AI clients where this pattern could work (PreToolUse-equivalent hook)

Example rules in `examples/rules/` to copy-paste. Happy to answer questions
in comments.

## Tone notes (for when you edit)

- Reddit hates corporate-sounding launches. "I shipped X today" > "announcing X".
- Lead with a shared frustration, not a feature list.
- Offer something the reader can use in the first 60 seconds (the rm -rf
  reality is the hook).
- Honest limitations go near the top, not buried at the bottom.
