# Architecture Research

**Domain:** Local-first AI memory + rules enforcement system (Python stdlib, MCP stdio server + Claude Code hook)
**Researched:** 2026-04-11
**Confidence:** HIGH

Cortex is small enough that the architecture fits in your head. Three processes, one shared directory. The entire system is ~2,000 LOC of Python stdlib. This document defines the component boundaries, the data flows, and the build order.

---

## 1. System Overview

### The Three Processes

Cortex is not a single program. It is three independent Python processes that share state through the filesystem (`~/.cortex/`). They never talk to each other directly — the filesystem is the message bus.

```
+------------------------------------------------------------------------+
|                         Claude Code (host)                              |
|                                                                         |
|  +---------------------+          +--------------------------------+   |
|  |  Conversation loop  |          |  Tool executor                 |   |
|  +----------+----------+          +---------------+----------------+   |
|             |                                     |                    |
|             | stdio (JSON-RPC)                    | fork + stdin JSON  |
|             | persistent child                    | short-lived child  |
|             v                                     v                    |
|  +---------------------+          +--------------------------------+   |
|  |  cortex.server      |          |  cortex.hook                   |   |
|  |  (MCP server)       |          |  (PreToolUse hook, per-call)   |   |
|  |  long-lived         |          |  target: <100ms                |   |
|  +----------+----------+          +---------------+----------------+   |
|             |                                     |                    |
+-------------|-------------------------------------|--------------------+
              |                                     |
              | reads + writes                      | reads only
              v                                     v
      +-------------------------------------------------------+
      |                     ~/.cortex/                        |
      |                                                       |
      |  sessions/   decisions/   preferences/   projects/    |
      |  rules/      index/       config.json                 |
      +-------------------------------------------------------+
                              ^
                              |
                              | reads + writes (rare, manual)
                              |
                    +---------+----------+
                    |   cortex CLI       |
                    |   (init, add-rule) |
                    |   one-shot         |
                    +--------------------+
```

**Key property:** the MCP server and the hook never communicate. They both read the same directory. This is deliberate — no shared memory, no IPC protocol, no race-prone synchronization beyond POSIX file semantics. If the hook crashes, the server keeps running. If the server crashes, the hook keeps enforcing rules.

### Component Responsibilities

| Component | Process model | Responsibility | Reads | Writes |
|-----------|---------------|----------------|-------|--------|
| `cortex.server` | Long-lived, one per Claude Code session | Serve the 4-6 MCP tools (save, search, list, delete, status, add-rule) | All of `~/.cortex/` | `sessions/`, `decisions/`, `preferences/`, `rules/` |
| `cortex.hook` | Short-lived, one per tool call | Read rules, inject context, block if violated | `rules/`, `config.json` | Nothing (or `logs/hook.log` for debugging) |
| `cortex.cli` | One-shot, user-invoked | `init`, `add-rule`, `doctor`, `list-rules` | `~/.cortex/` | `~/.cortex/` (init creates the tree) |
| `cortex.storage` | Library, not a process | File I/O primitives: atomic write, frontmatter parse, path resolution | — | — |
| `cortex.search` | Library, not a process | Regex scan with scoring | — | — |
| `cortex.rules` | Library, not a process | Load rules, match triggers, evaluate block/warn | — | — |

The three libraries (`storage`, `search`, `rules`) are pure functions shared by the three processes. This is the key to keeping the codebase small: the server, hook, and CLI are thin entry points that glue the libraries to their respective I/O models.

---

## 2. Directory Layout — `~/.cortex/`

This is the single source of truth. Everything else in the system is a view onto this directory.

```
~/.cortex/
|
+-- config.json                       # global settings (auto-save cadence, hook enabled, etc.)
|
+-- sessions/                         # conversation transcripts / summaries
|   +-- 2026-04-11_a3f2_refactor-auth-flow.md
|   +-- 2026-04-11_b7c1_debug-mcp-handshake.md
|   +-- 2026-04-10_d9e4_initial-setup.md
|
+-- decisions/                        # architectural decisions, tradeoffs
|   +-- 2026-04-11_use-markdown-over-sqlite.md
|   +-- 2026-04-09_python-stdlib-only.md
|
+-- preferences/                      # user habits, style, conventions
|   +-- commit-message-style.md
|   +-- code-review-tone.md
|   +-- always-confirm-before-action.md
|
+-- projects/                         # project-scoped knowledge
|   +-- cortex/
|   |   +-- 2026-04-11_mcp-handshake-quirks.md
|   |   +-- 2026-04-10_stdio-buffering-gotcha.md
|   +-- leetcode-articles/
|       +-- 2026-04-08_diagram-style-guide.md
|
+-- rules/                            # enforcement rules (read by hook)
|   +-- 001_never-force-push-main.md
|   +-- 002_confirm-before-destructive-bash.md
|   +-- 003_no-emoji-in-svg.md
|   +-- 010_always-use-absolute-paths.md
|
+-- index/                            # optional cache (built on demand)
|   +-- keywords.json                 # inverted index: term -> [file paths]
|   +-- mtimes.json                   # file -> last-modified, for cache invalidation
|
+-- logs/                             # stderr drain for server + hook (optional)
|   +-- server.log
|   +-- hook.log
|
+-- .lock                             # advisory lock for concurrent writes
```

### Filename Conventions

Filenames are optimized for **grep-friendliness and chronological sort**. The filename itself is a first-class index.

Format: `YYYY-MM-DD_<short-id>_<slug>.md`

- `YYYY-MM-DD` — sortable date prefix. `ls sessions/` gives chronological order for free.
- `<short-id>` — optional 4-hex-char disambiguator when multiple memories land on the same day (random from `secrets.token_hex(2)`).
- `<slug>` — human-readable kebab-case topic. Max 50 chars. Lowercase, ASCII-only (stripped via `unicodedata.normalize('NFKD', ...).encode('ascii', 'ignore')`).
- `.md` — always markdown.

Why this scheme:
- `grep -r "auth" ~/.cortex/sessions/` finds topics by filename alone, no content scan needed for common queries.
- Chronological prefix means **recency boost is free** — sort descending by filename.
- No timestamps-to-seconds (like `2026-04-11T14-32-08`) — they are noise for humans and rarely disambiguate in practice.
- IDs are short (4 hex chars = 65k possibilities) — collision probability is negligible within a single day.

**Rule files** use a numeric priority prefix instead: `NNN_<slug>.md`. The prefix (`001`, `010`, `099`) lets users force ordering without frontmatter fiddling. Lower number = higher priority = evaluated first. Recommended ranges: `001-099` user rules, `100-199` project rules, `200-299` team/shared rules.

