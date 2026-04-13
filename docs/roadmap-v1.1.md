# Sekha v1.1 Roadmap

Features deferred from v0.1.0.

## Session-state tracking (warn-based rules)

**Goal:** Enable rules that consider session history, not just the current tool call.

**Implementation sketch:**
- Hook writes to `~/.sekha/session-state/<session_id>.json` on every invocation, recording `{tool_name, tool_input, timestamp}`
- Session file pruned on `notifications/initialized` (new session) or after 24h idle
- Rule frontmatter gets a new optional field `session_condition`:
  ```yaml
  session_condition: "not_read_this_session(tool_input.file_path)"
  ```

**Enables these warn-severity rules:**

- **`warn-edit-without-read.md`** -- warn when `Edit` or `Write` targets a file that has not been `Read` in the current session. Catches the classic hallucination failure mode: AI edits based on assumed content instead of actual content.
- **`warn-edit-without-recent-read.md`** -- warn when last `Read` of the target file was more than N tool calls ago (file may have changed in between).
- **`warn-bash-without-git-status.md`** -- warn on destructive `Bash` commands (rm, mv, git reset) if no recent `git status` in the session.
- **`warn-agent-without-context.md`** -- warn when spawning an agent without passing `<files_to_read>` that cover the relevant code.

**Why warn, not block:** False positives would be too common for block-severity. New files, intentional overwrites, cases where the AI legitimately knows the file from prior context. Warn redirects without punishing.

**Opt-out:** Session-state tracking adds ~5-10ms to hook latency (one file read per call). Disable via `SEKHA_SESSION_TRACKING=0` env var.

## Other v1.1 candidates

- **Auto-save hook** (Stop event triggered) -- save conversation summaries every N messages. Deferred from v0.1.0 because Stop events during complex tasks produce junk memories. v1.1 design needs a better heuristic for "this is a clean breakpoint, save here."
- **Per-project memory directories** -- `.sekha/` alongside code, not just `~/.sekha/`. Workspace-scoped memories.
- **Memory tagging and tag-based search** -- currently tags exist in frontmatter but are not indexed.
- **Export/import memories** -- zip archive for sharing/backup.
- **`sekha pause <rule>` first-class command** -- v0.1.0 uses env var override; v1.1 writes a marker file so pause survives shell restart.
- **`updatedInput` hook output** -- not just block, but rewrite tool inputs (e.g., auto-add `-i` to `rm` to force interactive mode).

## Explicit non-goals

Same as v0.1.0:
- Vector/semantic search (adds 100MB+ deps)
- Custom compression dialects
- Knowledge graphs / temporal triples
- GUI dashboard
- Cloud sync / multi-device
- Multi-user / team-shared memory
