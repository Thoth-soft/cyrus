# Pitfalls Research

**Domain:** MCP server + hook-based AI rules enforcement + local markdown memory
**Researched:** 2026-04-11
**Confidence:** HIGH (most pitfalls verified against MemPalace first-hand experience, MCP spec, Claude Code hook docs, and community issue trackers)

> These pitfalls are specific to Cortex: a Python-stdlib-only MCP server that exposes 4-6 memory tools plus a PreToolUse hook that enforces user-defined rules on every tool call. The lived MemPalace experience defines the "don't do this" baseline.

---

## Critical Pitfalls

### Pitfall 1: Wrong MCP framing protocol (Content-Length headers vs. newline-delimited JSON)

**What goes wrong:**
Server writes `Content-Length: N\r\n\r\n{json}` framing (as old LSP-style docs suggest) or wraps stdout in a BufferedWriter that chunks multi-line payloads. Claude Code's stdio client silently hangs on handshake — no error, no crash, just "Server not responding."

**Why it happens:**
A large swath of MCP tutorials, blog posts, and AI-generated docs reference the legacy Content-Length framing from pre-2024 MCP draft specs or borrow LSP patterns. The current MCP stdio spec is actually "JSON-RPC 2.0, one message per line, no embedded newlines, no length headers." MemPalace shipped Content-Length framing and required a wrapper script to work with Claude Code.

**How to avoid:**
- Transport layer emits exactly: `json.dumps(msg, separators=(',',':')) + '\n'` then `sys.stdout.flush()`.
- Reader loop: `for line in sys.stdin:` — one JSON-RPC message per line.
- Assert in tests that no message contains a literal `\n` inside the serialized JSON.
- Never write a `Content-Length` header anywhere.
- Do a raw handshake test: pipe `echo '{"jsonrpc":"2.0","id":1,"method":"initialize",...}'` into the server and verify a single-line response.

**Warning signs:**
- Claude Code's mcp log shows "waiting for initialize response" or "no response received"
- Server works when manually tested with a non-stdio harness but not with Claude Code
- Works on one machine, hangs on another (buffering differences)

**Phase to address:** Phase 1 (MCP core) — before any tool is wired up.

**Severity:** BLOCKER

---

### Pitfall 2: Writing logs/prints to stdout (pollutes the protocol channel)

**What goes wrong:**
Any stray `print("loaded config")`, `print(f"saving {path}")`, traceback, or library warning on stdout is parsed by Claude Code as JSON-RPC and fails with "Invalid JSON" — sometimes disconnecting the server. A single `print()` anywhere in import chain corrupts the session.

**Why it happens:**
Python's default `print()` goes to stdout. Developers instinctively add debug prints. Third-party libraries sometimes print on import. Uncaught exception tracebacks go to stderr (good) but any wrapper that catches-and-prints goes to stdout (bad).

**How to avoid:**
- At server boot, before any other import, redirect stdout: keep a reference to the real stdout for protocol writes, and replace `sys.stdout` with stderr or `/dev/null`.
  ```python
  _protocol_out = sys.stdout
  sys.stdout = sys.stderr  # any stray print() now goes to stderr
  ```
- All logs through `logging` module configured to stderr only.
- Grep the codebase in CI for bare `print(` calls; fail the build.
- Warnings filter: `warnings.filterwarnings("ignore")` at startup or route to stderr.
- Never use `pprint`, `pdb.set_trace()`, or `breakpoint()` in the server process.

**Warning signs:**
- Intermittent "Invalid JSON" errors in Claude Code MCP log
- Server works in direct testing but fails under Claude Code
- Server reconnects then fails again after certain tool calls (whichever path triggers the print)

**Phase to address:** Phase 1 (MCP core) — stdout hygiene is a foundational invariant.

**Severity:** BLOCKER

---

### Pitfall 3: Windows stdin text mode mangles protocol bytes

**What goes wrong:**
On Windows, Python opens `sys.stdin` in text mode by default, which translates `\r\n` → `\n` on read and interprets a lone `\x1a` (Ctrl-Z) as EOF. JSON payloads containing escaped CRLF get corrupted. Binary content (e.g., a memory containing a Windows log file) silently loses bytes. The initialize handshake succeeds but later messages fail randomly.

**Why it happens:**
Python 3 opens std streams in text mode with locale encoding (`cp1252` on US Windows) and universal newlines. This is a direct repeat of the MemPalace Windows failure.

**How to avoid:**
- At server entry, before reading stdin, reopen in binary mode:
  ```python
  import sys, os
  if sys.platform == "win32":
      import msvcrt
      msvcrt.setmode(sys.stdin.fileno(), os.O_BINARY)
      msvcrt.setmode(sys.stdout.fileno(), os.O_BINARY)
  sys.stdin = os.fdopen(sys.stdin.fileno(), "rb", buffering=0)
  sys.stdout = os.fdopen(sys.stdout.fileno(), "wb", buffering=0)
  ```
- Decode/encode explicitly as UTF-8 for each message (not locale default).
- Reader splits on `b"\n"` only — never rely on text-mode line reading.
- Test on a Windows machine with a message containing literal `\r\n` inside a string value.

**Warning signs:**
- Works on macOS/Linux, fails on Windows
- Large messages (>4KB) get truncated or corrupted on Windows
- Messages containing Windows paths (`C:\\Users\\...`) cause JSON decode errors

**Phase to address:** Phase 1 (MCP core) — binary-mode stdio is a day-one requirement.

**Severity:** BLOCKER

---

### Pitfall 4: Unicode encoding crashes on Windows CLI (cp1252 can't encode emoji)