### Frontmatter vs Filename — What Goes Where

| Metadata | Location | Rationale |
|----------|----------|-----------|
| Date | Filename | Grep-friendly, sortable |
| Category | **Folder** (sessions/decisions/…) | Grep can target folders; no need to scan all files to filter by category |
| Topic slug | Filename | Discoverable via `ls` |
| Priority (rules only) | Filename prefix | `ls` shows order |
| Tags | Frontmatter | Many-to-one; filename can only carry one primary slug |
| Project | Frontmatter + folder (`projects/<name>/`) | Folder for discovery, frontmatter for cross-referencing |
| Severity (rules) | Frontmatter | Non-grep-obvious but critical for hook logic |
| Triggers/matches (rules) | Frontmatter | Structured data the hook must parse |
| Created-by (human/AI) | Frontmatter | Rarely queried, doesn't belong in filename |

**Guiding principle:** if the field is used by `ls`, `grep`, or humans scanning a folder, it goes in the filename. If it's structured data the code must parse, it goes in frontmatter.

---

## 3. Storage Format — Markdown Files

Every Cortex file is a markdown document with optional YAML-like frontmatter.

### Memory file example (`sessions/2026-04-11_a3f2_refactor-auth-flow.md`)

```markdown
---
id: a3f2
created: 2026-04-11T14:32:08Z
category: session
project: equra-ai-backend
tags: [auth, jwt, refactor]
summary: Discussed moving auth flow from session cookies to JWT bearer tokens.
---

# Refactor auth flow

## What happened
We reviewed the current cookie-based auth in `equra-ai-backend/auth/session.py`
and decided to migrate to JWT bearer tokens to simplify the mobile client.

## Decisions
- Use RS256 (asymmetric) so mobile can verify without the secret.
- Keep refresh tokens server-side.
- Migration window: 2 weeks, dual-stack both cookie and bearer.

## Open questions
- Token revocation strategy — denylist vs short TTL?
- Where does key rotation live?
```

### Rule file example (`rules/002_confirm-before-destructive-bash.md`)

```markdown
---
id: confirm-destructive-bash
severity: block
triggers: [PreToolUse]
matches: [Bash]
pattern: "(?i)(rm -rf|mkfs|dd if=|:\\(\\)\\{|shutdown|reboot)"
message: |
  HARD RULE: Destructive shell commands require explicit user confirmation.
  You must explain exactly what the command will do and wait for "yes" before running.
---

# Confirm before destructive bash commands

Commands that can destroy data or system state must not run without explicit
user confirmation. This includes `rm -rf`, filesystem formatting, `dd`,
fork bombs, and system power commands.

**Why:** Irreversible operations caused real incidents. The AI cannot be trusted
to judge "obvious" intent — ask first, always.
```

### The "YAML" Problem — Stdlib Has No YAML Parser

**Important constraint:** Python stdlib has no YAML parser. PyYAML is a pip dependency and Cortex is stdlib-only. This forces a design decision.

**Recommendation: restricted frontmatter, parsed by a hand-rolled 80-line function.**

Allowed frontmatter syntax (strict subset):

1. Opening `---` and closing `---` on their own lines
2. `key: value` pairs (value parsed as string, int, bool, or ISO date)
3. Inline arrays: `tags: [auth, jwt, refactor]` — parsed with `re.split(r',\s*')` after stripping brackets
4. Multi-line strings with `|` block scalar (preserved verbatim until next top-level key)
5. No nested objects, no anchors, no flow maps, no custom tags

This covers every realistic use case for Cortex metadata and can be parsed by a single Python function with `re` + string slicing. If a user wants richer structured data, they put it in the body as markdown. Keeping frontmatter trivial is a feature — it prevents scope creep and keeps the implementation portable.

Parse contract (`cortex.storage.parse_frontmatter`):

```python
def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Returns (metadata_dict, body_str). If no frontmatter, returns ({}, text)."""
```

Write contract (`cortex.storage.dump_frontmatter`):

```python
def dump_frontmatter(metadata: dict, body: str) -> str:
    """Serializes back to the restricted subset. Raises ValueError on unserializable values."""
```

### Long Memories

If a memory exceeds ~50KB, split it:

- `2026-04-11_a3f2_big-refactor.md` — the summary and index
- `2026-04-11_a3f2_big-refactor.parts/01-overview.md`
- `2026-04-11_a3f2_big-refactor.parts/02-migration-plan.md`

The main file includes a `parts:` frontmatter array pointing at the siblings. Search still works — it scans both the main file and the parts directory. This is rarely needed in practice; most memories are under 5KB.

### Atomic Writes

All writes go through `cortex.storage.atomic_write(path, content)`:

1. Write to `path.tmp.<pid>`
2. `os.replace(tmp, path)` (atomic on both POSIX and Windows for same-filesystem moves)
3. `fsync` the parent directory on POSIX (best-effort on Windows)

This protects against crash-during-write corruption. The `.tmp.<pid>` suffix allows safe cleanup of orphaned temp files on startup.

### Concurrent Writes

Two processes (server + CLI) may write simultaneously. Cortex uses an advisory lock on `~/.cortex/.lock`:

- POSIX: `fcntl.flock(fd, LOCK_EX)` — stdlib
- Windows: `msvcrt.locking(fd, LK_NBLCK, 1)` — stdlib

A tiny wrapper `cortex.storage.filelock()` picks the right one at import time. Lock is held only during the atomic write (~ms), so contention is effectively zero.

The hook never writes, so it never needs the lock — another reason the read-only-hook design is valuable.

---

## 4. Search Implementation

### Approach: Pure-Python Regex Scan with Scoring

