# Architecture

Sekha is small, opinionated, and has one structural idea: **three
processes, shared state through the filesystem, no IPC between them.**
This doc explains why, how, and what lives where.

If you're a contributor, read this before touching `server.py`,
`hook.py`, or `_init.py` -- the invariants here are load-bearing.

## Table of contents

- [The three processes](#the-three-processes)
- [Why no IPC](#why-no-ipc)
- [What lives in `~/.sekha/`](#what-lives-in-sekha)
- [Data flows](#data-flows)
- [Performance budget](#performance-budget)
- [Invariants contributors must respect](#invariants-contributors-must-respect)
- [What we deliberately don't do](#what-we-deliberately-dont-do)

---

## The three processes

Sekha is three mostly-independent processes. They are spawned by Claude
Code (or the user) at different lifecycles and share nothing in memory.

### 1. MCP server (`sekha.server`)

- **Spawned by** Claude Code when a session starts, once per session, via
  the `claude mcp add sekha -- python -m sekha.cli serve` registration.
- **Lives for** the duration of that Claude Code session (minutes to
  hours).
- **Talks** newline-delimited JSON-RPC 2.0 over stdio. NOT LSP-style
  Content-Length framing -- this is what killed MemPalace's MCP compat.
- **Exposes** six tools prefixed `sekha_`:
  - `sekha_save` -- write a memory file
  - `sekha_search` -- grep over `~/.sekha/`
  - `sekha_list` -- list memories in a category
  - `sekha_delete` -- remove a memory by path
  - `sekha_status` -- overview (counts, recent activity)
  - `sekha_add_rule` -- write a rule file (validated regex)
- **Writes** to `~/.sekha/<category>/*.md` for save and `~/.sekha/rules/*.md`
  for rules.
- **Reads** only what each tool call requires.

No rule evaluation happens here. No hook logic. The MCP server is a thin
dispatch layer over `sekha.storage`, `sekha.search`, `sekha.rules`.

### 2. PreToolUse hook (`sekha.hook`)

- **Spawned by** Claude Code before every tool call, via the
  `python -m sekha.cli hook run` entry in `~/.claude/settings.json`
  under `hooks.PreToolUse`.
- **Lives for** a single tool call -- typically <150ms total wall
  clock including Python interpreter startup.
- **Reads** the PreToolUse event JSON from stdin:

  ```json
  {
    "session_id": "...",
    "transcript_path": "...",
    "cwd": "...",
    "permission_mode": "default",
    "hook_event_name": "PreToolUse",
    "tool_name": "Bash",
    "tool_input": {"command": "rm -rf /tmp/demo"},
    "tool_use_id": "..."
  }
  ```

- **Loads** rules from `~/.sekha/rules/` via `sekha.rules.load_rules`.
- **Evaluates** the rules against the tool_input; the winning rule (if
  any) is returned by `sekha.rules.evaluate`.
- **Writes** to stdout one of three JSON shapes:
  - Block: `{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": "..."}}`
  - Warn: `{"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": "..."}}`
  - Allow: no output (Claude Code proceeds).
- **Writes** errors to stderr + `~/.sekha/hook-errors.log`. Fail-open
  policy: if anything inside the hook throws, the tool call is
  allowed. The hook can never lock Claude Code out.

### 3. CLI (`sekha.cli`)

- **Spawned by** the user (or by a setup script) one shot at a time.
- **Subcommands**: `init`, `doctor`, `add-rule`, `list-rules`,
  `hook run`, `hook bench`, `hook enable`, `hook disable`, `serve`.
- **Lives for** the duration of one command -- milliseconds to seconds.
- **Writes** status lines to stderr (`[OK]`, `[WARN]`, `[FAIL]`) and
  reserves stdout for machine-readable directives (the hint printed
  when auto-MCP-registration fails, the JSON blob in
  `doctor --json`).

`sekha init` is the most complex of these: it creates the `~/.sekha/`
tree, writes the default config, backs up and merges the PreToolUse
hook into `~/.claude/settings.json`, and (since v0.1.2) shells out to
`claude mcp add` to register the MCP server automatically. Every one
of those steps is idempotent -- running `sekha init` a second time
produces exactly one sekha hook entry and does not overwrite user data.

---

## Why no IPC

The three processes never talk to each other directly. They share state
through the filesystem: rules at `~/.sekha/rules/`, memories at
`~/.sekha/<category>/`, error logs at `~/.sekha/hook-errors.log`, the
kill-switch marker at `~/.sekha/hook-disabled.marker`, and so on.

This is deliberate:

1. **Crash isolation.** The MCP server can die without affecting the
   hook. A buggy hook invocation doesn't take down the server.
2. **No daemon.** We don't have to manage a background process or its
   lifecycle. The OS spawns and reaps everything.
3. **Debuggability.** Every piece of state is inspectable with `cat`,
   `grep`, and `ls`. You can diff rule changes with `git diff`. No
   sqlite inspector, no sockets to attach to.
4. **Concurrency is simple.** POSIX file semantics (atomic rename,
   advisory locks) are the only synchronization primitive. The storage
   layer uses `fcntl.flock` on Linux/macOS and `msvcrt.locking` on
   Windows.
5. **Multi-client works for free.** If Cursor starts one MCP server and
   Claude Code starts another at the same time, they both just read/write
   the same files. The hook only runs in Claude Code (since it's the only
   client with PreToolUse hooks), so there's no contention.

The tradeoff is that cross-process communication is indirect: to tell
the hook "stop applying this rule," you delete the rule file.

---

## What lives in `~/.sekha/`

```
~/.sekha/
├── config.json                    # written by `sekha init`, user-editable
├── sessions/                      # conversation memories (category)
│   └── 2026-04-14_a1b2c3d4_brief-summary.md
├── decisions/                     # lock-in decisions
├── preferences/                   # user preferences
├── projects/                      # project-specific context
├── rules/                         # hook rule files
│   ├── block-rm-rf.md
│   └── warn-no-tests-before-commit.md
├── hook-errors.log                # fail-open log; appended on every hook error
├── hook-disabled.marker           # kill-switch; created after 3 consecutive errors
└── session-state/                 # reserved for v1.1 session-state tracking
```

Every memory file follows the same shape:

```
YYYY-MM-DD_<8-char-hash>_<slug-up-to-40-chars>.md
```

Filenames are grep-friendly. Date prefix means natural chronological
sort. The hash prevents collisions on same-day same-slug saves. The
slug makes the file identifiable without opening it.

Memory files and rule files both use a restricted YAML-subset frontmatter
(hand-parsed in `sekha.storage` -- no PyYAML, no pip deps):

```markdown
---
id: a1b2c3d4
category: preferences
created: 2026-04-14T16:00:00Z
updated: 2026-04-14T16:00:00Z
tags: [postgres, database]
source: claude
---

User prefers Postgres over MySQL for new projects; reasoning is
concurrent writes and larger dataset expectations.
```

Rules use a different frontmatter shape:

```markdown
---
name: block-rm-rf
severity: block
triggers: [PreToolUse]
matches: [Bash]
pattern: 'rm\s+-rf'
priority: 50
anchored: false   # default since v0.1.1; see CHANGELOG for why
---

Catastrophic. If you really want this, run it yourself outside the AI
session.
```

---

## Data flows

### Flow A -- Save memory

```
User says "remember X" to Claude
        |
        v
Claude decides sekha_save is the right tool
        |
        v
Claude emits MCP tools/call for sekha_save
        |
        v
sekha.server.handle_tools_call -> sekha.tools.sekha_save
        |
        v
sekha.storage.save_memory(category, content, tags)
        |
        v
atomic_write to ~/.sekha/<category>/YYYY-MM-DD_<hash>_<slug>.md
        |
        v
MCP response: {"path": "...", "id": "<hash>"}
        |
        v
Claude tells user "saved"
```

### Flow B -- Search memory

Same structure, different tool: `sekha_search` -> `sekha.search.search`
-> `os.walk` over `~/.sekha/` with regex compiled and scored by
`tf * exp(-age_days/30) * filename_bonus`. Returns top-N.

### Flow C -- Hook enforcement

```
Claude calls Bash tool (e.g. rm -rf /tmp/x)
        |
        v
Claude Code spawns `python -m sekha.cli hook run` with PreToolUse event JSON on stdin
        |
        v
sekha.hook.main():
    lazy-imports sekha.rules, sekha.paths
    sekha.rules.load_rules(hook_event="PreToolUse", tool_name="Bash")
    -> [Rule("block-rm-rf", ...), Rule("warn-no-tests", ...), ...]
        |
        v
sekha.rules.evaluate(rules, tool_input)
    flatten tool_input to '{"command":"rm -rf /tmp/x"}' via json.dumps
    for each rule: rule.pattern.search(flat)
    pick winner by precedence: block > warn; then priority; then first-match
        |
        v
    If block winner: emit deny JSON to stdout, exit 0
    If warn winner: emit additionalContext JSON to stdout, exit 0
    If no match: no stdout, exit 0
        |
        v
Claude Code applies the hook's decision
```

Total budget: <50ms p50 on Linux/macOS, <150ms p95. Windows is looser
(<300ms p95) because Python interpreter cold-start is irreducible.

### Flow D -- Hook failure

```
Hook throws any exception
        |
        v
Top-level except catches it
        |
        v
Write traceback to ~/.sekha/hook-errors.log
Write short error to stderr (operator sees it)
Exit 0 without emitting deny JSON
        |
        v
Claude Code sees no block -> tool call proceeds (fail-open)
```

After 3 consecutive errors within a short window, the hook writes
`~/.sekha/hook-disabled.marker`. Subsequent invocations short-circuit
to allow. `sekha doctor` surfaces this.

---

## Performance budget

| Process | Budget | How we hit it |
|---------|--------|---------------|
| MCP server startup | <500ms | Stdlib-only imports. No `asyncio` (uses sync stdio loop to dodge asyncio's Windows stdio bugs). |
| Hook per-invocation | p50 <50ms / p95 <150ms Linux/macOS; p95 <300ms Windows | Lazy imports (top of hook.py has only `sys, json`). All heavy modules imported inside `main()`. `python -X importtime cyrus.hook` budget <30ms total. |
| Search 10k files warm | p95 <500ms | Pre-compile regex once. Short-circuit result list (`heapq.nlargest`). Stat-before-read to skip obvious non-matches. Decode only the snippet of top-N results. |
| Init | <2 seconds | Bounded filesystem ops. The only slow thing is `claude mcp add` as a subprocess; 30s timeout guard. |

The hook budget is the tightest constraint and drives every other
architectural choice. If the hook is >200ms on every tool call, users
disable Sekha. That's why lazy imports, compiled regex caches (keyed on
rules-dir mtime), and the fail-open marker are all hook-side concerns.

---

## Invariants contributors must respect

1. **Zero runtime dependencies.** `pyproject.toml` has no
   `[project.dependencies]`. Build-time deps (hatchling) are fine.
2. **`pathlib.Path` everywhere.** `os.path` is banned. This is enforced
   by the CONTRIBUTING.md checklist and is grep-able in review.
3. **Stderr-only logging.** Stdout is reserved for:
   - MCP protocol output in `server.py`
   - Hook decision JSON in `hook.py`
   - Machine-readable CLI output in `doctor --json` and the manual
     `claude mcp add` hint from `init`
   Any stray `print(` in `server.py`, `tools.py`, `jsonrpc.py`, or
   `schemas.py` is a CI lint failure.
4. **ASCII-only user-facing output.** Windows cmd.exe is cp1252.
   `[OK]`, `[WARN]`, `[FAIL]` instead of emoji. `--` instead of em-dash.
5. **Hook fails open.** Every exception path in `hook.py` ends with
   exit-0 and no block output. The hook can never lock Claude Code
   out, even if Sekha itself is broken.
6. **MCP protocol is newline-delimited JSON-RPC 2.0.** NOT Content-
   Length framed. If you're porting code from an LSP example, strip the
   framing.
7. **Atomic writes.** `storage.atomic_write` uses `os.replace` after
   `os.fsync` on a same-directory temp file. Never leaves partial files
   on crash. Test coverage: 100-parallel-write stress test on every
   OS in CI.
8. **Rules-dir mtime is the cache key.** `load_rules` memoizes
   based on `(mtime, file_count)` of `~/.sekha/rules/`. If you touch
   the cache invalidation logic, update `test_rules.TestCache`.

---

## What we deliberately don't do

- **Vector / semantic search.** Would require embedding models and
  numpy or chromadb. Install-friction killed MemPalace; we're not
  repeating the mistake. Grep is good enough for 10k files.
- **Knowledge graphs / temporal triples.** Overkill for a local
  memory system. If you need entity relationships, save the
  relationships as a memory file and let the AI reason about them.
- **Cloud sync.** Users can put `~/.sekha/` under git or Dropbox if
  they want sync. Not our problem.
- **Custom compression dialects (MemPalace's AAAK).** Clever but
  unreadable. Plain markdown wins. `cat` has to work.
- **GUI / web dashboard.** Files in a folder. Any editor works.
- **Multi-user / team-shared memory.** Sekha is single-user
  local-first. Team memory is a different product with different
  scaling and privacy constraints.
- **Behavioral rule enforcement.** Rules like "always confirm before
  acting" stay prompt-level. No PreReason hook exists in Claude Code;
  we can't enforce what the AI decides, only what the AI executes.
  See the [threat model in the README](../README.md#threat-model).
- **Daemon / persistent hook process.** Hook cold-start is our
  latency floor. A daemon would be faster but adds lifecycle
  complexity and another process to debug. If cold-start ever proves
  unacceptable, we'll introduce a compiled-rules pickle cache before
  daemonizing.

---

*Last updated: 2026-04-14 (v0.1.2). If this doc drifts from the code,
the code wins -- please file an issue or PR.*
