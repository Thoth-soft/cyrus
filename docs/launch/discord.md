# Anthropic Discord post

Channel: `#project-showcase` or `#community-projects` (whatever the current name
is). Keep it short - Discord channels move fast.

## Message (single post, no thread)

```
Shipped Sekha v0.1.0 today: https://github.com/Thoth-soft/sekha

It's the only AI memory system I found that actually blocks Claude Code tool
calls via PreToolUse hooks instead of just prompting "please don't."

- Rules are plain markdown in ~/.sekha/rules/
- Hook returns permissionDecision: "deny" when tool input matches your regex
- Works even with --dangerously-skip-permissions (that was the whole point)
- Zero Python deps, one-command install

Scope honesty: blocks regex-matchable tool patterns (rm -rf, git push --force,
DROP TABLE). Does NOT enforce behavioral rules like "always confirm" - those
stay prompt-level and the AI can ignore them (I proved this embarrassingly
while building it). Threat model in the README is explicit.

pip install sekha && sekha init && claude mcp add sekha -- sekha serve

MIT, feedback welcome - especially edge cases I haven't hit yet.
```

## If a mod bumps you to #off-topic or similar

Fine. Repost verbatim and move on.

## Follow-up plan

- Check replies twice a day for the first week
- Offer to help any user who hits install issues - first-week supporters matter
- Don't repost in the same channel; instead drop into specific threads where
  someone complains about Claude not following rules