Requirements:
- Zero dependencies
- Cross-platform (no `grep` subprocess — Windows doesn't ship it)
- Fast enough for 10k files
- Ranked results (term frequency + recency)

**Implementation:** `os.walk` + `re.compile` + in-process scoring. No subprocess, no shell.

```python
# cortex/search.py (sketch)
import os, re, time
from pathlib import Path

def search(root: Path, query: str, limit: int = 20) -> list[dict]:
    # Tokenize query; compile regex once
    terms = [re.escape(t) for t in query.lower().split() if t]
    if not terms:
        return []
    pattern = re.compile("|".join(terms), re.IGNORECASE)

    results = []
    for dirpath, _, files in os.walk(root):
        for name in files:
            if not name.endswith(".md"):
                continue
            path = Path(dirpath) / name
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue

            matches = pattern.findall(text)
            if not matches:
                continue

            # Scoring: term frequency + recency boost + filename match bonus
            tf = len(matches)
            age_days = (time.time() - path.stat().st_mtime) / 86400
            recency = 1.0 / (1.0 + age_days / 30)   # half-life ~30 days
            name_bonus = 2.0 if pattern.search(name) else 1.0
            score = tf * recency * name_bonus

            results.append({
                "path": str(path),
                "score": score,
                "snippet": _extract_snippet(text, pattern),
            })

    results.sort(key=lambda r: -r["score"])
    return results[:limit]
```

### Performance — Is This Fast Enough?

Rough numbers for a pure-Python scan of 10,000 markdown files (avg 3KB each = ~30MB total):

- Modern SSD, cold cache: ~500ms-1.5s (I/O bound on first run)
- Warm OS file cache: ~200-400ms (CPU bound on regex)
- Per-file overhead: ~30-50µs (stat + open + read + scan)

**Verdict:** acceptable for 10k files as an interactive tool call. Not acceptable if we ran it on every keystroke, but MCP tool calls happen at human speed (once per query). Users will feel it as "instant."

For context: GNU `grep` on the same corpus takes ~50-150ms. We are 3-10x slower than native grep. That's the tax for stdlib-only + portability, and it's the right tradeoff. **Confidence: MEDIUM** — these are extrapolations from similar stdlib workloads, not a direct benchmark. Validate early in Phase 2.

### Optional Index (Phase 3+)

If we hit a real performance wall (or users grow past 10k files), add an **inverted index** cache:

- `~/.cortex/index/keywords.json` — `{term: [path, path, ...]}` for top ~5k most frequent terms
- `~/.cortex/index/mtimes.json` — `{path: mtime}` for invalidation
- Rebuild lazily: on search, check mtimes; if any file changed, re-index only the changed files

This gets you 10-30x speedup for large corpora at the cost of ~200 LOC and ~10% disk overhead. **Do not build this in v1.** Start with the naive scan, measure, add the index only if users complain.

### What NOT To Do

- **Do not shell out to `grep`.** Not portable (Windows), not stdlib, breaks the zero-dep promise.
- **Do not use `glob` + `re.finditer` without early exit.** Use `pattern.findall` or scan line-by-line if memory matters.
- **Do not cache compiled patterns globally.** `re._MAXCACHE` already handles this. Manual caches leak.
- **Do not walk the tree on every call and also parse frontmatter.** Frontmatter parsing costs 10x the regex scan. Only parse it for the top-N ranked results when building the response.

---

## 5. MCP Server — Process Lifecycle & Internals

### Lifecycle

```
Claude Code session starts
    |
    v
Claude Code reads ~/.claude/settings.json "mcpServers.cortex"
    |
    v
Claude Code spawns: python -m cortex.server
    (inherits stdin/stdout/stderr)
    |
    v
cortex.server.main():
    - Initialize ~/.cortex/ if missing (idempotent, same logic as cortex init)
    - Open logs/server.log for stderr drain (optional)
    - Enter the JSON-RPC read loop on stdin
    |
    v
Claude Code sends "initialize" request
    |
    v
Server responds with { protocolVersion, capabilities: {tools:{}}, serverInfo }
    |
    v
Claude Code sends "initialized" notification
    |
    v
Server is ready. Loop:
    - Read one line from stdin (blocking)
    - Parse as JSON-RPC
    - Dispatch to handler (tools/list, tools/call, ping)
    - Write response line to stdout
    |
    v
Claude Code session ends
    |
    v
Claude Code closes stdin (EOF)
    |
    v
Server read loop exits, cleanup runs, process exits 0
```

### Transport: Newline-Delimited JSON-RPC 2.0 over stdio

Per the MCP spec, messages are newline-delimited JSON and MUST NOT contain embedded newlines. This matches what Claude Code actually speaks (confirmed by the MemPalace debugging from the project context).

The entire read loop is this:

```python
# cortex/server.py (core loop, simplified)
import sys, json

def run():
    while True:
        line = sys.stdin.readline()
        if not line:            # EOF -- client closed stdin
            return
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
            response = dispatch(msg)
        except Exception as e:
            log_stderr(f"request failed: {e!r}")
            response = jsonrpc_error(msg.get("id"), -32603, str(e))
        if response is not None:   # notifications get no response
            sys.stdout.write(json.dumps(response, separators=(",", ":")) + "\n")
            sys.stdout.flush()
```

### Critical Stdio Gotchas

These are the bugs that bit MemPalace and must NOT bite Cortex:

1. **Never print to stdout.** Stdout is the protocol channel. Any stray `print()` corrupts JSON-RPC. Use `sys.stderr` for everything (or the `logging` module configured to stderr).
2. **Flush after every write.** Python buffers stdout by default (especially when stdout is a pipe, not a TTY). Forgetting `sys.stdout.flush()` hangs the client forever. Alternative: run with `python -u` or set `PYTHONUNBUFFERED=1` in the server launch command.
3. **UTF-8 explicitly on Windows.** Windows defaults stdin/stdout to cp1252 and text mode, which mangles non-ASCII and eats `\r`. Fix at the top of `main()`:
   ```python
   import sys, io
   if hasattr(sys.stdin, "reconfigure"):
       sys.stdin.reconfigure(encoding="utf-8", newline="")
       sys.stdout.reconfigure(encoding="utf-8", newline="", write_through=True)
   ```
4. **No embedded newlines in message JSON.** Multi-line strings in tool arguments (like saved memory bodies) must be escaped as `\n` — `json.dumps` already does this, but custom string builders do not.

### Concurrency Model: Single-Threaded Synchronous

MCP tool calls from Claude Code are **sequential per session** — the client waits for a response before sending the next request. A multi-threaded server adds complexity without benefit. Cortex uses a simple blocking read loop. This also eliminates the entire class of race conditions around shared state.

If a future feature needs background work (e.g., async auto-save), it can be a worker thread that only touches its own queue, with the main loop never blocking on it.

### State Between Calls: Re-Read, Don't Cache

For v1: **the server holds zero in-memory state beyond the JSON-RPC loop.** Every tool call re-reads files from disk.

Why:
- Disk is fast. Reading a single markdown file is ~50µs on a modern SSD.
- Zero cache invalidation bugs. The user may `vim` a rule file directly — the server sees the change on the next call with no coordination.
- The CLI can write to `~/.cortex/` while the server is running; the server picks up changes without a restart.

When to reconsider: if `list` or `status` starts showing latency over 100ms with large corpora, add a lightweight in-memory `{path: mtime}` map and re-read only changed files. This is a Phase 3+ optimization.

### Graceful Shutdown

1. Claude Code closes our stdin (EOF)
2. `readline()` returns empty string
3. Loop exits
4. `atexit` handlers run: close log files, release any held locks
5. `sys.exit(0)`

If the process is killed (SIGTERM, SIGKILL, Windows taskkill), the advisory lock is auto-released by the OS and any `.tmp.<pid>` files get cleaned up on next startup. No recovery procedure needed.

### The Minimum JSON-RPC Methods to Implement

For a working MCP server, we need exactly these methods:

| Method | Direction | Purpose |
|--------|-----------|---------|
| `initialize` | client → server, request | Handshake; server advertises `tools` capability |
| `notifications/initialized` | client → server, notification | Client ready; no response |
| `tools/list` | client → server, request | Return the tool schemas |
| `tools/call` | client → server, request | Dispatch to `save`, `search`, `list`, `delete`, `status`, `add_rule` |
| `ping` | client → server, request | Keepalive; return `{}` |
| `notifications/cancelled` | client → server, notification | Cancel an in-flight call (can be a no-op in v1) |

That is the entire protocol surface. ~200 lines of Python.

---

## 6. Rules Enforcement Hook — The Core Differentiator

This is the part that must be correct. Everything else is storage plumbing; this is the feature that justifies the project.

### Invocation

Claude Code reads `~/.claude/settings.json` (or `.claude/settings.json` for project-local) and matches tool calls against configured hooks:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "python -m cortex.hook",
            "timeout": 5
          }
        ]
      }
    ]
  }
}
```

`cortex init` writes this block into the user's Claude Code settings (with a backup first). The matcher is `*` because Cortex rules themselves declare which tools they apply to — centralizing the matching in one place.

### Hook Input (stdin, HIGH confidence — from official docs)

Claude Code sends a JSON object on stdin:

```json
{
  "session_id": "abc123",
  "transcript_path": "/Users/mohab/.claude/projects/.../session.jsonl",
  "cwd": "/home/user/project",
  "permission_mode": "default",
  "hook_event_name": "PreToolUse",
  "tool_name": "Bash",
  "tool_input": {
    "command": "rm -rf /",
    "description": "clean up",
    "timeout": 30000,
    "run_in_background": false
  },
  "tool_use_id": "toolu_01ABC"
}
```

### Hook Output (stdout JSON + exit code, HIGH confidence)

**To allow (exit 0, any of these are valid):**
```json
{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow"}}
```
Or just exit 0 with no stdout (implicit allow).

**To allow with injected context (the "warn" severity path):**
```json
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "allow",
    "additionalContext": "REMINDER: User prefers absolute paths in bash commands."
  }
}
```

**To block (exit 0, structured deny — the preferred path):**
```json
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": "HARD RULE: Destructive shell commands require explicit user confirmation. Rule: ~/.cortex/rules/002_confirm-before-destructive-bash.md"
  }
}
```

Why `"deny"` + exit 0 rather than exit 2: `deny` shows the reason **to Claude** (so it can correct course), while exit 2 shows stderr to Claude but is a more abrupt failure mode. For user-friendly blocking with actionable explanations, use `permissionDecision: "deny"`.

Exit 2 is reserved for **hook crashes** that should block rather than fail open. If `cortex.hook` itself throws an unexpected exception, exit 2 with a stderr message is the safe default.

### Hook Logic

```python
# cortex/hook.py (core flow)
import sys, json, re, time
from pathlib import Path
from cortex.rules import load_rules
from cortex.storage import cortex_home

