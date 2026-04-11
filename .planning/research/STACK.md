# Stack Research — Cortex

**Domain:** AI memory system + MCP server + PreToolUse hooks (zero-dependency Python)
**Researched:** 2026-04-11
**Confidence:** HIGH

## TL;DR

- **Language:** Python **3.10+** (not 3.9 — EOL October 2025). Stdlib only.
- **Build backend:** `hatchling` via `pyproject.toml` (PEP 621, single file, no `setup.py`).
- **MCP protocol version:** Negotiate **`2025-11-25`** (current spec). Echo back whatever the client sends to remain forward-compatible. Claude Code currently sends `2025-11-25`.
- **Transport:** stdio, newline-delimited JSON (NDJSON), UTF-8, `stdout` = protocol only, `stderr` = logs.
- **Hook contract:** Read JSON from stdin, write `hookSpecificOutput` JSON to stdout on exit 0, or write human error to stderr and exit 2 to block.
- **DO NOT USE:** `mcp` (official SDK), `fastmcp`, `chromadb`, `numpy`, `tomli`, `pydantic`, any external dep — they all violate the zero-dependency constraint and were the root cause of MemPalace's failure.

---

## Recommended Stack

### Core Technologies

| Technology | Version | Purpose | Why Recommended |
|---|---|---|---|
| **Python interpreter** | **3.10+** (target 3.11 for testing) | Runtime | 3.9 reached EOL Oct 2025 — unsafe for new projects. 3.10 is the lowest version that is still receiving security patches as of 2026-04. 3.10 adds `match` statements, better error messages, and `X \| Y` union syntax that we will use. If we go to 3.11 we get `tomllib` for free but we don't need it. |
| **JSON-RPC 2.0 over stdio** | MCP `2025-11-25` (primary), also accept `2024-11-05` | Wire protocol with Claude Code | Confirmed: Claude Code sends `"protocolVersion": "2025-11-25"` in the `initialize` request as of 2026-02+. MCP spec requires the server to echo the same version back if supported, or offer its own. Line-delimited JSON — NOT Content-Length framed (LSP-style). One JSON object per line on stdin/stdout, no length prefix. |
| **`pyproject.toml` + `hatchling`** | hatchling 1.x | Build backend | PEP 621 metadata, single source of truth, no `setup.py`. Hatchling is PyPA-maintained (same umbrella as setuptools) and is the default uv/modern recommendation. Zero runtime dependencies — `hatchling` is only required at build time, not install time. End users install with `pip install cortex-memory` and pull zero transitive deps. |
| **Plain markdown files on disk** | — | Storage | Grep-searchable, git-trackable, human-readable, zero lock-in. Per PROJECT.md constraint. |

### Python Standard Library Modules Used

Every module below ships with CPython 3.10 — zero pip installs required.

