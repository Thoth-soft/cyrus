---
severity: block
triggers: [PreToolUse]
matches: [Bash]
pattern: 'git\s+push.*(--force|-f).*\b(main|master)\b'
priority: 90
anchored: false
---
Force-pushing to main/master rewrites shared history. Use --force-with-lease on a feature branch instead.

<!--
Use case: catch `git push --force origin main`, `git push -f main`, and their
variants before they rewrite shared history.

Known escape: a cleverer AI could `git checkout main && git push --force`
without naming the branch on the push line. This rule only catches the
explicit main/master mention -- consistent with Sekha's "consistency enforcer,
not a security sandbox" posture. If you want to also block bare
`git push --force`, add a second rule with pattern 'git\s+push.*--force' and
a lower priority so the branch-aware rule still fires first when it applies.
-->