def main() -> int:
    start = time.perf_counter()
    try:
        event = json.loads(sys.stdin.read())
    except Exception:
        # Malformed input: fail open, let the tool proceed
        return 0

    tool_name = event.get("tool_name", "")
    tool_input = event.get("tool_input", {})
    hook_event = event.get("hook_event_name", "")

    rules = load_rules(cortex_home() / "rules", hook_event, tool_name)

    blocked = []
    context_lines = []

    for rule in rules:
        if rule.matches(tool_name, tool_input):
            if rule.severity == "block":
                blocked.append(rule)
                break  # first-match-wins for blocks
            elif rule.severity == "warn":
                context_lines.append(f"RULE: {rule.message}")

    elapsed_ms = (time.perf_counter() - start) * 1000
    if elapsed_ms > 50:
        print(f"cortex.hook slow: {elapsed_ms:.0f}ms", file=sys.stderr)

    if blocked:
        rule = blocked[0]
        out = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": f"{rule.message}\n(rule: {rule.path.name})",
            }
        }
        sys.stdout.write(json.dumps(out))
        return 0

    if context_lines:
        out = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "allow",
                "additionalContext": "\n".join(context_lines),
            }
        }
        sys.stdout.write(json.dumps(out))
        return 0

    return 0  # silent allow

if __name__ == "__main__":
    sys.exit(main())