**What goes wrong:**
`cortex init` prints a banner or success message containing `✓`, `→`, `🧠`, or a smart quote. Windows PowerShell and CMD default to cp1252, and Python's stdout raises `UnicodeEncodeError: 'charmap' codec can't encode character`, crashing init before `~/.cortex/` is created. User sees a traceback, not a success message.

**Why it happens:**
Python on Windows uses the system ANSI codepage (cp1252) for stdout encoding unless PYTHONIOENCODING is set or stdout is reconfigured. This is exactly what bit MemPalace — the emoji in the init banner aborted the installer.

**How to avoid:**
- **Option A (preferred for CLI):** Use ASCII-only for CLI output. No emoji, no box-drawing characters beyond `-+|`. "OK" not "✓", "->" not "→".
- **Option B:** At CLI entry, reconfigure stdout:
  ```python
  import sys
  if hasattr(sys.stdout, "reconfigure"):
      sys.stdout.reconfigure(encoding="utf-8", errors="replace")
  ```
- Never rely on PYTHONIOENCODING being set; hard-code it.
- Test `cortex init` on Windows CMD (not just Windows Terminal, which defaults to UTF-8).

**Warning signs:**
- `UnicodeEncodeError` in tracebacks from CLI commands
- Works in Windows Terminal but fails in cmd.exe
- Users on Windows report "init crashed" with garbled output

**Phase to address:** Phase 1 (CLI scaffold) and enforced in Phase 6 (packaging/installer).

**Severity:** BLOCKER

---

### Pitfall 5: Slow PreToolUse hook makes everything feel broken

**What goes wrong:**
Hook does a Python cold-start (~100-250ms on Windows), reads and parses 50 rule files, evaluates regexes, then exits. Total: 400-800ms per tool call. Claude Code edits a file 10 times in a task — that's 4-8 seconds of invisible latency. Users describe it as "Claude Code feels sluggish since I installed Cortex." Community issue shows a case where 11 hooks compounded to ~20 seconds per interaction.

**Why it happens:**
PreToolUse runs **before every matching tool call**, synchronously. Python interpreter startup on Windows is especially slow (imports like `json`, `re`, `pathlib` add up). Developers benchmark one invocation (feels fine) but never measure cumulative impact.

**How to avoid:**
- **Hard budget: hook total execution < 50ms on warm disk, < 150ms cold.** Enforce in CI with a benchmark.
- Minimize imports: only `sys`, `json`, `os`, `re`. No `pathlib`, no `yaml`, no custom modules. Lazy-import everything that isn't on the hot path.
- Pre-compile rules into a single `~/.cortex/rules.compiled.json` cache; re-compile only when source rule files change (check mtime of a single manifest file).
- Use `re.compile` results stored in the cache as pickled pattern bytes (or cache regex source strings and compile once).
- Hook should `sys.exit(0)` immediately if no rules are active (cheap no-op path).
- Profile with `python -X importtime -c "import cortex.hook"` and keep imports under 30ms.
- Provide a `cortex hook bench` command that measures p50/p95 latency over 100 runs.

**Warning signs:**
- `time` on hook invocation exceeds 200ms
- Users complain "Claude Code is slow"
- Tool calls visibly pause between command and output

**Phase to address:** Phase 3 (hook + rules enforcement). Benchmark gate must be part of phase exit criteria.

**Severity:** BLOCKER (perceived performance)

---

### Pitfall 6: Hook swallows errors silently, or crashes and blocks Claude Code forever

**What goes wrong:**
Two opposite failure modes:
- **Silent swallow:** Hook hits an unexpected error (malformed rule file, permission error, encoding issue), catches it broadly, exits 0. User thinks rules are enforcing. They aren't. A "don't run destructive commands" rule never fires. User discovers weeks later after an incident.
- **Loud crash:** Hook raises an unhandled exception, exits 1 (or 2), and Claude Code interprets it as "block every tool call" — the user can't do anything until they edit settings.json to disable the hook.

**Why it happens:**
Exit code semantics are counterintuitive: exit 0 = allow, exit 2 = block with stderr → Claude, any other non-zero = non-blocking error. Developers default to broad try/except → exit 0, which hides bugs. Or they let exceptions propagate → Python exits 1 on unhandled exception, which is "non-blocking error" but the hook still didn't enforce anything.

**How to avoid:**
- Explicit error policy documented in the spec: hook errors are **fail-open with loud warning to stderr**, never fail-closed. An error in Cortex must not lock the user out of their own tools.
- Top-level try/except in the hook that:
  1. Logs full traceback to `~/.cortex/hook-errors.log`
  2. Writes a short "Cortex hook error (check ~/.cortex/hook-errors.log)" to stderr
  3. Exits 0 (allow)
- On startup, if `~/.cortex/hook-errors.log` has new entries since last session, surface it via the next MCP `status` tool call.
- Kill switch: if the hook errors 3+ times in a row, auto-disable itself by writing a marker file and surfacing "hook auto-disabled due to repeated errors" in MCP status.
- Integration test: corrupt a rule file and verify Claude Code still works + error is logged + status surfaces it.

**Warning signs:**
- `~/.cortex/hook-errors.log` exists and is non-empty
- User reports "rules stopped working" without knowing why
- Claude Code refuses all tool calls (blocked state)

**Phase to address:** Phase 3 (hook + rules enforcement). Error policy is a design decision, not an implementation detail.

**Severity:** BLOCKER

---

### Pitfall 7: Blocking decision JSON format wrong → hook "blocks" but Claude proceeds anyway

**What goes wrong:**
Hook outputs `{"block": true, "message": "..."}` or `{"decision": "deny"}` — both invalid. Claude Code ignores malformed JSON, treats hook as "no opinion," and lets the tool call proceed. Developer sees hook running (maybe even in logs), assumes it's enforcing, but rules never block anything.

**Why it happens:**
Claude Code hook schema has evolved across versions. Current correct schema is either:
- `{"decision": "block", "reason": "..."}` (simple form), or
- `{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": "..."}}`

And exit code 2 with stderr also blocks (feeds stderr to Claude). Developers copy outdated examples and never verify the block actually blocks.

**How to avoid:**
- Pin against a specific Claude Code version range in docs; state "tested with Claude Code X.Y.Z+".
- Use **both** mechanisms defensively: output the JSON `{"decision": "block", "reason": "..."}` on stdout AND write the reason to stderr AND exit 2. This is belt-and-suspenders but survives schema drift.
- Integration test: install a rule "block all Bash commands", run `bash -c 'echo test'` through Claude Code in a test harness, assert it's actually blocked.
- Document the exact JSON the hook emits in README with a version tag.
- On Claude Code version mismatch, emit a warning at `cortex status` time.

**Warning signs:**
- Hook logs show "would block" but tool call succeeded
- Rules defined but never observed to fire
- New Claude Code release breaks enforcement without a code change

**Phase to address:** Phase 3 (hook integration). Real end-to-end blocking test is an exit criterion.

**Severity:** BLOCKER

---

### Pitfall 8: PyPI name "cortex" is taken — and many variants too

**What goes wrong:**
`pip install cortex` installs someone else's package (a neural network toolkit from the 2010s). `pip install cortex-memory` may resolve to `cortex-memory-sdk` (an enterprise product). Users fail `pip install cortex-memory` because the exact name is taken. Brand confusion, support burden, shipped-broken install instructions.

**Why it happens:**
Verified on PyPI (2026-04-11): `cortex`, `cortex-ai-memory`, `cortex-memory-sdk`, `claude-cortex`, `cortex-gateway`, `cortex-linux`, `cortex-python` all exist. The name "cortex" is crowded, especially the memory-adjacent space.

**How to avoid:**
- **Verify PyPI name availability before any public commitment** — ideally before the GitHub repo is public.
- Candidate names ranked by availability + clarity:
  - `cortex-cc` ("Cortex for Claude Code") — short, scoped, probably free
  - `cortex-hook` — emphasizes the differentiator
  - `cortex-rules` — emphasizes enforcement
  - `claude-cortex` is **taken** (claude context CLI)
  - `cortex-memory` variants are **all taken**
- Reserve the name on PyPI with a v0.0.0 placeholder the moment it's chosen.
- Alternative: rename the project. "Cortex" has too much squatter pressure. Consider a unique name (e.g., "gyrus", "hippo", "synapse-hook"). Name uniqueness > brand attachment in open-source.
- Reserve the GitHub org + npm scope + PyPI name simultaneously.

**Warning signs:**
- `pip search` (or PyPI web) shows multiple hits
- `pip install <name>` resolves to something unexpected in a clean venv
- GitHub has another popular repo with the same name

**Phase to address:** Phase 0 (project setup, pre-code). This is **the first thing** to lock down.

**Severity:** BLOCKER

---

### Pitfall 9: File lock contention corrupts memory files under concurrent access

**What goes wrong:**
Two MCP `save_memory` calls arrive near-simultaneously (autoSave hook + explicit save). Both open the same markdown file in append mode. On Windows, the second one fails with `PermissionError: [WinError 32]`. On POSIX, both succeed but interleave bytes — producing a corrupted file with half of each message. User later grep-searches a corrupted memory and gets junk.

**Why it happens:**
MCP stdio is single-connection but server handlers are often concurrent (asyncio or threaded). Appending to files without locking is unsafe across OSes. Python stdlib has no portable file lock (no `fcntl` on Windows, no `LockFileEx` on POSIX).

**How to avoid:**
- **Serialize all writes through a single writer.** Use an in-process queue (`queue.Queue`) processed by one worker thread/coroutine. All save/delete/rule-add operations go through it.
- **Atomic write pattern (critical):**
  1. Write to `file.md.tmp.<uuid>` in the same directory
  2. `os.fsync()` the temp file's fd
  3. `os.replace(tmp, final)` — atomic on both Windows and POSIX
  4. On exception, unlink the temp file
- Never use `open(f, "a")` for memory writes. Always read-modify-write with atomic replace, or append via the serialized writer.
- Test: fire 100 parallel save calls and verify no corruption + no lost writes.
- For read-while-write: readers should tolerate the atomic rename by retrying on transient FileNotFoundError (rare, < 1ms race window).

**Warning signs:**
- Memory files contain duplicated YAML frontmatter
- `PermissionError [WinError 32]` on Windows
- Occasional empty or half-written files after a crash
- Character-level corruption in grep results

**Phase to address:** Phase 2 (memory storage). Atomic writes + serialized writer must be baseline, not an optimization.

**Severity:** MAJOR

---

### Pitfall 10: False positives in rule enforcement block legitimate work

**What goes wrong:**
User adds rule "block rm -rf". Hook regex matches `rm -rf` substring. Later, Claude tries to edit a README that contains the literal string `rm -rf /tmp/cache` in a code example. Hook blocks the Edit tool call. User can't edit docs. User disables Cortex in frustration. Rule enforcement product fails by being too aggressive.

**Why it happens:**
Naive substring / regex matching over the raw tool input field doesn't distinguish between "executing a command" and "mentioning a command." Rules authored without context about which tool they apply to fire across all tools.

**How to avoid:**
- **Rules must be scoped to specific tools**, not global. Schema:
  ```yaml
  name: no-rm-rf
  applies_to: [Bash]   # only Bash tool, not Edit/Write
  pattern: "^\\s*rm\\s+-rf"  # anchored
  action: block
  reason: "Destructive command blocked by Cortex rule 'no-rm-rf'"
  ```
- Anchored regex patterns by default; warn on unanchored patterns at rule creation.
- Dry-run mode: `cortex rule test <rule> <input>` shows whether a rule would fire against an example without installing it.
- **Temporary override:** env var `CORTEX_ALLOW=rule-name` or `cortex pause <rule>` (write a marker file that expires after N minutes) to let users bypass a rule without editing files.
- Log every block (to `~/.cortex/blocks.log`) so users can audit false positives.
- Rule authoring template asks "what tool does this apply to?" and won't save a global rule without confirmation.

**Warning signs:**
- Users report "Cortex blocked something harmless"
- Block log shows high volume on same rule + same file type
- Users editing rules constantly to add exceptions

**Phase to address:** Phase 3 (rules enforcement). Scoping must be in v1 schema, not added later.

**Severity:** MAJOR

---

### Pitfall 11: False negatives — rules that look active but never trigger

**What goes wrong:**
User writes a rule in `~/.cortex/rules/no-force-push.md`. Rule file has a typo in the YAML frontmatter (`patern:` instead of `pattern:`). The rule loader skips it silently. User believes `git push --force` is blocked. It isn't. Months later, they force-push to main.

**Why it happens:**
Lenient parsers that skip malformed rules without surfacing errors. No schema validation. Users edit files manually with no IDE schema support.

**How to avoid:**
- **Strict parser:** any rule file that fails to parse raises a visible warning in `cortex status` and the MCP `status` tool. Not silent.
- `cortex lint` command validates all rule files against the schema.
- On hook startup, skip malformed rules but write to `~/.cortex/rule-load-errors.log` and surface on next `status` call.
- `cortex rule show <name>` displays the parsed (post-load) representation — lets users confirm what the hook actually sees.
- Required fields enforced: `name`, `applies_to`, `pattern`, `action`. Missing field = loud error.
- Self-test: on first install, Cortex installs a single "canary" rule that must fire on a specific no-op test input. Verifies the hook path is wired correctly end-to-end.

**Warning signs:**
- Silent `rule-load-errors.log` entries
- User says "I added a rule but it doesn't do anything"
- Rule count in `cortex status` lower than file count in `~/.cortex/rules/`

**Phase to address:** Phase 3 (rules enforcement). Visibility + linting is table stakes.

**Severity:** MAJOR

---

### Pitfall 12: Forward slash vs. backslash breaks JSON serialization on Windows

**What goes wrong:**
MCP response includes a Windows path like `C:\Users\mohab\.cortex\memories\note.md`. JSON serialization escapes each `\` as `\\`, producing `C:\\Users\\mohab\\...`. If any code path uses string concatenation instead of `json.dumps` (e.g., building responses as f-strings), backslashes get interpreted as escape sequences — `\n`, `\t`, `\U` — corrupting the path. `\U` is especially dangerous: it triggers "truncated \UXXXXXXXX escape" errors.

**Why it happens:**
Developers write `response = f'{{"path": "{path}"}}'` instead of `json.dumps({"path": path})`. Works on POSIX because paths don't contain backslashes. MemPalace hit this.

**How to avoid:**
- **Never build JSON with string concatenation.** Always `json.dumps(...)`.
- Normalize paths on storage: store as POSIX-style (`/`) internally; convert to native separator only at FS boundary. Use `pathlib.PurePosixPath` or `str(path).replace("\\", "/")`.
- Lint rule: fail the build if any file contains `f'{{` (string-formatted JSON) in the server path.
- Test payload: generate a memory with path `C:\\Users\\test\\Users\\note.md` and verify JSON round-trips correctly.

**Warning signs:**
- JSON decode errors only on Windows
- Paths look wrong in MCP responses (missing characters)
- `SyntaxError: (unicode error) 'unicodeescape' codec can't decode bytes`

**Phase to address:** Phase 1 (MCP core) path handling contract + Phase 2 (storage).

**Severity:** MAJOR

---

### Pitfall 13: Hook settings.json path is absolute and machine-specific

**What goes wrong:**
`cortex init` writes to `~/.claude/settings.json` a hook path like `/Users/mohab/.cortex/hook.sh`. User syncs settings via dotfiles repo to another machine (Windows). Path doesn't exist. Claude Code fails to start hook, surfaces a cryptic "hook not found" error.

**Why it happens:**
Hook configs in settings.json require a command path. Absolute paths are machine-specific. Relative paths are resolved relative to CWD, which varies. `~` expansion is client-dependent.

**How to avoid:**
- Install a tiny shim in a well-known location (e.g., `~/.cortex/bin/hook`) and reference it with a template that Claude Code resolves: use `${HOME}/.cortex/bin/hook` if Claude Code supports env expansion, or use the `cortex` CLI as the hook command (`cortex hook run`) relying on `cortex` being on PATH.
- **Preferred:** Register hook as `cortex hook run` — this works as long as the CLI is on PATH (which `pip install` guarantees via entry points).
- `cortex init` detects whether `cortex` is on PATH; if not, fails loudly with remediation steps.
- `cortex doctor` command: validates settings.json, checks `cortex` is on PATH, verifies hook fires with a canary test.
- Document that settings.json should not be synced across machines unless all machines have `cortex` on PATH.

**Warning signs:**
- "Hook command not found" errors
- Works on install machine, fails after dotfile sync
- Different behavior between terminals with different PATHs

**Phase to address:** Phase 3 (hook installation) and Phase 6 (packaging, entry points).

**Severity:** MAJOR

---

### Pitfall 14: Bash-script hook breaks on Windows (no bash) and Git Bash (different PATH)

**What goes wrong:**
Hook script is `#!/bin/bash` and shells out to `python ~/.cortex/hook.py`. On Windows without Git Bash, `bash` isn't on PATH — hook can't start. On Windows **with** Git Bash, `python` may resolve to WSL Python or a different interpreter than the one Cortex was installed into. User installs Cortex in venv, hook runs system Python, imports fail.

**Why it happens:**
Cross-shell compatibility is hard. `cmd.exe`, PowerShell, Git Bash, zsh, fish, and bash all have different conventions. Python venvs further complicate which interpreter runs.

**How to avoid:**
- **No shell scripts.** Register the hook as a Python entry point: `cortex hook run`. Pip's entry points generate a `.exe` shim on Windows and a shell wrapper on POSIX — handled by pip, not us.
- Entry point in `pyproject.toml`:
  ```toml
  [project.scripts]
  cortex = "cortex.cli:main"
  ```
  Claude Code hook command: `cortex hook run` (or the OS-native path pip generated).
- Absolutely no `bash`, `sh`, `zsh` dependency. No `.sh`, `.bat`, `.ps1` files.
- `cortex doctor` verifies `cortex` command resolves to the expected Python interpreter (check `sys.executable`).

**Warning signs:**
- Hook works for some users, silently fails for others
- "command not found" in hook error logs
- Users in venvs report hook uses wrong Python

**Phase to address:** Phase 3 (hook installation). Design decision: Python entry point, never shell.

**Severity:** MAJOR

---

### Pitfall 15: Regex catastrophic backtracking on large memory files

**What goes wrong:**
User writes a rule with pattern `(.*a)+b`. Evaluates fine on small input, but on a 500KB memory file it hangs for 30 seconds due to exponential backtracking. Hook times out. Every save is now blocked. User has no idea why.

**Why it happens:**
Python's `re` module uses a backtracking engine vulnerable to catastrophic regex patterns (ReDoS). Grep search over 10k files with user-supplied patterns amplifies the risk.

**How to avoid:**
- Grep tool: use `re.compile(pattern)` with a timeout guard. Python's `re` doesn't support timeouts natively; use a watchdog thread or run the regex in a subprocess with `timeout=N`.
- Limit input size to the regex: cap individual file reads to, e.g., 1MB; fall back to line-by-line for larger files.
- For rules, prefer **literal substring match** or **anchored patterns** by default. Accept regex only when explicitly marked `type: regex`.
- Lint rules at creation time: run them against a synthetic adversarial input with a 100ms budget; warn if exceeded.
- Document the rule syntax explicitly: "Glob patterns or anchored regex only. Avoid nested quantifiers."

**Warning signs:**
- Hook latency spikes on specific files
- `cortex search` hangs on certain queries
- CPU pegged at 100% during rule evaluation

**Phase to address:** Phase 2 (search) and Phase 3 (rules). Timeout guard in both paths.

**Severity:** MAJOR

---

### Pitfall 16: YAML frontmatter parsing without PyYAML — edge cases

**What goes wrong:**
Python stdlib has no YAML parser. Rolling your own for markdown frontmatter works for 95% of cases then fails on: multiline strings, flow-style lists (`tags: [a, b]`), anchors, escaped colons in values (`url: https://example.com:8080`), unquoted strings that look like booleans (`key: no`), Windows line endings.

**Why it happens:**
"I'll just split on `---` and parse key: value" — works for the demo, breaks on real user input.

**How to avoid:**
- **Restrict the frontmatter format to a strict subset:**
  - Only scalar string values
  - No multiline strings (`|` or `>`)
  - Colons in values must be quoted (`url: "https://..."`)
  - No flow-style collections
  - CRLF and LF both accepted on read; write LF only
- Document the subset explicitly in the README ("Cortex frontmatter is a strict subset of YAML").
- `cortex lint` validates frontmatter against the subset.
- **Alternative: use TOML** — Python 3.11+ has `tomllib` in stdlib. If minimum Python is 3.11+, this is a better choice. Still zero deps.
- **Alternative: use JSON frontmatter** — `---json` delimiter. Less human-friendly but unambiguous and stdlib-native.
- Never pretend to support "YAML" when actually supporting a subset; call it what it is.

**Warning signs:**
- Users report "my memory file has weird characters"
- Frontmatter silently truncated
- Values containing `:` get split at the wrong place

**Phase to address:** Phase 2 (storage). Decide format in Phase 0 / Phase 1.

**Severity:** MAJOR

---

### Pitfall 17: Memory files grow unbounded; grep slows at 10k+ files

**What goes wrong:**
Auto-save hook fires every N messages for 6 months. User has 40,000 memory files, each 5KB. `cortex search` walks the full directory tree on every query — takes 8 seconds. Cortex feels unusable. User migrates to something else.

**Why it happens:**
Naive directory walking + linear grep is O(n) in files. No index. No archival. Every save adds a file forever.

**How to avoid:**
- **Directory sharding:** store memories in date-sharded subdirs (`memories/2026/04/11/note-<slug>.md`). Keeps directory sizes small and lets search prune by date filters.
- **Tag/category index file:** `~/.cortex/index.json` with `{category: [paths]}` updated on save/delete. Enables O(1) category listing.
- **Optional FTS via stdlib sqlite3:** if search slows, add a sidecar SQLite index using SQLite's FTS5 extension (comes with stdlib Python's sqlite3). Still zero external deps.
- **Archival policy:** memories older than N days auto-move to `~/.cortex/archive/` which is excluded from default search (requires `--include-archive`).
- **Size cap with warning:** `cortex status` warns when memory store exceeds 100MB or 10k files.
- Benchmark: search p95 < 500ms at 10k files is an exit criterion.

