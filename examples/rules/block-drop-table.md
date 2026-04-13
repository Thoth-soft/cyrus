---
severity: block
triggers: [PreToolUse]
matches: [Bash]
pattern: 'DROP\s+TABLE'
priority: 90
anchored: false
---
DROP TABLE in a Bash-invoked command is almost always a mistake. Run destructive SQL through a reviewed migration instead.

<!--
Use case: catch ad-hoc `psql -c "DROP TABLE ..."`, `sqlite3 db.sqlite "DROP
TABLE ..."`, and similar one-liner SQL fired from Bash.

Scope limits: Sekha matches by tool_name, so this rule does NOT cover SQL
passed through a different MCP tool (e.g. a database-specific tool). If you
use such a tool, add a second rule with the same pattern scoped to that tool's
name. To also cover TRUNCATE and DELETE without WHERE, duplicate this file
with different patterns and priorities.
-->