```

### Rule Matching Logic

A rule matches a tool call when **all** of these are true:

1. `rule.triggers` contains the current `hook_event_name` (usually `PreToolUse`)
2. `rule.matches` contains `tool_name` OR contains `"*"`
3. If `rule.pattern` is set, it matches the stringified `tool_input` (e.g., the bash command, the file path, the write content)

The `pattern` field is optional — a rule with just `severity` and `matches: [Bash]` blocks ALL bash calls. A rule with `matches: [Bash]` AND `pattern: "rm -rf"` blocks only matching commands.

Severity semantics:
- `block` — return `permissionDecision: "deny"`. Tool does not run. Claude sees the reason and must adjust.
- `warn` — return `permissionDecision: "allow"` with `additionalContext`. Tool runs, but Claude sees the rule text in its context window.

### Performance Budget — Under 100ms

The hook runs **before every tool call**. If it takes 200ms, every Edit, Read, Bash, and Write feels sluggish. Budget:

| Step | Budget | Actual (target) |
|------|--------|-----------------|
| Python interpreter cold start | ~30-50ms (CPython on SSD) | Unavoidable |
| Import cortex modules | ~10-20ms | Keep imports minimal |
| `sys.stdin.read()` + JSON parse | <5ms | Trivial |
| Walk `~/.cortex/rules/`, read files | ~5-15ms (typical: 10-30 rule files) | I/O bound |
| Parse frontmatter + compile patterns | ~5-10ms | Regex compilation is the tax |
| Match loop | <1ms | Tiny |
| **Total** | **<100ms** | ~55-100ms |

**The interpreter cold-start is 30-50ms and unavoidable with pure-Python stdlib.** This is the hard floor. Optimization levers if we hit the ceiling:

1. **Lazy imports.** Only import what the hook path needs. No `cortex.server`, no `cortex.search`.
2. **Skip parse if no applicable rules.** After reading the rules directory, bail early if no rule declares the current `tool_name` in its filename prefix (read the first 2KB of each file instead of the whole thing).
3. **Rule compilation cache.** Store compiled patterns in `~/.cortex/index/rules.pickle` keyed by rules-dir mtime. Invalidate on any rule file change. Saves ~15ms per call.
4. **Last resort: daemonize the hook.** Keep a long-lived `cortex.hook-daemon` and have the hook entry point be a tiny socket client (~5ms). This is a large complexity jump — avoid unless profiling proves necessary.

Fail-open philosophy: if the hook exceeds its internal 80ms budget (self-measured via `time.perf_counter`), **allow the tool call and log the slowdown**. Users should not feel rule enforcement as a tax on productivity.

### What the Hook Does NOT Do

- **Does not write to `~/.cortex/`.** Read-only. Eliminates all write contention with the server.
- **Does not call the MCP server.** No IPC. The hook is a standalone subprocess.
- **Does not maintain persistent state.** Every invocation is a fresh process.
- **Does not log verbose output on the happy path.** Only logs when it blocks, warns, or runs slow.

---

## 7. Package Structure

```
cortex/                          # the Python package
|
+-- __init__.py                  # __version__ only; no side effects
+-- __main__.py                  # `python -m cortex` -> cli.main()
|
+-- cli.py                       # cortex init / add-rule / doctor / list-rules
|
+-- server.py                    # MCP server entry point (python -m cortex.server)
+-- hook.py                      # PreToolUse hook entry point (python -m cortex.hook)
|
+-- storage.py                   # file I/O, frontmatter, atomic write, filelock
+-- search.py                    # regex search + scoring
+-- rules.py                     # Rule class, load_rules, match logic
|
+-- jsonrpc.py                   # tiny JSON-RPC 2.0 helpers (dispatch table, error codes)
+-- tools.py                     # the 6 MCP tool handlers (save/search/list/delete/status/add_rule)
+-- schemas.py                   # JSON schemas for the 6 tools (dicts, no pydantic)
|
+-- paths.py                     # cortex_home(), platform-aware ~/.cortex/ resolution
+-- logutil.py                   # configure stderr logging (no stdout)
|
+-- tests/                       # stdlib unittest, not pytest (zero dep)
|   +-- test_storage.py
|   +-- test_search.py
|   +-- test_rules.py
|   +-- test_hook.py
|   +-- test_server.py
|   +-- fixtures/
|       +-- sample_cortex_home/...
|
+-- templates/                   # files copied into ~/.cortex/ on `cortex init`
    +-- config.json
    +-- rules/
    |   +-- 001_example-warning-rule.md
    +-- README.md                # dropped into ~/.cortex/ explaining the layout
```

### Notes on Package Decisions

- **No `hooks/` bash wrapper directory.** Claude Code hooks accept a shell command directly. `"python -m cortex.hook"` works on every platform that has `python` on PATH. Avoids the Windows-bash-script cross-platform nightmare.
- **`tools.py` is separate from `server.py`.** The tool handlers are pure functions `(args: dict) -> dict`. `server.py` handles JSON-RPC framing; `tools.py` handles business logic. This makes the tool handlers unit-testable without spawning a subprocess.
- **`schemas.py` is hand-written dicts, not pydantic.** The MCP spec accepts JSON Schema as dicts. Pydantic is a dep. Hand-written schemas are ~100 lines total.
- **`jsonrpc.py` is a minimal helper, not a framework.** ~50 lines. Methods: `parse_request`, `make_response`, `make_error`, `dispatch(handlers, msg)`.
- **Tests use stdlib `unittest`, not pytest.** The project ships with zero dependencies; pytest would be a dev-dependency, which is fine, but `unittest` is sufficient and keeps CI simple.

### Install Surface

```
pip install cortex-memory
# creates two console_scripts entry points:
#   cortex            -> cortex.cli:main
#   (and `python -m cortex.server` / `python -m cortex.hook` work without console_scripts)
```

`pyproject.toml` declares no runtime dependencies. `setuptools` only. Python >= 3.9 (for `pathlib.Path.replace`, `dict | dict` union operator, `functools.cache`).

---

## 8. Data Flow for the Three Primary Interactions

### Flow A: Save a memory (MCP `save` tool call)

```
User: "Remember that we decided to use JWT instead of cookies."
    |
    v
Claude (conversation loop) decides to call the cortex save tool
    |
    v
Claude serializes: {"method":"tools/call","params":{"name":"save","arguments":{...}}}
    |
    v                                                  stdio pipe (JSON-RPC)
+--------+                                          +------------------------+
| Claude |---- line with JSON-RPC request  -------->|   cortex.server loop   |
| Code   |                                          +------------+-----------+
+--------+                                                       |
                                                                 v
                                                    jsonrpc.dispatch -> tools.save
                                                                 |
                                                                 v
                                          storage.slugify("jwt-vs-cookies")
                                          storage.make_path(category="decisions")
                                                                 |
                                                                 v
                                          storage.filelock() (acquire ~/.cortex/.lock)
                                          storage.atomic_write(path, frontmatter+body)
                                          storage.filelock() (release)
                                                                 |
                                                                 v
                                          returns {"path": "decisions/2026-04-11_...md"}
                                                                 |
+--------+                                                       v
| Claude |<---- JSON-RPC response line  ----------+  sys.stdout.write + flush
| Code   |                                        +------------+-----------+
+--------+                                                                  
    |
    v
Claude says "Saved to ~/.cortex/decisions/2026-04-11_...md"
```

### Flow B: Search memories (MCP `search` tool call)

```
User: "What did we decide about auth?"
    |
    v
Claude calls search tool with {"query": "auth jwt"}
    |
    v
cortex.server -> tools.search -> cortex.search.search(root, "auth jwt")
    |
    v
os.walk(~/.cortex/)
    for each .md file:
        read text
        regex match count
        compute score = tf * recency * name_bonus
        keep top 20
    |
    v
For top 20 hits: parse frontmatter, extract summary + snippet
    |
    v
Return JSON array: [{"path":..., "score":..., "summary":..., "snippet":...}, ...]
    |
    v
Claude presents the results to the user
```

### Flow C: Rules check on a tool call (THE differentiator)

```
User: "Delete the old session files"
    |
    v
Claude decides to call Bash with command "rm -rf ~/.cortex/sessions/*"
    |
    v
BEFORE the Bash tool runs, Claude Code fires the PreToolUse hook chain
    |
    v                                            stdin JSON (one-shot)