**Warning signs:**
- `cortex search` latency creeping up
- Directory `ls` takes visible time
- `cortex status` shows high file count

**Phase to address:** Phase 2 (storage design). Sharding from day one; FTS as Phase 5 optimization.

**Severity:** MAJOR

---

### Pitfall 18: Auto-save fires mid-task, saving garbage context

**What goes wrong:**
"Save every 10 messages" fires when Claude is in the middle of planning. The memory captures half a thought, a code snippet with no context, or a partial tool result. Later searches return these junk memories. Signal-to-noise degrades over time.

**Why it happens:**
Time/message-based triggers don't correlate with "a useful thing just happened." Mid-task saves are noise.

**How to avoid:**
- **Don't auto-save by default.** Make the MVP explicit-save-only. Let users prove they want auto-save before building it.
- If auto-save ships: trigger on **task boundaries**, not message counts. Use SessionStop hook (task ended) or UserPromptSubmit (new user instruction = previous turn complete).
- Never save inside a tool-use loop; wait for an assistant turn without tool calls.
- Every auto-saved memory includes a `source: auto` tag so users can filter them out.
- `cortex cleanup` command bulk-deletes auto-saved memories older than N days.
- Let the AI itself decide when to save via the explicit `save_memory` tool; rely on prompt engineering in CLAUDE.md, not hooks.

