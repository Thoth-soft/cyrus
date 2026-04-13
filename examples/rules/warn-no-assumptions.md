---
severity: warn
triggers: [PreToolUse]
matches: ["*"]
pattern: '.*'
priority: 100
anchored: false
---

HARD RULE REMINDER: Explain first, no guessing, no assumptions.

Before this tool call, verify you are NOT:
1. Stating code behavior you have not read THIS TURN as fact
2. Assuming file contents, API shapes, or config values from memory
3. Hedging with "probably", "typically", "usually", "should be" - replace with read-then-state
4. Chaining actions beyond the user's last explicit approval

If uncertain: stop, say "I don't know - let me check", read the source, then proceed with confirmed facts.

Standing permissions cover previously-stated scope only. New scope needs new approval.

<!--
This rule fires on EVERY tool call (pattern '.*', matches '*'). It is a warn-severity
rule, so it only injects a reminder via additionalContext - it never blocks.

If it feels too noisy, bump priority down so a blocking rule can still win precedence.
To disable for a single session: SEKHA_PAUSE=warn-no-assumptions in the environment.
-->