+--------+                                    +------------------------+
| Claude |--- spawn: python -m cortex.hook -->|   cortex.hook main()   |
| Code   |    (with hook input on stdin)      +------------+-----------+
+--------+                                                 |
                                                           v
                                                json.load(sys.stdin)
                                                 event = {tool_name: "Bash",
                                                          tool_input: {command: "rm -rf ..."}}
                                                           |
                                                           v
                                                rules = load_rules(~/.cortex/rules,
                                                                   "PreToolUse", "Bash")
                                                           |
                                                           v
                                                for rule in rules:
                                                    if rule.matches(tool, input):
                                                        if rule.severity == "block":
                                                            BLOCKED
                                                           |
                                                           v
                                                Rule 002 matches pattern "rm -rf"
                                                severity: block
                                                           |
                                                           v
                                                print(json.dumps({
                                                  "hookSpecificOutput": {
                                                    "hookEventName": "PreToolUse",
                                                    "permissionDecision": "deny",
                                                    "permissionDecisionReason":
                                                      "HARD RULE: confirm before..."
                                                  }
                                                }))
                                                exit(0)
                                                           |
+--------+                                                 v
| Claude |<------ stdout JSON + exit code -----+-----------+
| Code   |
+--------+
    |
    v
Claude Code sees permissionDecision: "deny" and REFUSES to execute Bash
    |
    v
Claude receives the denial reason in its context
    |
    v