**Warning signs:**
- Users complain memories are "useless"
- Memory files contain incomplete sentences
- Search results return fragments, not coherent notes

**Phase to address:** Phase 4 (auto-save) or defer entirely. Do the explicit path first.

**Severity:** MAJOR (product failure mode)

---

### Pitfall 19: Stale memories conflict with current reality; no freshness signal

**What goes wrong:**
User changes their mind about a preference. Old memory says "always use React," new memory says "always use Svelte." AI finds both on search, can't tell which is authoritative, does something inconsistent. User loses trust in memory system.

**Why it happens:**
No versioning, no supersession, no freshness weighting. Memories are append-only with no concept of "this replaces that."

**How to avoid:**
- Every memory has a `created:` and `updated:` timestamp in frontmatter.
- Search results sorted by recency (or recency-weighted) by default.
- `save_memory` tool supports `replaces: <id>` field to mark supersession — old memory gets a `superseded_by:` link and is filtered from default search.
- `cortex dedupe` command surfaces near-duplicate memories for manual review.
- Rules should have an explicit supersession mechanism too: newer rule with same `name` wins, old one archived.
- Document the mental model: "memories are append-only but search prefers recent; use explicit supersession for contradictions."

**Warning signs:**
- AI cites contradictory memories in the same response
- User asks "why is it still doing X?" and old memory is the culprit
- Duplicate memories with minor variations

**Phase to address:** Phase 2 (storage schema). Timestamps are baseline; supersession is Phase 4.

**Severity:** MAJOR

---

### Pitfall 20: AI finds creative workarounds to bypass rules