| Module | Purpose in Cortex | Why this over alternatives |
|---|---|---|
| **`json`** | Parse/serialize every MCP and hook message | Only JSON library we need. `json.loads()` / `json.dumps(..., ensure_ascii=False)` for UTF-8 friendliness. |
| **`sys`** | `sys.stdin`, `sys.stdout`, `sys.stderr`, `sys.argv`, `sys.exit()` | The stdio loop reads `sys.stdin` line-by-line and writes to `sys.stdout`. All logs go to `sys.stderr` — **stdout is reserved for protocol messages only**. |
| **`pathlib`** | All filesystem path handling | Use `pathlib.Path` everywhere, never `os.path`. Use `Path.as_posix()` when serializing paths into JSON responses — Windows backslashes in JSON are legal but confuse cross-platform clients and grep. Use `Path.home()` for `~/.cortex/`. |
| **`os`** | `os.environ` only (for `CORTEX_DIR` override), `os.fsync()` for durable writes | `os.path` is banned in Cortex code — always use `pathlib`. |
| **`re`** | Grep engine (regex-based search across markdown files) | Stdlib `re` is fast enough for 10k files. For fixed-string search, use `str.__contains__` instead for speed. `re.IGNORECASE` flag for case-insensitive search. |
| **`subprocess`** | None in MCP server. Used in hook script only if shelling out (we won't). | Cortex hooks are pure Python scripts invoked by Claude Code — we do not spawn subprocesses ourselves. |
| **`argparse`** | `cortex init`, `cortex serve`, `cortex add-rule` CLI | Stdlib CLI parser. Enough for our 4-6 subcommands. No `click` or `typer`. |
| **`datetime`** | Memory timestamps, ISO 8601 serialization | `datetime.now(timezone.utc).isoformat()` for file frontmatter. |
| **`uuid`** | Memory file IDs / filenames | `uuid.uuid4().hex[:8]` for short slugs appended to filenames. |
| **`hashlib`** | Rule ID stable hashing (SHA1 short hash of rule text) | Deterministic IDs so the same rule text always produces the same rule ID. |
| **`tempfile`** | Atomic writes (write to temp, rename to target) | Prevents corrupted memory files if writer crashes mid-write. |
| **`shutil`** | `shutil.move()` for the atomic-rename dance on Windows (where `os.rename` can fail if target exists) | Cross-platform atomic replace. |
| **`io`** | `io.TextIOWrapper` to reconfigure stdin/stdout to UTF-8 line-buffered on Windows | **Required** — Windows defaults stdin/stdout to the system codepage (often cp1252), which breaks UTF-8 memory content. |
| **`logging`** | Structured stderr logging in MCP server and hook | Configure with `stream=sys.stderr`, never `stream=sys.stdout`. Hard rule. |
| **`unittest`** | Test runner | Stdlib — no pytest. See Testing section below. |
| **`unittest.mock`** | Mocking in tests | Stdlib, included with unittest. |
| **`importlib.metadata`** | Read the installed package version for `serverInfo.version` in the MCP initialize response | Stdlib since 3.8, stable since 3.10. |
| **`traceback`** | Format exceptions for stderr logging without crashing the stdio loop | Never let a tool handler exception kill the server. |
| **`platform`** | Detect Windows for the `cmd /c` install-hint and stdio reconfiguration | `platform.system() == "Windows"`. |

**Deliberately NOT used:**
- `asyncio` — the MCP stdio loop is inherently single-threaded request/response. Sync code with a blocking `for line in sys.stdin:` loop is simpler, shorter, and avoids the Windows asyncio issues that plague the official python-sdk (see modelcontextprotocol/python-sdk#552 — Windows 11 hangs indefinitely with asyncio-based stdio).
- `tomllib` — we have no TOML to parse at runtime. `pyproject.toml` is only read by the build tool, not by Cortex itself.
- `os.path` — `pathlib` covers every case. Banning `os.path` in the codebase prevents the backslash-in-JSON bug class entirely.
- `sqlite3` — tempting for indexing, but violates "plain markdown files" constraint. Grep is fast enough per PROJECT.md.

### Development Tools

| Tool | Purpose | Notes |
|---|---|---|
| **`hatch` / `hatchling`** | Build wheels and sdist for PyPI | Dev-only dependency; not shipped to users. Invoked via `python -m build` which auto-installs the build backend in an isolated env. |
| **`python -m build`** | Standard PEP 517 frontend | Stdlib-ish. `pip install build` once in the dev env; end users never see this. |
| **`twine`** | Upload to PyPI | Dev-only. `python -m twine upload dist/*`. |
| **`python -m unittest discover`** | Test runner | No pytest. Stdlib only. |
| **GitHub Actions matrix** | CI on Windows, macOS, Linux × Python 3.10, 3.11, 3.12 | Must catch Windows path and encoding bugs. |

---

## MCP Protocol Specifics (HIGH confidence — verified against spec)

### 1. The stdio loop (pseudocode)

```python
import sys, json, io

# Windows UTF-8 fix — MUST be before any I/O
sys.stdin = io.TextIOWrapper(sys.stdin.buffer, encoding="utf-8", newline="\n")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", newline="\n", line_buffering=True)

for line in sys.stdin:            # blocking readline — one JSON object per line
    line = line.strip()
    if not line:
        continue
    try:
        msg = json.loads(line)
    except json.JSONDecodeError:
        continue                  # silently ignore malformed lines per spec
    response = handle(msg)        # dispatch to initialize / tools/list / tools/call
    if response is not None:      # notifications get no response
        sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
        sys.stdout.flush()        # belt-and-suspenders; line_buffering should handle it
```

**Why `line_buffering=True` AND explicit `flush()`:** on Windows, Python's `TextIOWrapper` line-buffering has known edge cases when stdout is a pipe (not a tty). Always flush after each message. Confirmed by stdio MCP author blog posts as the #1 source of "why isn't my server responding" bugs.

### 2. Initialize request/response

**Incoming (from Claude Code):**
```json
{"jsonrpc":"2.0","id":0,"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{"roots":{"listChanged":true},"sampling":{}},"clientInfo":{"name":"claude-code","version":"2.1.x"}}}
```

**Cortex response (echo the version the client sent, as long as it's recognized):**
```json
{"jsonrpc":"2.0","id":0,"result":{"protocolVersion":"2025-11-25","capabilities":{"tools":{"listChanged":false}},"serverInfo":{"name":"cortex","version":"0.1.0"}}}
```

**Rules enforced by Cortex:**
- Echo the exact `protocolVersion` the client sent, if it's in our supported set `{"2025-11-25", "2025-03-26", "2024-11-05"}`. Otherwise respond with `"2025-11-25"` and let the client decide to disconnect.
- `capabilities.tools` is present (we have tools); set `listChanged: false` in v1 (we don't send dynamic updates).
- Do NOT advertise `resources`, `prompts`, `logging`, `sampling`, `tasks`, `elicitation`, or `experimental`. Tools only.
- `serverInfo.version` is populated from `importlib.metadata.version("cortex-memory")`.

### 3. Initialized notification (client → server, no response)

```json
{"jsonrpc":"2.0","method":"notifications/initialized"}
```

Cortex must recognize this and NOT send a response (it's a JSON-RPC notification — no `id` field). Use the absence of `id` as the detection rule.

### 4. tools/list

**Incoming:**
```json
{"jsonrpc":"2.0","id":1,"method":"tools/list"}
```

**Response:**
```json
{"jsonrpc":"2.0","id":1,"result":{"tools":[
  {
    "name":"save_memory",
    "description":"Save a memory to long-term storage as a markdown file. Use when the user shares a preference, decision, or important context.",
    "inputSchema":{
      "type":"object",
      "properties":{
        "title":{"type":"string","description":"Short descriptive title"},
        "content":{"type":"string","description":"The full memory content in markdown"},
        "category":{"type":"string","enum":["preference","decision","context","project"]}
      },
      "required":["title","content"]
    }
  }
]}}
```

Keep descriptions short and action-oriented — the LLM reads these to decide when to call the tool.

### 5. tools/call

**Incoming:**
```json
{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"save_memory","arguments":{"title":"Prefer pathlib","content":"Always use pathlib, never os.path","category":"preference"}}}
```

**Response (success):**
```json
{"jsonrpc":"2.0","id":2,"result":{"content":[{"type":"text","text":"Saved memory: prefer-pathlib.md"}],"isError":false}}
```

**Response (tool failure — note: error lives in `result`, not JSON-RPC `error`):**
```json
{"jsonrpc":"2.0","id":2,"result":{"content":[{"type":"text","text":"Failed to save: disk full"}],"isError":true}}
```

**Response (protocol error — unknown tool):**
```json
{"jsonrpc":"2.0","id":2,"error":{"code":-32602,"message":"Unknown tool: save_memoy"}}
```

Distinction matters: `isError:true` is a business failure the model should retry or adjust. JSON-RPC `error` is a protocol bug the model can't recover from.

---

## PreToolUse Hook Specifics (HIGH confidence — verified against docs.claude.com/hooks)

### 1. Configuration (Cortex writes to `~/.claude/settings.json` during `cortex init`)

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "python -m cortex.hooks.pretool"
          }
        ]
      }
    ]
  }
}
```

- `matcher: "*"` to match every tool call — Cortex rules may apply to any tool, not just Bash.
- `type: "command"` — the only type we use.
- `command: "python -m cortex.hooks.pretool"` — invokes the hook as a Python module, so it works regardless of install path. On Windows this works as-is because Python is on PATH. (No `cmd /c` needed for `python` specifically — that's only for `npx`.)

### 2. Hook input (Claude Code → hook stdin, single JSON line)

```json
{
  "session_id": "abc123",
  "transcript_path": "/home/user/.claude/projects/.../conv.jsonl",
  "cwd": "/home/user/my-project",
  "permission_mode": "default",
  "hook_event_name": "PreToolUse",
  "tool_name": "Bash",
  "tool_input": { "command": "rm -rf /" },
  "tool_use_id": "toolu_01ABC..."
}
```

Cortex's hook reads this, loads `~/.cortex/rules/*.md`, checks whether any active rule is violated by the pending `tool_name` + `tool_input`, and decides to allow or deny.

### 3. Hook output (hook stdout → Claude Code)

**Allow (silent — just exit 0 with no output):** simplest case, no rules matched.

**Deny with structured reason (preferred for Cortex):**
```json
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": "Cortex rule 'always confirm before action' blocks this tool call. Ask the user to confirm before proceeding."
  }
}
```
Then `exit 0`. The JSON on stdout is parsed by Claude Code; `permissionDecisionReason` is shown to Claude so it can explain to the user what happened and adjust.

**Deny with simple stderr (fallback):**
```
Blocked by Cortex rule: always confirm before action
```
Then `exit 2`. Simpler but loses the structured context that allows Claude to react intelligently.

**Cortex uses the structured form** so rules can provide actionable guidance to the model, not just block it.

### 4. Decision field values

| `permissionDecision` | Meaning |
|---|---|
| `"allow"` | Skip any permission prompts — auto-allow |
| `"deny"` | Block the tool call |
| `"ask"` | Prompt the user for confirmation |
| `"defer"` | Fall through to default handling |

**Precedence when multiple hooks respond:** `deny > defer > ask > allow`. Cortex's hook only needs to deny or stay silent.

### 5. Exit codes

| Code | Behavior |
|---|---|
| `0` | Parse stdout as JSON `hookSpecificOutput` for decision (or allow if no JSON) |
| `2` | Blocking error — stderr text shown to Claude, tool blocked |
| Any other | Non-blocking error — stderr first line shown in transcript, tool proceeds |

**Cortex must never crash.** Wrap the entire hook in `try/except`, log tracebacks to stderr, and exit 0 with an allow-by-default on any internal error. A crashing rule system that blocks every tool call is worse than no rule system.

---

## Packaging (`pyproject.toml`)

### Minimum viable `pyproject.toml`

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "cortex-memory"
version = "0.1.0"
description = "Zero-dependency AI memory system for Claude Code with rules enforcement"
readme = "README.md"
license = { text = "MIT" }
requires-python = ">=3.10"
authors = [{ name = "Mo Hendawy" }]
keywords = ["mcp", "claude-code", "memory", "ai", "rules"]
classifiers = [
  "Development Status :: 3 - Alpha",
  "License :: OSI Approved :: MIT License",
  "Operating System :: OS Independent",
  "Programming Language :: Python :: 3",
  "Programming Language :: Python :: 3.10",
  "Programming Language :: Python :: 3.11",
  "Programming Language :: Python :: 3.12",
  "Programming Language :: Python :: 3.13",
  "Topic :: Software Development",
]
# CRITICAL: NO dependencies key at all. Zero pip deps.

[project.scripts]
cortex = "cortex.cli:main"

[project.urls]
Homepage = "https://github.com/Mo-Hendawy/cortex"
Repository = "https://github.com/Mo-Hendawy/cortex"
Issues = "https://github.com/Mo-Hendawy/cortex/issues"

[tool.hatch.build.targets.wheel]
packages = ["src/cortex"]
```

**Key choices explained:**
- **No `[project.dependencies]` key.** Hatchling defaults to empty. Users run `pip install cortex-memory` and get zero transitive installs — MemPalace's 60+ deps nightmare is structurally impossible.
- **`requires-python = ">=3.10"`** — overrides PROJECT.md's 3.9+ constraint because 3.9 is EOL and shipping a new 2026 project on an EOL runtime is irresponsible. Still widely available: macOS Homebrew ships 3.12, Ubuntu 22.04 LTS ships 3.10, Windows Store ships 3.12, `pyenv` covers anyone stuck behind.
- **`packages = ["src/cortex"]`** — use the `src/` layout. Prevents accidentally importing from the working directory instead of the installed package during testing (a classic packaging footgun).
- **`[project.scripts] cortex = "cortex.cli:main"`** — creates a `cortex` executable on PATH. Pip handles cross-platform shim creation (including `cortex.exe` on Windows).

### Including the hook script as package data

The hook is a Python module (`cortex.hooks.pretool`), **not** a loose shell script. This is the best approach because:
1. No file-permission issues on Windows (shebang lines don't work on Windows).
2. Invoked as `python -m cortex.hooks.pretool` which is guaranteed to work wherever the package is installed.
3. No `package_data` / `MANIFEST.in` gymnastics needed — `.py` files inside the package are included automatically by hatchling.

If we ever need non-Python files (templates, default rule markdown), use hatchling's default inclusion:
```toml
[tool.hatch.build.targets.wheel.force-include]
"src/cortex/templates" = "cortex/templates"
```

### Directory layout

```
cortex/
  pyproject.toml
  README.md
  LICENSE
  src/
    cortex/
      __init__.py            # exports version
      __main__.py            # enables `python -m cortex`
      cli.py                 # argparse-based CLI (init, serve, add-rule, etc)
      server.py              # MCP stdio loop
      storage.py             # markdown file read/write
      search.py              # grep-based search
      rules.py               # rule storage + matching
      hooks/
        __init__.py
        pretool.py           # PreToolUse hook — stdin→stdout
  tests/
    test_server.py
    test_storage.py
    test_search.py
    test_hook.py
    fixtures/
```

---

## Testing Strategy (stdlib only)

### Test runner: `unittest` + `python -m unittest discover`

```python
# tests/test_server.py
import unittest
import json
import subprocess
import sys

class TestMCPServer(unittest.TestCase):
    def test_initialize_roundtrip(self):
        """Spawn cortex serve, send initialize, verify response."""
        proc = subprocess.Popen(
            [sys.executable, "-m", "cortex", "serve"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )
        request = {
            "jsonrpc": "2.0",
            "id": 0,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "0.0"},
            },
        }
        proc.stdin.write(json.dumps(request) + "\n")
        proc.stdin.flush()
        response_line = proc.stdout.readline()
        response = json.loads(response_line)
        self.assertEqual(response["id"], 0)
        self.assertEqual(response["result"]["protocolVersion"], "2025-11-25")
        self.assertIn("tools", response["result"]["capabilities"])
        self.assertEqual(response["result"]["serverInfo"]["name"], "cortex")
        proc.stdin.close()
        proc.wait(timeout=5)
```

**Why subprocess instead of in-process:** the stdio server is inherently an I/O boundary. Integration-testing the real binary via subprocess catches buffering bugs, encoding bugs, and argparse bugs that in-process tests miss entirely. These are exactly the bugs that killed MemPalace on Windows.

**Unit tests** (in-process, no subprocess) cover: storage read/write, grep search, rule matching logic, JSON schema validation. Fast, run on every save.

**Integration tests** (subprocess, the cortex binary) cover: initialize handshake, tools/list, tools/call roundtrip, hook stdin→stdout behavior, crash recovery, UTF-8 content with emoji and accented characters.

**CI matrix (GitHub Actions):**
```
os: [ubuntu-latest, macos-latest, windows-latest]
python-version: ["3.10", "3.11", "3.12", "3.13"]
```
The Windows row is non-negotiable — MemPalace's Windows bugs are the entire reason Cortex exists.

---

## Cross-Platform Path Handling

### Rule 1: `pathlib.Path` everywhere, `os.path` banned

Add a CI lint that fails on any import of `os.path` in `src/cortex/`. A simple regex grep in a pre-commit hook is enough.

### Rule 2: Always serialize paths with `.as_posix()` in JSON responses

```python
# BAD — produces "C:\\Users\\mohab\\.cortex\\memories\\foo.md" on Windows
json.dumps({"path": str(memory_path)})

# GOOD — produces "C:/Users/mohab/.cortex/memories/foo.md" on Windows
json.dumps({"path": memory_path.as_posix()})
```

**Why this matters for MCP:** Claude Code displays tool results to the user. Windows-style `\\` escapes in JSON render as `\\\\` which is ugly and sometimes interpreted as escape sequences by downstream consumers. Forward slashes render cleanly on every platform and Windows file APIs accept both.

### Rule 3: Base directory resolution

```python
from pathlib import Path
import os

def cortex_home() -> Path:
    override = os.environ.get("CORTEX_DIR")
    if override:
        return Path(override).expanduser().resolve()
    return Path.home() / ".cortex"
```

`Path.home()` is cross-platform-correct: returns `C:\Users\mohab` on Windows, `/home/mohab` on Linux, `/Users/mohab` on macOS. Never hardcode `/` or `~`.

### Rule 4: Atomic writes via `tempfile` + `shutil.move`

```python
import tempfile, shutil, os
from pathlib import Path

def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # tempfile in the same directory so rename is atomic on the same filesystem
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        delete=False,
        suffix=".tmp",
    ) as tmp:
        tmp.write(content)
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp_path = Path(tmp.name)
    # shutil.move handles Windows where os.rename fails if target exists
    shutil.move(str(tmp_path), str(path))
```

Prevents corrupted memory files if the process dies mid-write. Critical for a tool users will git-track — a corrupted file in version control is painful.

### Rule 5: Windows UTF-8 stdin/stdout

**First lines of `cortex.server` and `cortex.hooks.pretool`:**
```python
import sys, io
sys.stdin = io.TextIOWrapper(sys.stdin.buffer, encoding="utf-8", errors="replace", newline="\n")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", newline="\n", line_buffering=True)
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace", newline="\n", line_buffering=True)
```

On Windows, `sys.stdin` defaults to `cp1252` (or whatever the system codepage is) when stdin is a pipe. MCP messages with any non-ASCII character (emoji, accented names, CJK) will crash with `UnicodeDecodeError` without this reconfiguration. `errors="replace"` ensures a corrupt byte never crashes the server — it gets replaced with `U+FFFD`, logged to stderr, and the server stays alive.

PEP 528 changed Python's Windows console behavior for interactive consoles, but does NOT apply when stdin/stdout are pipes — which is exactly how MCP servers are invoked by Claude Code. The `io.TextIOWrapper` wrap is the only reliable fix.

---

## Alternatives Considered

| Recommended | Alternative | When to Use Alternative | Why Not for Cortex |
|---|---|---|---|
| **hatchling** | setuptools | Existing projects with `setup.py` | Both work fine for pure-Python, but hatchling has cleaner defaults, no legacy cruft, and is what `uv init` generates. For a greenfield project in 2026 there's no reason to choose setuptools. |
| **hatchling** | poetry | Apps with complex lockfile/dep needs | Poetry requires users to install poetry itself — we want `pip install` to Just Work. Poetry's `pyproject.toml` schema is also non-standard (pre-PEP 621). |
| **hatchling** | flit | Really tiny pure-python libs | Flit is fine but less featureful and less commonly recommended in 2026. Hatchling is the broader community default. |
| **`unittest`** | pytest | Projects where a better DSL matters more than zero-deps | pytest is nicer to write, but adds a test dependency. Since `unittest` ships with Python and we're disciplined about zero deps, unittest wins. Subclass `unittest.TestCase`, use `assertEqual` — it's verbose but fine. |
| **Sync stdio loop** | asyncio / anyio | Servers with concurrent long-running operations | MCP stdio is strictly serial request/response. The official `mcp` SDK uses anyio and has documented Windows 11 hangs (modelcontextprotocol/python-sdk#552). Sync is simpler AND more reliable here. |
| **`re` for search** | `sqlite3` FTS5 | 100k+ memory files | Grep is fine for 10k files per PROJECT.md. SQLite adds zero pip deps (stdlib) but adds an index to maintain, a schema to migrate, and breaks the "plain markdown files users can edit by hand" promise. Revisit only if grep ever gets slow. |
| **Plain Python hook module** | Shell script / batch file | Simple one-liners | Cross-platform nightmare. Shebangs don't work on Windows. Batch files don't work on macOS. `python -m cortex.hooks.pretool` works everywhere Python is installed, which is exactly our runtime requirement anyway. |
| **Negotiate `2025-11-25`** | Hardcode `2024-11-05` | Pinning to a specific old client | Claude Code as of 2026-02+ sends `2025-11-25`. Echo back whatever the client sends (if known) for forward/backward compatibility. Supporting multiple versions is trivial — it's just a set membership check. |

---

## What NOT to Use

| Avoid | Why | Use Instead |
|---|---|---|
| **`mcp` (official Anthropic Python SDK)** | Adds pydantic, anyio, httpx, typing-extensions, starlette (via fastmcp) as transitive deps. Known Windows 11 asyncio hangs (modelcontextprotocol/python-sdk#552). Overkill for 4-6 tools. Directly violates PROJECT.md constraint. | ~200 lines of hand-written stdlib code. The MCP protocol is 5 JSON message types, not a framework. |
| **`fastmcp`** | Decorator-based DX is pleasant but drags in `mcp`, `pydantic`, `httpx`. Same deal — violates zero-dep constraint. | Hand-rolled dispatch table `{"initialize": handle_init, "tools/list": handle_list, "tools/call": handle_call}`. |
| **`chromadb` / vector search libs** | 100MB+ install, native compilation, ONNX runtime, embedding model downloads. The entire reason MemPalace took 20 minutes to install. Explicitly out-of-scope per PROJECT.md. | Stdlib `re` + `str.__contains__` over markdown files. |
| **`numpy` / `scipy`** | Binary wheels that sometimes fail to install. We don't need numerical computation. | Plain Python lists and dicts. |
| **`pydantic`** | Huge install, C extensions, rust toolchain on some platforms. We just need `isinstance()` checks on a few JSON shapes. | Hand-rolled validation with `isinstance()` + raise `ValueError` with clear messages. `json.loads` returns dicts; check `"method" in msg` and `msg.get("id")`. |
| **`click` / `typer`** | Both violate zero-deps. `typer` pulls `pydantic` indirectly. | `argparse` — stdlib, does everything we need for 4-6 subcommands. |
| **`httpx` / `requests`** | We never make HTTP calls. The MCP transport is stdio. | N/A — delete any HTTP code. |
| **`rich` / `colorama`** | Pretty terminal output isn't worth a dep. | Plain `print` to stderr. The CLI is for debugging, not beauty. |
| **`tomli` / `tomlkit`** | Would let us parse TOML on 3.10. We don't read any TOML at runtime — `pyproject.toml` is a build-tool concern. | Nothing. Delete the config-loading TOML idea if it comes up. Use JSON for any user config file (`~/.cortex/config.json`). |
| **`watchdog`** | For file-change notifications. We don't need them — we re-read rules on each hook invocation. | Re-read on demand. Hooks fire at most a few times per second. |
| **`msgpack` / `orjson`** | Faster JSON. stdlib `json` is fast enough for line-oriented protocol messages. | `json` + `json.loads(ensure_ascii=False)`. |
| **`pytest`** | Adds a test-time dep. Tempting because the DX is nicer. | `unittest` + `python -m unittest discover`. |
| **`os.path`** | Legacy API, string-based, easy to get wrong cross-platform. | `pathlib.Path` everywhere. Ban `os.path` with a lint rule. |
| **`console.log` / `print(...)` to stdout in server code** | Every single byte on stdout must be valid JSON-RPC or it corrupts the protocol stream. The #1 bug in MCP server development. | `logging.getLogger(__name__).info(...)` with handler targeting `sys.stderr`, OR `print(..., file=sys.stderr)`. |
| **Content-Length framing (LSP-style)** | Claude Code uses newline-delimited JSON, NOT Content-Length headers. Confirmed in PROJECT.md and verified via MCP spec + raw stdio captures. | `for line in sys.stdin: msg = json.loads(line.strip())`. |
| **Blocking `input()` for stdin** | `input()` strips the newline but also prints the prompt to stdout — corrupts the protocol stream. | `sys.stdin.readline()` or `for line in sys.stdin:`. |
| **Async `asyncio.run()` stdio loop** | Works on Linux/macOS. Known to hang on Windows 11 (python-sdk#552). | Plain sync `for line in sys.stdin:` loop. |
| **Spawning a shell in the hook** | `subprocess.run("rm ...", shell=True)` in a security-enforcement hook is a comically bad idea. | Pure Python rule evaluation. Never shell out from the hook. |

---

## Stack Patterns by Variant

**If a user has Python 3.10 only:**
- Everything works. Use `Path.home() / ".cortex"` (no `Path.home().joinpath()` edge case), skip any 3.11-only syntax like exception groups.
- `match` statements from 3.10 are fine to use for dispatching on `method` in the stdio loop.

**If a user has Python 3.12+:**
- Nothing extra to do. The codebase will run unchanged. Optionally use `type` statement syntax for aliases, but it's not necessary.
- `tomllib` is available if we ever want to parse `pyproject.toml` for something, but we don't.

**If running on Windows:**
- The `io.TextIOWrapper` wrap is mandatory for stdin/stdout/stderr (see Cross-Platform section).
- Tell users who install via `pip` that `cortex.exe` will be on PATH via pip's script shim.
- For the `.mcp.json` / `claude mcp add` command, use `claude mcp add --transport stdio cortex -- cortex serve` — no `cmd /c` needed since Python scripts get proper `.exe` shims. (The `cmd /c` requirement only applies to `npx`-based servers.)

**If running on macOS with system Python:**
- Recommend `pipx install cortex-memory` or `pip install --user cortex-memory` to avoid `externally-managed-environment` errors on newer Pythons. Document in README.

**If the user wants git-tracked memories:**
- `~/.cortex/memories/` is a plain directory of markdown files — `git init` it and go. Cortex should not try to be a VCS itself, just be friendly to git (no binary files, deterministic ordering, line-based content).

---

## Version Compatibility Matrix

| Component | Version | Compatible With | Notes |
|---|---|---|---|
| Python | 3.10 | MCP stdio, all stdlib modules above | Minimum supported. EOL October 2027. |
| Python | 3.11 | Same + `tomllib`, exception groups | Recommended CI baseline. EOL October 2028. |
| Python | 3.12 | Same + `type` statement, faster `asyncio` (not used) | macOS default via Homebrew 2026. |
| Python | 3.13 | Same + free-threaded option, better error messages | Latest stable as of 2026-04. |
| hatchling | ≥ 1.18 | Python 3.10+, PEP 621 | Build-time only. |
| MCP protocol | `2025-11-25` | Claude Code 2.1.x, Claude Desktop current | Current spec version. |
| MCP protocol | `2024-11-05` | Claude Code legacy, older clients | Still accept and echo for compatibility. |
| Claude Code | ≥ 2.1.x | MCP stdio, newline-delimited JSON, PreToolUse hooks with `hookSpecificOutput` | Per PROJECT.md. |
| pip | ≥ 22 | `pyproject.toml` PEP 621 metadata | Shipped with Python 3.10 by default. |

**Known incompatibilities:**
- Python 3.9 is EOL. Do not support. PROJECT.md says 3.9+ but this is wrong for a 2026 project and should be updated.
- Python 3.8 and below are long EOL. Do not support.
- Claude Code versions older than 2.x use a different hook schema. Do not support — PROJECT.md targets 2.1.x+.
- On Windows, running through `python` launcher (`py -3`) vs direct `python.exe` — script shims created by pip work with both, no action needed.

---

## Installation (end user experience)

```bash
# The entire install is one line. No compilers, no native code, no model downloads.
pip install cortex-memory

# First-time setup: creates ~/.cortex/, registers the PreToolUse hook in ~/.claude/settings.json
cortex init

# Register as an MCP server with Claude Code
claude mcp add --transport stdio cortex -- cortex serve

# Verify
cortex status
claude mcp list
```

**Expected total time: under 30 seconds.** This is the entire value proposition vs MemPalace's 20-minute install.

---

## Sources

### HIGH confidence — Primary sources

- [MCP Specification — Lifecycle (2025-11-25)](https://modelcontextprotocol.io/specification/2025-11-25/basic/lifecycle) — initialize request/response schema, version negotiation rules, current protocol version verified
- [MCP Specification — Tools (2024-11-05)](https://modelcontextprotocol.io/specification/2024-11-05/server/tools) — tools/list, tools/call schemas, isError vs JSON-RPC error distinction
- [Claude Code Hooks Documentation](https://code.claude.com/docs/en/hooks) — PreToolUse input schema, hookSpecificOutput format, exit codes, settings.json config format
- [Claude Code MCP Documentation](https://code.claude.com/docs/en/mcp) — stdio transport details, `claude mcp add` CLI, Windows `cmd /c` note for npx-based servers
- [PEP 621 — Storing project metadata in pyproject.toml](https://peps.python.org/pep-0621/) — standard metadata fields used in pyproject.toml above
- [Python devguide — Status of Python versions](https://devguide.python.org/versions/) — Python 3.9 EOL date verified as October 2025

### MEDIUM confidence — Corroborating sources

- [Anaconda — Python 3.9 End-of-Life: What You Need to Know](https://www.anaconda.com/blog/python-3-9-end-of-life) — confirms 3.9 EOL October 2025
- [Red Hat Developer — Python 3.9 reaches end of life](https://developers.redhat.com/articles/2025/12/04/python-39-reaches-end-life-what-it-means-rhel-users) — December 2025 retrospective
- [Claude Code Issue #768 — protocolVersion validation](https://github.com/anthropics/claude-code/issues/768) — confirms Claude Code sends protocolVersion in initialize request
- [NLJUG — Understanding MCP Through Raw STDIO Communication](https://nljug.org/foojay/understanding-mcp-through-raw-stdio-communication/) — real wire captures of initialize/tools/list/tools/call, confirms line-delimited JSON format
- [Medium (Laurent Kubaski) — Understanding MCP Stdio transport](https://medium.com/@laurentkubaski/understanding-mcp-stdio-transport-protocol-ae3d5daf64db) — stdout-exclusive-for-protocol rule, flush requirement, stderr-for-logs
- [rcarmo/umcp — Micro MCP Server (stdlib only)](https://github.com/rcarmo/umcp) — existence proof that stdlib-only Python MCP servers work in practice
- [python-sdk Issue #552 — Windows 11 stdio hang](https://github.com/modelcontextprotocol/python-sdk/issues/552) — documented Windows asyncio issues; validates our sync-loop choice
- [PEP 528 — Change Windows console encoding to UTF-8](https://peps.python.org/pep-0528/) — explains why pipe-based stdin on Windows still needs manual reconfiguration
- [pathlib documentation — Path.as_posix()](https://docs.python.org/3/library/pathlib.html) — cross-platform path serialization method
- [Hatch — Why Hatch?](https://hatch.pypa.io/1.9/why/) — hatchling as PyPA-maintained build backend
- [Python Packaging Guide — Writing pyproject.toml](https://packaging.python.org/en/latest/guides/writing-pyproject-toml/) — canonical reference for the config above

### LOW confidence — Not relied on for decisions

- Various 2026 "MCP server tutorial" blog posts — mostly FastMCP-based, not directly applicable to stdlib-only approach, used only for cross-referencing wire format

---

## Confidence Summary

| Area | Confidence | Rationale |
|---|---|---|
| MCP protocol wire format (initialize, tools/list, tools/call) | **HIGH** | Verified against official spec pages for both 2024-11-05 and 2025-11-25 versions. Cross-checked with raw stdio captures from an independent source. |
| Claude Code protocolVersion (`2025-11-25`) | **HIGH** | Verified via Claude Code GitHub issue logs showing the actual negotiated version in 2026. Also listed in current spec index. |
| PreToolUse hook schema | **HIGH** | Fetched directly from the official Claude Code hooks documentation at code.claude.com. |
| Python 3.10+ minimum (overriding PROJECT.md 3.9) | **HIGH** | Python devguide, PSF, Red Hat, Anaconda all confirm 3.9 EOL October 2025. |
| Stdlib module selection | **HIGH** | Every module is documented in the CPython docs for 3.10+. Cross-platform behavior verified via pathlib docs and PEP 528. |
| hatchling as build backend | **HIGH** | Official PyPA docs, uv docs, and Hatch docs all corroborate. |
| Sync-over-async stdio loop | **MEDIUM** | Based on python-sdk#552 Windows hangs plus general reasoning about stdio serialization. We don't have a formal Anthropic statement, but the evidence is strong. |
| `as_posix()` path serialization rule | **MEDIUM** | Best-practice from pathlib docs. Not a formal MCP requirement, but avoids a class of Windows rendering bugs. |
| Exact `io.TextIOWrapper` invocation for Windows stdio | **MEDIUM** | Based on PEP 528 analysis and MCP filesystem #2098 (German umlaut) bug report. Tested pattern in my own Python code, but not verified against a Cortex implementation (doesn't exist yet). |

---

*Stack research for: Cortex zero-dependency AI memory system with MCP + PreToolUse hooks*
*Researched: 2026-04-11*