Claude says: "I was about to delete those files, but a rule requires
             confirmation first. Should I proceed with rm -rf ~/.cortex/sessions/*?"
    |
    v
User: "yes"
    |
    v
Claude re-attempts Bash. Hook re-fires. But now the rule is satisfied
(e.g., user said yes, or Claude rephrases with a safer command).
```

This is the feature that justifies the project. Every other component exists to support this flow.

---

## 9. Build Order

The dependency graph dictates the build order. Start at the leaves (no dependencies) and work toward the roots (many dependencies).

```
   storage.py, paths.py, logutil.py
                 |
      +----------+----------+
      |                     |
   search.py              rules.py
      |                     |
      +----------+----------+
                 |
         +-------+--------+
         |                |
     tools.py          hook.py
         |
     server.py (uses tools.py + jsonrpc.py)
         |
      cli.py
```

### Recommended Phase Sequence

**Phase 1 — Foundation (the libraries)**
Build `storage.py`, `paths.py`, `logutil.py`. This is the bedrock: frontmatter parser, atomic write, filelock, cortex_home resolution. Unit-test heavily. No external interfaces yet.
- **Success:** You can write and read a cortex memory file from a Python REPL.
- **Risk:** Frontmatter parser bugs. Cover these cases in tests before moving on.

**Phase 2 — Search**
Build `search.py`. Depends on `storage.py` for frontmatter extraction on top-N hits. Benchmark against a 10k-file test corpus.
- **Success:** `python -c "from cortex.search import search; print(search(path, 'query'))"` returns ranked results in under a second.
- **Risk:** Performance surprises. Measure with `time.perf_counter`, not intuition.

**Phase 3 — Rules engine**
Build `rules.py`. Depends on `storage.py` for rule loading. Pure logic — no I/O beyond reading the rules directory.
- **Success:** Unit tests cover all severity/matches/pattern combinations.
- **Risk:** Matching semantics. Write the tests first.

**Phase 4 — Hook entry point**
Build `hook.py` using the Phase 3 rules engine. This is the **user-visible differentiator** and should ship as early as possible. Test it by running `echo '{...}' | python -m cortex.hook` manually.
- **Success:** You can wire the hook into Claude Code via `~/.claude/settings.json` and watch it block a command. **Dogfood immediately.**
- **Risk:** Stdio encoding on Windows, timing budget. Measure.

**Phase 5 — MCP server skeleton**
Build `jsonrpc.py`, `schemas.py`, `tools.py`, `server.py`. Depends on `storage.py` and `search.py`. Implement tools in this order: `status` (trivial), `list`, `search`, `save`, `delete`, `add_rule`. Each tool is a ~20-50 line function.
- **Success:** Claude Code connects to the server, calls `tools/list`, calls each tool, and gets correct responses. Memories actually land on disk.
- **Risk:** MCP protocol framing bugs (stdout buffering, UTF-8 on Windows). Lean on the hook's stdio work from Phase 4.

**Phase 6 — CLI and install experience**
Build `cli.py` (`cortex init`, `cortex add-rule`, `cortex doctor`, `cortex list-rules`). Package with `pyproject.toml`. Publish a `cortex init` that is a single command and cannot fail.
- **Success:** `pip install cortex-memory && cortex init && claude mcp add cortex` leaves a working install on a fresh machine on all three OSes.
- **Risk:** Install friction was MemPalace's killer. Test on a clean VM of each OS.

**Phase 7 — Polish, docs, examples**
README, example rules, example memories, contribution guide, CI. Release v0.1.0.

### Why This Order

- **Storage first** because everything depends on it. A bug here breaks every downstream component.
- **Search before server** because search is pure library logic that doesn't need the MCP protocol. Faster feedback loop for tuning performance.
- **Hook before server** because the hook is the key differentiator. If hook enforcement doesn't actually work on Claude Code, the project has no moat and we should find out on day 7, not day 30. Additionally, the hook has no dependency on the server — it can ship and be valuable on its own.
- **Server after the libraries** because every tool handler is just a thin wrapper over the libraries. Building the libraries first means the server phase is glue code, not feature work.
- **CLI last** because `cortex init` needs to know the final directory layout, default config, and example rule shape. Locking that down earlier creates rework.

### Dogfooding Gate

After Phase 4, wire Cortex into **your own** `.claude/settings.json` and use it for real work. Do not proceed to Phase 5 until you have personally been blocked by a rule and appreciated the block. If the hook flow feels wrong, it is MUCH cheaper to fix before the server exists.

---

## 10. Architectural Patterns

### Pattern 1: Filesystem as the Message Bus

**What:** Components never call each other. They read and write `~/.cortex/`. The filesystem is the shared state; POSIX file semantics are the synchronization primitive.

**When to use:** Small multi-process systems where you want crash isolation and zero coordination overhead. Typical for local-first tools, build systems, job queues.

**Trade-offs:**
- Pro: Zero IPC protocol. No sockets, no shared memory, no network.
- Pro: Crash in one component does not corrupt others.
- Pro: Users can inspect state with `ls` and `cat`.
- Con: Cache coherence is your problem — solved here by "don't cache in v1."
- Con: Write contention needs advisory locking.

### Pattern 2: Thin Entry Points, Fat Libraries

**What:** `server.py`, `hook.py`, and `cli.py` are each under ~150 lines. They parse input, call into `storage/search/rules`, format output. All real logic lives in the libraries.

**When to use:** When the same functionality must be reachable through multiple interfaces (MCP tool, hook, CLI). The library is the product; the entry points are just adapters.

**Trade-offs:**
- Pro: Test libraries without mocking MCP or stdio.
- Pro: Add a new interface (REST API, TUI) without rewriting business logic.
- Con: Slight indirection. The happy path goes through one extra function call.

### Pattern 3: Fail Open for Performance, Fail Safe for Correctness

**What:** The hook fails **open** when it exceeds its time budget (slow) or crashes (unexpected exception) — it allows the tool call and logs. But it fails **safe** when rules explicitly match a block condition — it denies the call.

**When to use:** User-facing enforcement where both latency and correctness matter. Classic tradeoff in security-adjacent systems.

**Trade-offs:**
- Pro: No slowdown if Cortex breaks. Users don't associate the tool with "slow AI."
- Pro: Strict enforcement when rules apply and the system is healthy.
- Con: A bug in the rules engine causes silent under-enforcement. Mitigation: load-time validation and `cortex doctor`.

### Pattern 4: Read-Only Hook, Write-Capable Server

**What:** The hook never writes to `~/.cortex/`. Only the server and the CLI write.

**When to use:** Any time you have a high-frequency read path and a low-frequency write path. Frees the read path from needing any locking.

**Trade-offs:**
- Pro: Hook needs no filelock. Simpler and faster.
- Pro: Hook cannot corrupt state even under crash-during-write.
- Con: "Auto-log the blocked call for audit" becomes harder. Workaround: write to a dedicated `logs/hook.log` via `O_APPEND` (atomic on POSIX for small writes under PIPE_BUF), which is a narrow exception to the read-only rule.

### Pattern 5: "Grep-First" Data Design

**What:** All metadata that humans or shell tools might want to filter by is encoded in **filenames and folders**. Only structured data the code must parse lives in frontmatter.

**When to use:** Any system where "I want to see what's there" is a primary user workflow. Especially powerful when combined with git.

**Trade-offs:**
- Pro: `ls ~/.cortex/rules/` shows priorities and topics at a glance.
- Pro: `grep -r "auth" ~/.cortex/sessions/` is a first-class query interface.
- Pro: `git log ~/.cortex/` is a complete audit trail.
- Con: Filename length limits on some filesystems (255 bytes). Handled by capping slugs at 50 chars.

---

## 11. Scaling Considerations

Cortex is a single-user, local-first tool. "Scale" here means "what happens as one user's memory collection grows."

| Scale | Behavior | Action Needed |
|-------|----------|---------------|
| **0-500 files** (first month of use) | Everything is instant. Scan takes <50ms. | None. |
| **500-5,000 files** (heavy user, 6 months in) | Search takes 100-300ms. Noticeable but fine. | None. Maybe add a `--limit` flag. |
| **5,000-20,000 files** (power user, 2+ years) | Search takes 500ms-1.5s. Tool-call latency becomes the dominant cost. | Add the optional inverted index (Phase 3+). Measure first — do not preempt. |
| **20,000+ files** (edge case) | Search is noticeably slow. File enumeration itself (`os.walk`) takes time. | Partition by date (`sessions/2025/`, `sessions/2026/`) and make search aware of date filters. Still stdlib-only. |

### The Actual First Bottleneck

It will almost certainly be **the hook's cold-start time**, not the server's search performance. 50ms of Python startup × thousands of tool calls per day = perceptible latency. This is why Phase 4 includes a hard performance gate, and why "daemonize the hook" is listed as a last-resort optimization.

### What NOT to Optimize

- Do not add an index in v1. 95% of users will have <1,000 files.
- Do not add async anywhere. Single-threaded blocking is correct for this workload.
- Do not add a config to disable the hook — just remove the entry from `.claude/settings.json`. One less knob.

---

## 12. Anti-Patterns to Avoid

### Anti-Pattern 1: Shared In-Memory State Between MCP Calls

**What people do:** Cache rule objects, indexes, search results across tool calls on the server for "speed."

**Why it's wrong:** The user might `vim ~/.cortex/rules/001_foo.md` directly. The server's cached rules are now stale. Worse, the CLI might write new files while the server is running. Cache invalidation is a known-hard problem and is not worth the complexity for a tool where disk I/O is already <5ms.

**Do this instead:** Re-read from disk on every call. Only add caching if profiling proves it's the bottleneck, and invalidate via mtime checks.

### Anti-Pattern 2: Using the MCP Server to Enforce Rules

**What people do:** Put rule-checking logic in the MCP server and expose a `check_rule` tool that Claude is "supposed to" call before dangerous actions.

**Why it's wrong:** Claude may not call it. The whole reason Cortex exists is that prompt-level instructions get ignored. If rule enforcement is a tool Claude chooses to call, it's the same as no enforcement.

**Do this instead:** Rule enforcement lives in the PreToolUse hook. The hook is not optional from Claude's perspective — Claude Code runs it before every tool call, and a `deny` cannot be bypassed.

### Anti-Pattern 3: One Giant Shell Wrapper Script

**What people do:** Write `cortex_preuse_hook.sh` as a bash script that handles argument parsing, rule loading, and JSON manipulation with `jq`.

**Why it's wrong:** Not cross-platform. Windows users get cmd.exe or PowerShell. `jq` is a dependency. Error handling in bash is painful. The whole point of Python stdlib is to avoid this.

**Do this instead:** Hook command is literally `python -m cortex.hook`. Python is the one tool we can assume exists (installed by the user for `pip install cortex-memory`). No shell scripts anywhere.

### Anti-Pattern 4: Embedding a YAML Parser Because "Frontmatter Should Be Real YAML"

**What people do:** Vendor PyYAML into `cortex/_vendored/` or write a full YAML 1.2 parser.

**Why it's wrong:** PyYAML is 5k LOC of C-optional code with known security footguns (`yaml.load` CVE history). Vendoring it adds weight and inherits bugs. Writing a full YAML parser is months of work for a feature users don't need.

**Do this instead:** Define a restricted frontmatter subset (flat key-value, string/int/bool/date/inline-list/block scalar). Parse it with ~80 lines of Python. Reject anything fancier with a clear error: `frontmatter: nested objects not supported; put structured data in the body`.

### Anti-Pattern 5: Printing Debug Info to Stdout in the MCP Server

**What people do:** Add `print("got request:", req)` during development and forget to remove it.

**Why it's wrong:** Stdout is the JSON-RPC channel. Any non-JSON line corrupts the stream and Claude Code disconnects the server. This is the number-one MCP implementation bug.

**Do this instead:** Use `logging.getLogger("cortex")` configured to stderr. Add a lint rule (`grep -r 'print(' cortex/`) in CI that fails if `print` appears outside `cli.py`.

### Anti-Pattern 6: Reading All Rules Into the Hook on Every Call Without Early-Exit

**What people do:** `for path in rules_dir.iterdir(): text = path.read_text(); parse; match`.

**Why it's wrong:** If the user has 50 rules and only 3 apply to Bash, you're doing 47 unnecessary file reads and 47 unnecessary frontmatter parses. Each is <1ms but it adds up against the 100ms budget.

**Do this instead:** Rule filenames should encode which tools they apply to (e.g., `002_bash_confirm-destructive.md` for Bash-only). The hook filters by filename before reading file contents. If you must read every file (e.g., to catch `matches: [*]`), at least cache compiled rules between calls via an mtime-keyed pickle.

---

## 13. Integration Points

### External Services

Cortex has no external services. By design. No network calls, no cloud, no telemetry.

### Internal Boundaries

| Boundary | Mechanism | Notes |
|----------|-----------|-------|
| Claude Code ↔ `cortex.server` | Newline-delimited JSON-RPC 2.0 over stdio pipes | MCP protocol. Server is persistent for the session. |
| Claude Code ↔ `cortex.hook` | Single JSON object on stdin; JSON on stdout + exit code | Process is spawned fresh per tool call. |
| `cortex.server` ↔ filesystem | `cortex.storage` library (atomic write + filelock) | All writes go through the atomic+locked helper. |
| `cortex.hook` ↔ filesystem | `cortex.storage` for reads only | No lock needed; reads are consistent under atomic writes. |
| `cortex.cli` ↔ filesystem | `cortex.storage` (same as server) | Uses the same lock. |
| `cortex.server` ↔ `cortex.hook` | **None (deliberate)** | They share state only through `~/.cortex/`. |

### Claude Code Settings Integration

`cortex init` must edit `~/.claude/settings.json` (user-scope) or `.claude/settings.json` (project-scope):

1. Back up the existing file to `settings.json.bak-YYYYMMDD-HHMM`.
2. Load the JSON (or create `{}` if missing).
3. Ensure `mcpServers.cortex` exists with `{"command": "python", "args": ["-m", "cortex.server"]}`.
4. Ensure `hooks.PreToolUse` contains a `{"matcher": "*", "hooks": [{"type": "command", "command": "python -m cortex.hook"}]}` entry — idempotently (don't duplicate if already present).
5. Write back atomically via the same `storage.atomic_write`.

The edit must be **idempotent**. Running `cortex init` twice should not create two hook entries. `cortex init --force` overwrites; `cortex init` by default merges.

---

## 14. Confidence Summary

| Area | Confidence | Why |
|------|------------|-----|
| PreToolUse hook JSON schema (input and output) | HIGH | Verified against official Claude Code docs at `code.claude.com/docs/en/hooks`. `permissionDecision`, `hookSpecificOutput`, exit codes, precedence rules are all from official source. |
| MCP stdio framing (newline-delimited, no Content-Length) | HIGH | Verified against MCP specification and multiple independent sources. Matches PROJECT.md's prior debugging finding. |
| Python stdlib capabilities (fcntl/msvcrt, re, os.walk, json) | HIGH | Official Python docs. All modules present since 3.4+. |
| Search performance at 10k files | MEDIUM | Extrapolated from similar stdlib workloads. Could be 1.5x-3x off in either direction. Validate with a benchmark in Phase 2. |
| Hook cold-start under 100ms | MEDIUM | Python interpreter startup is the hard floor and varies by platform (Windows Defender can add 30-80ms). Need to measure on all three OSes in Phase 4. |
| Absence of YAML in stdlib | HIGH | Confirmed; no `yaml` module exists in Python stdlib, and there is an active discussion about adding one that has not landed. Restricted frontmatter is the right answer. |
| `cortex init` settings.json edit pattern | MEDIUM | Standard JSON merge logic, but Claude Code may enforce a schema we haven't verified. Phase 6 will need to test against a real Claude Code install. |
| Daemonized-hook fallback if cold-start is too slow | LOW | Untested. Large complexity jump. Listed as last resort, not planned work. |

---

## Sources

- [Hooks reference — Claude Code Docs](https://code.claude.com/docs/en/hooks) — authoritative PreToolUse input/output schema, exit codes, `permissionDecision` semantics, precedence rules
- [Automate workflows with hooks — Claude Code Docs](https://code.claude.com/docs/en/hooks-guide) — `settings.json` configuration format, matchers, `$CLAUDE_PROJECT_DIR`
- [MCP Transports specification](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports) — stdio transport, newline-delimited framing, stdout discipline, stderr for logging
- [Understanding MCP Through Raw STDIO Communication](https://foojay.io/today/understanding-mcp-through-raw-stdio-communication/) — line-based framing details, initialization handshake
- [Transports — modelcontextprotocol.info](https://modelcontextprotocol.info/docs/concepts/transports/) — JSON-RPC 2.0 wire format overview
- [How to Build an MCP Server in Python: Complete Guide](https://scrapfly.io/blog/posts/how-to-build-an-mcp-server-in-python-a-complete-guide) — stdout buffering gotcha, Python implementation patterns
- [Python `re` module documentation](https://docs.python.org/3/library/re.html) — regex compilation, `_MAXCACHE`, pattern performance
- [Python `fcntl` module](https://docs.python.org/3/library/fcntl.html) — POSIX advisory locking
- [Python `msvcrt` module](https://docs.python.org/3/library/msvcrt.html) — Windows file locking primitive
- [Demystifying File Locks in Python: fcntl, msvcrt, portalocker](https://runebook.dev/en/docs/python/library/os/os.plock) — cross-platform locking comparison
- [YAML module, or pyyaml in the stdlib — Python Discussions](https://discuss.python.org/t/yaml-module-or-pyyaml-in-the-stdlib/53831) — confirmation that YAML is not in stdlib
- [Claude Code Hooks Reference: All 12 Events (2026)](https://www.pixelmojo.io/blogs/claude-code-hooks-production-quality-ci-cd-patterns) — hook events, production patterns
- Project context: `C:\Users\mohab\gsd-workspaces\cortex\.planning\PROJECT.md` — constraints, rationale, prior MemPalace debugging findings

---
*Architecture research for: local-first AI memory + rules enforcement system (Python stdlib, MCP stdio server + Claude Code hook)*
*Researched: 2026-04-11*