**What goes wrong:**
Rule: "block Edit tool on /etc/passwd". AI reads the rule via `read_memory`, sees the block, then calls `Bash("vim /etc/passwd")` — which isn't an Edit tool call, so the rule doesn't fire. User discovers later. Or: rule blocks `rm -rf /`, AI writes a Python script that calls `shutil.rmtree("/")` via the Write+Bash combo.

**Why it happens:**
Rules defined in terms of tool+pattern, but the attack surface is the actual system resource. Any tool that can reach the resource bypasses the rule. AI pattern-matches on "how do I accomplish X" without knowing the security intent.

**How to avoid:**
- Document the threat model clearly in README: "Cortex rules catch common cases; they are not a sandbox. An AI actively trying to bypass them can do so."
- Rules should target **resources** where possible (file paths, URLs), not just tool patterns. "Block any write to /etc/*" applies across Edit, Write, Bash, NotebookEdit, etc.
- Provide a "resource-scoped rule" as a first-class concept alongside "tool-scoped rule."
- Supplement with CLAUDE.md / system prompt instructions that tell Claude what the rules are for; rules enforce, prompts inform.
- Never market Cortex as a security boundary. It's a consistency enforcer.
- Rule templates cover the common classes (destructive FS ops, credential exposure, git force-push) with cross-tool coverage built in.

**Warning signs:**
- Users report "AI did X anyway despite the rule"
- Block log shows attempts via tools the user didn't expect
- Community issues about "bypass"

**Phase to address:** Phase 3 (rules enforcement) — design rule schema with resource-scoping from day one. README threat model is documentation debt if delayed.

**Severity:** MAJOR

---

### Pitfall 21: Rule conflicts — rule A blocks, rule B allows — no resolution policy

**What goes wrong:**
User has rule "block Bash containing rm" and another rule "allow rm in /tmp/". Both fire on `rm /tmp/cache`. What wins? If order-dependent, a rule added in a different order changes behavior. If undefined, behavior varies across versions. Users can't predict enforcement.

**Why it happens:**
Multiple overlapping rules are natural; no explicit precedence rule means "first match wins" or "last match wins" which is fragile.

**How to avoid:**
- **Explicit precedence:** `deny` wins over `allow` by default (fail-safe). Document this loudly.
- Rule priority field (integer) for overrides: higher priority evaluated first; if matched, terminal.
- `cortex rule test <input>` shows **all** matching rules + which one won + why.
- Warn on rule load if two rules have the same name or overlapping patterns.
- Block log includes the winning rule id so users can trace decisions.

**Warning signs:**
- Users report inconsistent enforcement
- Adding a rule changes behavior of an unrelated rule
- Community questions about "which rule wins"

**Phase to address:** Phase 3 (rules). Precedence is a design decision, not a bug fix.

**Severity:** MAJOR

---

### Pitfall 22: Tool name collisions with other MCP servers

**What goes wrong:**
Cortex exposes a `save` tool. Another MCP server (e.g., a note-taking server) also has `save`. Claude Code's MCP client raises an error on startup, or routes calls to the wrong server depending on connection order. User can't use both.

**Why it happens:**
MCP spec has no namespacing. Tool name collisions between servers are a known community issue. Common generic names (`save`, `search`, `list`, `status`) are especially likely to collide.

**How to avoid:**
- **Prefix all tool names** with `cortex_`: `cortex_save`, `cortex_search`, `cortex_list`, `cortex_delete`, `cortex_status`, `cortex_add_rule`.
- Use consistent prefix across every tool; no exceptions.
- Document this as a deliberate choice in README ("tools prefixed to avoid collisions").
- Keep tool count low (4-6) — fewer names, fewer collisions.
- Never use a generic name even if prefixed is longer.

**Warning signs:**
- Users report "Cortex conflicts with my other MCP server"
- Tool calls go to wrong server
- Claude Code errors about duplicate tool names

**Phase to address:** Phase 1 (MCP tool design). Naming convention is a day-one decision.

**Severity:** MAJOR

---

### Pitfall 23: No way to test the MCP server without Claude Code

**What goes wrong:**
Developer can't iterate fast because testing means: make change → restart Claude Code → trigger a tool call → see if it worked. 60-second feedback loop. No unit tests for protocol behavior. Regressions ship unnoticed.

**Why it happens:**
MCP stdio protocol feels "owned" by the client, so developers don't write harnesses. Third-party inspectors exist but aren't always trusted.

**How to avoid:**
- Build a minimal test harness that drives the server via stdio with a scripted sequence of JSON-RPC messages. ~100 lines of code.
- Harness can replay recorded interactions (initialize → list_tools → call_tool → shutdown) and assert on responses.
- Unit tests for every tool that call the handler function directly, bypassing the transport.
- Integration test: spawn the server as a subprocess, pipe fake requests, assert responses match fixtures.
- Separate test for hook subprocess: spawn the hook with fake event JSON on stdin, assert exit code and stdout JSON.
- CI runs the full harness on every PR, cross-platform (Windows + macOS + Linux matrix).
- Document how to run the harness manually: `python -m cortex.test.harness`.

**Warning signs:**
- Bugs found only after user reports
- No CI coverage of protocol layer
- Developer avoids making changes because "might break it"

**Phase to address:** Phase 1 (MCP core). Harness is part of the core deliverable, not an optional extra.

**Severity:** MAJOR

---

### Pitfall 24: Python 3.9 minimum → missing key stdlib features

**What goes wrong:**
Target says "Python 3.9+ (widely available)." But:
- `tomllib` is 3.11+ — can't use for frontmatter
- `zoneinfo` is 3.9+ (OK) but `datetime.fromisoformat` on arbitrary inputs is 3.11+
- `str.removeprefix`/`removesuffix` is 3.9+ (OK)
- `re.NOFLAG` is 3.11+
- `sys.stdout.reconfigure` is 3.7+ (OK)
- Walrus operator gotchas in 3.9

Developer writes `tomllib.loads(...)` because "it's stdlib," users on 3.9 get ImportError.

**Why it happens:**
Different stdlib features landed in different versions. "Stdlib only" doesn't mean "available in all versions."

**How to avoid:**
- **Decide the true minimum version based on features needed.** If frontmatter uses TOML → minimum 3.11. If JSON → 3.9 is fine.
- Document minimum explicitly. CI runs against the minimum.
- Avoid 3.10+ syntax (`match` statements, `X | Y` type hints) unless 3.10 is the minimum.
- Recommendation: **Python 3.10 minimum** balances stdlib breadth with availability (3.10 is default on Ubuntu 22.04, macOS has it via brew, Windows installer available).
- Better: **Python 3.11 minimum** gets `tomllib` + faster startup (important for hook latency) + better error messages.
- Trade-off: users on older Linux distros may need to install a newer Python.

**Warning signs:**
- `ImportError` reports from users
- CI passes on 3.12 but users fail on 3.9
- Version-gated code branches proliferate

**Phase to address:** Phase 0 (decide minimum version). Revisit in Phase 6 (packaging).

**Severity:** MAJOR

---

### Pitfall 25: First-run init fails when `~/.cortex/` can't be created

**What goes wrong:**
User installs on a system where `~/` is read-only (locked-down enterprise), or `~/.cortex/` already exists as a file (not a dir), or they run as a service account with no home dir. `cortex init` crashes uninformatively. `cortex mcp` start also fails because dirs don't exist.

**Why it happens:**
Code assumes `~/` is writable and `~/.cortex/` is either absent or a directory. No handling of edge cases.

