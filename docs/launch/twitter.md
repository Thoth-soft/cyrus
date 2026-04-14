# Twitter / X launch thread

Post from your account, 4 tweets in a thread. Post tweet 1 standalone; reply
the others to form a thread.

## Tweet 1 (hook + GIF)

```
Claude Code ignored my rules one too many times.

So I hooked into PreToolUse and made it block for real.

[attach docs/demo.gif]

sekha: zero-dep AI memory system that actually blocks destructive tool calls
https://github.com/Thoth-soft/sekha
```

## Tweet 2 (mechanism, reply to #1)

```
The trick: Claude Code's PreToolUse hook can return
`permissionDecision: "deny"` and the tool call is enforced even with
--dangerously-skip-permissions.

No other memory system I found uses this. Sekha does. Rules live as plain
markdown in ~/.sekha/rules/.
```

## Tweet 3 (honest scope, reply to #2)

```
What it doesn't do: enforce behavioral rules like "always confirm" or "no
guessing." Those stay prompt-level and the AI can ignore them.

No PreReason hook exists. Sekha is a consistency enforcer, not a security
sandbox. README threat model is honest about this.
```

## Tweet 4 (install + ask, reply to #3)

```
pip install sekha
sekha init
claude mcp add sekha -- sekha serve

Python 3.11+, cross-platform, MIT, 337 tests.

If you've tried other ways to keep Claude honest, would love to hear what
worked and what didn't - especially edge cases I haven't hit yet.
```

## Hashtags (add to tweet 1 only, 2-3 max)

#ClaudeCode #AIcoding #MCP

## Timing

Same window as HN: Tuesday/Wednesday 8-10am PT. Retweet once ~6 hours later
to catch a second timezone.