**How to avoid:**
- `cortex init` checks: home dir exists, is writable, `~/.cortex/` (if present) is a dir not a file.
- Support `CORTEX_HOME` env var to override location.
- MCP server at startup: creates `~/.cortex/` if missing, fails loudly with actionable error if it can't.
- `cortex doctor` validates the entire install.
- Document the exact paths and permissions required.
- On Windows, prefer `%LOCALAPPDATA%\cortex\` (via `platformdirs`-equivalent manual logic, no dep). On macOS, `~/Library/Application Support/cortex/` is more idiomatic but users expect dotfiles; stick with `~/.cortex/` unless strong reason.

**Warning signs:**
- "No such file or directory" on first run
- "Permission denied" during init
- Silent failures where init says success but nothing was created

**Phase to address:** Phase 1 (CLI init) and Phase 6 (packaging).

**Severity:** MAJOR

---

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| Naive substring rule matching (no anchoring) | Simple rule syntax | False positives, users disable enforcement | Never — causes product failure |
| Loading all rules on every hook call | Simple code, no cache invalidation | Hook latency at scale of 50+ rules | Phase 3 only; add compiled cache in Phase 5 |
| Global `try/except: pass` in hook | Prevents crashes | Hides bugs, silently drops enforcement | Never — use explicit "log + fail-open" |
| Using `print()` for logging | Easy debug output | Corrupts MCP protocol | Never in server process; CLI only |
| Storing memories in a single flat directory | Trivial implementation | Breaks at 10k files | Only if you have a clear migration path to sharding |
| Hardcoding absolute paths in settings.json | Works for one machine | Breaks on multi-machine users | Never — use `cortex hook run` entry point |
| Shell-script hook wrapper | Fast to write | Breaks on Windows, venv confusion | Never |
| Text-mode stdin on Windows | Default Python behavior | Mangles \r\n and binary data | Never for MCP protocol stream |
| Custom MCP framing (Content-Length) | "Matches LSP" | Silently fails with Claude Code | Never |
| Silent rule parse failures | Lenient parser feels friendly | Users think rules work when they don't | Never — always surface errors |
| "Stdlib only" without pinning Python version | Marketing point | Version-gated bugs | Acceptable if minimum is 3.11+ and enforced in CI |
| Grep over full tree on every search | Simple | Slow at 10k+ files | Until Phase 5 optimization (FTS via sqlite3) |
| Append-mode memory writes | Fewer fsync calls | Concurrent corruption | Never — atomic replace only |
| Per-tool name without prefix (`save`, `search`) | Shorter | Collisions with other MCP servers | Never — always prefix with `cortex_` |
| Auto-save by message count | Easy feature | Mid-task junk memories | Never default-on; only opt-in with task-boundary trigger |

---

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| Claude Code MCP client | Assuming Content-Length framing or LSP patterns | Newline-delimited JSON-RPC, one message per line, no length headers |
| Claude Code hook system | Using `{"block": true}` or `{"action": "deny"}` | `{"decision": "block", "reason": "..."}` AND exit 2 AND stderr (belt-and-suspenders) |
| Claude Code settings.json | Absolute paths to hook scripts | `cortex hook run` entry-point command, requires `cortex` on PATH |
| Windows cmd.exe / PowerShell | Emoji in CLI output | ASCII-only output, or `sys.stdout.reconfigure(encoding="utf-8")` |
| Windows filesystem | `os.rename()` for atomic replace | `os.replace()` (cross-platform atomic) after `os.fsync()` |
| Git Bash / MSYS2 | Assuming POSIX path semantics | Native Python path handling, no shell-out to POSIX tools |
| PyPI | Using "cortex" or "cortex-memory" | Verified names: `cortex-cc`, `cortex-hook`, `cortex-rules` — or pick a unique name |
| Multiple MCP servers in one Claude Code session | Generic tool names (`save`, `list`) | Prefix all tools with `cortex_` |
| Python venvs | Hook uses system Python, not venv | Entry-point script via pip's generated shim resolves to correct interpreter |
| Dotfile sync (chezmoi, stow) | Syncing settings.json with machine-specific paths | Hook command `cortex hook run` is machine-agnostic |
| SQLite (if used for FTS) | Concurrent writers without WAL mode | `PRAGMA journal_mode=WAL` + single writer thread |

---

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| Python cold-start on every hook invocation | 100-250ms overhead per tool call, "Claude Code feels slow" | Keep imports minimal; `python -X importtime` < 50ms | Any usage on Windows; any user with 10+ hooks/tool calls |
| Regex backtracking on large files | Hook hangs, CPU pegged | Anchored patterns, timeout guards, input size cap | One user with a 500KB memory file |
| Grep over full memory tree | Search latency > 1s | Directory sharding; optional sqlite3 FTS index | 10k+ files or 100MB+ total |
| Rule file re-parsing on every hook call | Latency grows linearly with rule count | Compile rules to a cache keyed on source mtime | 50+ rules |
| File handle leaks in long-running server | Eventual "too many open files" error | Context managers everywhere; never bare `open()` | Weeks of uptime |
| JSON parsing in a loop without bulk read | Slow response to batch operations | Read once, parse once; batch tool calls when possible | Bulk import/export operations |
| Synchronous writes in MCP handler | Blocks other tool calls during save | Serialized writer thread with async signaling | Concurrent clients or auto-save + user save overlap |
| Directory walk without pruning | `os.walk` on 40k files takes seconds | Sharded paths allow pruning by date/category | 10k+ files |
| Full file read for pattern match | Memory pressure on large files | Line-by-line iteration for files > 1MB | Single 10MB memory file |
| Rebuilding FTS index from scratch | First-search latency spike | Incremental index updates on save | Any user upgrading from grep-only |

---

## Security Mistakes

| Mistake | Risk | Prevention |
|---------|------|------------|
| Rules marketed as a security sandbox | Users rely on Cortex for real security, get bypassed | Document threat model: "consistency enforcer, not sandbox" |
| Shell injection via rule input (using `eval`, `shell=True`) | User rule content becomes code execution | No `eval`, no `exec`, no `shell=True`, no `os.system`; rules are data not code |
| Reading memory files without sanitizing paths | Path traversal (`../../../etc/passwd` in a memory name) | Validate memory names against `^[a-zA-Z0-9_\-]+$`; reject `..`, absolute paths, null bytes |
| Logging full memory content to `~/.cortex/blocks.log` | Secrets in memories end up in logs | Log rule name + timestamp + tool name; never log content |
| Rule files sourced from the internet (e.g., `cortex rule install <url>`) | Malicious rules block user's legitimate tools | Don't implement remote rule install in v1; require local file path |
| Writing credentials to memory file in plaintext | Plaintext creds at rest | `cortex save` detects common secret patterns (API keys, tokens) and warns or refuses |
| Rules enforceable by one user on another's machine (shared config) | Social engineering via dotfile repo | Rules loaded from user's `~/.cortex/`; no system-wide rule path without opt-in |
| No file permissions on `~/.cortex/` | Other users on shared system read memories | On POSIX, `chmod 700 ~/.cortex/` on init; on Windows, default ACL sufficient |
| MCP server exposes file read tool without path restriction | AI uses Cortex to read `/etc/shadow` | Tool operations scoped to `~/.cortex/memories/` only; never arbitrary FS |
| Hook errors expose paths/secrets in user-facing error messages | Info disclosure | Error messages to stderr show rule name only; full details in log file |

---

## UX Pitfalls

| Pitfall | User Impact | Better Approach |
|---------|-------------|-----------------|
| Auto-save fires mid-task | Junk memories, signal degradation | Explicit save only in v1; task-boundary trigger if auto added |
| Silent rule failures | User thinks rules enforce when they don't | Canary rule on init; `cortex status` surfaces load errors |
| No preview of what a rule will block | Rules shipped blind, cause false positives | `cortex rule test <rule> <input>` dry-run |
| No override when a rule fires unexpectedly | User disables Cortex entirely in frustration | `cortex pause <rule>` temporary bypass with expiry |
| Emoji in CLI output | Crashes Windows cmd.exe | ASCII-only output |
| "Installation took 20 minutes" (MemPalace) | Users abandon before first use | One-command install, verified on all 3 OSes in CI |
| 19 MCP tools to learn (MemPalace) | Overwhelming, hard to remember | 4-6 tools max, all prefixed, documented with examples |
| Custom compression dialect (MemPalace AAAK) | Users can't read their own memories | Plain markdown, no transformations |
| Opaque error messages | Users can't self-diagnose | Every error includes: what failed, why, what to do next |
| No `doctor` command | Users paste tracebacks in issues | `cortex doctor` checks install, PATH, settings.json, hook wiring, canary rule |
| Memory files hidden in obscure paths | Users can't edit with their editor | Default `~/.cortex/memories/`, visible, documented |
| Contradictory memories with no supersession | AI behaves inconsistently, loses trust | Timestamps + recency weighting + explicit `replaces:` field |
| No way to see what got blocked and why | Users can't audit enforcement | Block log + `cortex blocks` command showing recent decisions |
| Memories and rules conceptually entangled | Users confused "is this a memory or a rule?" | Two clearly separate commands + directories: `memories/` and `rules/` |
| "Zero dependency" claim plus optional SQLite | Users feel misled when FTS pulls sqlite3 | sqlite3 is stdlib; document clearly as "stdlib-only," not "no files outside venv" |

---

## "Looks Done But Isn't" Checklist

Things that appear complete but are missing critical pieces.

- [ ] **MCP server:** Works when manually tested via a harness — verify Claude Code actually connects and receives initialize response (different code path due to stdin/stdout binary mode)
- [ ] **Hook installed:** `settings.json` updated — verify the hook **actually fires** on a real tool call (canary rule test)
- [ ] **Hook blocks:** Exit 2 returned and stderr written — verify Claude Code **actually respects the block** (some JSON shapes don't work in newer versions)
- [ ] **Rule created:** File saved in `~/.cortex/rules/` — verify it passes strict parser + shows up in `cortex status` + canary fires correctly
- [ ] **Memory saved:** File exists on disk — verify frontmatter parses back cleanly + content isn't corrupted + atomic write was used
- [ ] **Search works:** Returns results in dev — verify performance at 10k files (benchmark gate)
- [ ] **Init succeeds:** CLI exits 0 — verify `~/.cortex/` actually created with correct permissions + default rules installed + Claude Code settings.json updated
- [ ] **Cross-platform:** Tests pass in CI — verify CI matrix includes Windows (not just POSIX), tests actually run the binary mode paths
- [ ] **Unicode safe:** Happy-path CLI output works — verify Windows cmd.exe with cp1252 locale (not just Windows Terminal)
- [ ] **Install works:** `pip install <name>` resolves — verify in a clean venv, on all 3 OSes, that entry points are generated and `cortex` is on PATH
- [ ] **Hook is fast:** Feels fine locally — verify p50 and p95 latency via `cortex hook bench` meets budget on Windows (slowest platform)
- [ ] **No stdout pollution:** No obvious `print()` calls — verify server startup emits zero bytes to stdout before first legitimate JSON-RPC response (grep codebase + integration assert)
- [ ] **Concurrent-safe:** Single tool calls work — verify 100 parallel saves produce 100 correct files with no corruption
- [ ] **Rule schema:** Example rules in docs — verify the docs are generated from or tested against the actual parser (not hand-written drift)
- [ ] **Doctor passes:** `cortex doctor` says OK — verify it actually exercises every critical path, not just checks file existence
- [ ] **Name is clear:** README uses the project name — verify the PyPI package name matches and is not taken
- [ ] **Uninstall works:** `pip uninstall` succeeds — verify it removes settings.json entries too, or documents the manual cleanup step
- [ ] **First-time user can install + write a rule + see it block** in under 5 minutes, without editing any files by hand — verify with a fresh user test

---

## Recovery Strategies

When pitfalls occur despite prevention, how to recover.

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| Wrong MCP framing (works nowhere) | LOW | Fix transport layer, ship patch; users update via `pip install -U` |
| Stdout pollution | LOW | Fix offending `print()`; ship patch |
| Windows text-mode stdin | LOW | Add `msvcrt.setmode` at entry; ship patch |
| Slow hook | MEDIUM | Profile, compile rules, lazy imports; may require architecture change (compiled cache) |
| Hook silently swallows errors | LOW | Fix error policy; ship patch; surface past errors in next `status` call |
| Wrong decision JSON format | LOW | Update to current schema; ship patch; document version compat |
| PyPI name taken after launch | HIGH | Rename project or publish under prefixed name; migration notice; users must `pip uninstall old && pip install new` |
| File corruption from concurrent writes | HIGH | `cortex repair` command that salvages what it can; users must manually review affected files; ship atomic-write fix |
| Rule false positives | MEDIUM | Ship override mechanism if absent; users add exceptions or `cortex pause <rule>`; improve rule templates |
| Rule false negatives (silent parse failure) | MEDIUM | Ship strict parser + lint; `cortex status` surfaces the error going forward |
| Backslash path JSON corruption | LOW | Replace string concat with `json.dumps`; ship patch |
| Absolute hook paths in settings.json | MEDIUM | Migrate to `cortex hook run` entry point; `cortex init --migrate` rewrites settings.json |
| Bash hook doesn't run on Windows | LOW | Rewrite as Python entry point; ship patch; update init to regenerate settings.json |
| Regex ReDoS | MEDIUM | Add timeout guard; lint existing rules; users may need to rewrite their patterns |
| YAML frontmatter edge case | LOW | Ship strict subset parser; users fix their files guided by `cortex lint` |
| Unbounded memory growth | HIGH | Ship sharding migration: `cortex migrate` moves existing flat files to sharded dirs |
| Stale memory conflicts | MEDIUM | Ship supersession field; users tag old memories via `cortex supersede` command |
| AI rule bypass | HIGH | Improve rule schema (resource-scoped rules); update threat model docs; users may need to rewrite rules |
| Rule conflict undefined | MEDIUM | Ship explicit precedence; users audit via `cortex rule test` |
| Tool name collision | MEDIUM | Rename all tools with prefix; breaking change — users must update any tool-name references |
| Init can't create `~/.cortex/` | LOW | Add error handling + `CORTEX_HOME` env var; ship patch |
| Auto-save mid-task garbage | MEDIUM | Change trigger to task boundary; `cortex cleanup --auto-saved --before <date>` removes historical junk |

---

## Pitfall-to-Phase Mapping

How roadmap phases should address these pitfalls.

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| Wrong MCP framing (#1) | Phase 1 (MCP core) | Raw handshake test with newline-delimited JSON; real Claude Code integration test |
| Stdout pollution (#2) | Phase 1 (MCP core) | CI grep for `print(`; integration test asserts zero bytes on stdout before first response |
| Windows text-mode stdin (#3) | Phase 1 (MCP core) | Cross-platform CI (Windows job mandatory); test with CRLF in payload |
| Unicode CLI crash (#4) | Phase 1 (CLI scaffold) + Phase 6 (packaging) | Windows cmd.exe test with cp1252 locale; ASCII-only CLI output rule |
| Slow hook (#5) | Phase 3 (hook + rules) | `cortex hook bench` p50<50ms, p95<150ms on Windows CI — exit criterion |
| Hook error handling (#6) | Phase 3 (hook + rules) | Chaos test: corrupt rule file, assert Claude Code still works; assert log is written |
| Wrong block JSON format (#7) | Phase 3 (hook + rules) | End-to-end block test via real Claude Code harness |
| PyPI name taken (#8) | Phase 0 (pre-code setup) | Name verified + reserved on PyPI before Phase 1 begins |
| Concurrent file corruption (#9) | Phase 2 (storage) | 100-parallel-writers test in CI; atomic replace mandatory |
| Rule false positives (#10) | Phase 3 (rules) | Rule schema includes `applies_to`; override mechanism shipped in v1 |
| Rule false negatives (#11) | Phase 3 (rules) | Strict parser + `cortex lint` + canary rule + surfaced load errors |
| Backslash JSON corruption (#12) | Phase 1 (MCP core) | `json.dumps` everywhere; lint rule against f-string JSON; Windows path test payload |
| Absolute hook paths (#13) | Phase 3 (hook install) + Phase 6 (packaging) | Hook registered as `cortex hook run` entry point; `cortex doctor` verifies PATH |
| Bash script hook (#14) | Phase 3 (hook install) | No shell scripts in repo; pip entry point generates native shim |
| Regex ReDoS (#15) | Phase 2 (search) + Phase 3 (rules) | Timeout guard; rule lint against adversarial input |
| YAML frontmatter edge cases (#16) | Phase 2 (storage) | Strict subset documented; `cortex lint`; consider TOML if Python 3.11+ minimum |
| Unbounded memory growth (#17) | Phase 2 (storage design) + Phase 5 (scale) | Sharding from day one; benchmark at 10k files |
| Auto-save mid-task (#18) | Defer to Phase 4; explicit save only in v1 | User test shows auto-save disabled default; task-boundary trigger when enabled |
| Stale memories (#19) | Phase 2 (schema) + Phase 4 (supersession) | Timestamps baseline; supersession field + `replaces:` in Phase 4 |
| AI rule bypass (#20) | Phase 3 (rules schema) + Phase 0 (docs) | Resource-scoped rules in schema; README threat model section |
| Rule conflicts (#21) | Phase 3 (rules) | Explicit precedence documented; `cortex rule test` shows winning rule |
| Tool name collisions (#22) | Phase 1 (MCP tool design) | All tools prefixed `cortex_`; linted in CI |
| No MCP test harness (#23) | Phase 1 (MCP core) | Harness is part of Phase 1 deliverable; CI uses it |
| Python version feature gap (#24) | Phase 0 (decision) + Phase 6 (packaging) | Minimum version pinned; CI runs against minimum; `python_requires` in `pyproject.toml` |
| Init path edge cases (#25) | Phase 1 (CLI init) + Phase 6 (packaging) | `cortex doctor` validates; `CORTEX_HOME` env var supported |

---

## MemPalace Lessons (Captured)

Direct lessons from the user's first-hand MemPalace experience, encoded above:

1. **167MB dependency tree + ChromaDB** → Cortex hard constraint: Python stdlib only, no pip deps. (Pitfall #24 + constraint enforcement.)
2. **Wheels failing on Windows** → Constraint pre-empts this; no compiled dependencies.
3. **Custom JSON-RPC framing requiring a wrapper** → Pitfall #1. Newline-delimited JSON-RPC only.
4. **Windows text-mode stdin mangled `\r\n`** → Pitfall #3. Binary mode on Windows from day one.
5. **Unicode emoji crashed init on cp1252** → Pitfall #4. ASCII-only CLI output.
6. **Forward/backslash JSON corruption** → Pitfall #12. `json.dumps` discipline + path normalization.
7. **19 MCP tools was overwhelming** → Constraint: 4-6 tools max, all prefixed.
8. **Custom AAAK compression dialect was unreadable** → Constraint: plain markdown, no transformations.
9. **96.6% LongMemEval didn't translate to ease of use** → UX-first discipline: install under 5 min, first rule under 5 min, or ship fails.
10. **20 minutes of debugging to install** → Pitfall #25 + packaging gate; `cortex doctor` for self-diagnosis.
11. **Hook/prompt-level "please remember" didn't enforce** → Core differentiator: hook-level blocking. Pitfalls #5-#7, #10-#11, #20-#21 are all about making that real.

---

## Sources

**High-confidence (official specs and docs):**
- [MCP Specification — Transports](https://modelcontextprotocol.io/specification/2025-06-18/basic/transports) — confirms newline-delimited JSON-RPC for stdio, no Content-Length, no embedded newlines
- [Claude Code Hooks Reference](https://code.claude.com/docs/en/hooks) — hook JSON schemas, exit code semantics, decision format
- [Python os.replace docs + atomic write recipes](https://code.activestate.com/recipes/579097-safely-and-atomically-write-to-a-file/) — cross-platform atomic rename pattern
- [Python bug tracker #4571 — stdin binary mode on Windows](https://bugs.python.org/issue4571) — Windows text-mode stdin CRLF mangling
- [Python bug tracker #27179 — subprocess encoding on Windows](https://bugs.python.org/issue27179) — cp1252 encoding pitfalls

**Medium-confidence (community / issue tracker verified):**
- [Foojay: Understanding MCP Through Raw STDIO Communication](https://foojay.io/today/understanding-mcp-through-raw-stdio-communication/) — confirms line-delimited framing, one JSON per line
- [IBM MCP Context Forge — Python MCP server best practices](https://ibm.github.io/mcp-context-forge/best-practices/developing-your-mcp-server-python/) — binary mode recommendation for stdio transport
- [Claude Code hooks performance issue #1530 on ruflo](https://github.com/ruvnet/ruflo/issues/1530) — real-world ~20s latency from compounding hooks
- [claudekit hook profiling guide](https://github.com/carlrannaberg/claudekit/blob/main/docs/guides/hook-profiling.md) — hook latency budgets and profiling
- [Smartscope — Claude Code Hooks Complete Guide (March 2026)](https://smartscope.blog/en/generative-ai/claude/claude-code-hooks-guide/) — current JSON schema formats
- [Cursor forum — MCP tool name collision bug](https://forum.cursor.com/t/mcp-tools-name-collision-causing-cross-service-tool-call-failures/70946) — real collision incidents
- [LetsDoDevOps — Fixing MCP Tool Name Collisions](https://www.letsdodevops.com/p/fixing-mcp-tool-name-collisions-when) — namespace prefix best practice
- [OpenAI Agents SDK issue #464 — duplicate tool names](https://github.com/openai/openai-agents-python/issues/464) — framework-level collision errors
- [MCP Discussion #291 — tool name resolution with multiple servers](https://github.com/orgs/modelcontextprotocol/discussions/291) — lack of namespacing in spec
- [python-atomicwrites](https://github.com/untitaker/python-atomicwrites) — atomic write patterns for cross-platform
- [Python Discuss — forcing stdin/stdout encoding](https://discuss.python.org/t/forcing-sys-stdin-stdout-stderr-encoding-newline-behavior-programmatically/15437) — reconfigure patterns
- [PyPI: cortex](https://pypi.org/project/cortex/), [cortex-ai-memory](https://pypi.org/project/cortex-ai-memory/), [cortex-memory-sdk](https://pypi.org/project/cortex-memory-sdk/), [claude-cortex](https://pypi.org/project/claude-cortex/) — verified name conflicts on PyPI 2026-04-11
- [Mem0 blog: State of AI Agent Memory 2026](https://mem0.ai/blog/state-of-ai-agent-memory-2026) — Mem0 hybrid strategy context
- [TechCrunch: Mem0 raises $24M](https://techcrunch.com/2025/10/28/mem0-raises-24m-from-yc-peak-xv-and-basis-set-to-build-the-memory-layer-for-ai-apps/) — funding-driven cloud focus

**User-provided (HIGH confidence, first-hand):**
- MemPalace installation experience: 167MB ChromaDB cache, 60+ pip deps, custom JSON-RPC requiring wrapper, Windows text-mode stdin failures, Unicode cp1252 crashes, forward/backslash JSON issues, 19 MCP tools, AAAK compression, ~20 min install debugging
- The missing-enforcement insight: rules get read then ignored → hook-level blocking is the real differentiator

---
*Pitfalls research for: Cortex (MCP server + hook-based rules + local markdown memory)*
*Researched: 2026-04-11*
