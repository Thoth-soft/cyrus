<!-- GSD:project-start source:PROJECT.md -->
## Project

**Sekha**

Sekha is a zero-dependency AI memory system for developers using Claude Code, Cursor, and other MCP-compatible AI tools. It gives your AI persistent memory across sessions — conversations, decisions, preferences — stored as plain markdown files you can read, grep, git-track, and edit by hand. The anti-MemPalace: same core value proposition, 1% of the complexity.

**Core Value:** **The AI actually follows rules you give it.** Rules enforcement is enforced at the system level via PreToolUse hooks, not relying on the AI to "remember." Memory + enforcement in one system. If this works and nothing else does, Sekha succeeds.

### Constraints

- **Tech stack**: Python stdlib only — no pip dependencies beyond what's already in the interpreter. Why: installation friction was MemPalace's biggest failure. Every dependency is a potential install failure.
- **Storage**: Plain markdown files on local disk. Why: grep-searchable, git-trackable, human-readable, editable with any tool. No database lock-in.
- **MCP protocol**: Newline-delimited JSON-RPC over stdio. Why: this is what Claude Code actually uses, confirmed by directly testing MemPalace's server.
- **Tool count**: 4-6 MCP tools max. Why: MemPalace had 19 — overwhelming. Fewer tools = easier to learn and harder to misuse.
- **Cross-platform**: Windows paths, macOS paths, Linux paths must all work. Why: the user encountered Windows-specific issues with MemPalace (UTF-8 encoding, text-mode stdin).
- **Rules enforcement**: Must work via PreToolUse hook, not just prompt injection. Why: prompt injection gets ignored; hook-level blocking cannot be bypassed by the AI.
- **License**: MIT. Why: maximum adoption, zero friction for contributors.
<!-- GSD:project-end -->

<!-- GSD:stack-start source:research/STACK.md -->
## Technology Stack

## TL;DR
- **Language:** Python **3.10+** (not 3.9 — EOL October 2025). Stdlib only.
- **Build backend:** `hatchling` via `pyproject.toml` (PEP 621, single file, no `setup.py`).
- **MCP protocol version:** Negotiate **`2025-11-25`** (current spec). Echo back whatever the client sends to remain forward-compatible. Claude Code currently sends `2025-11-25`.
- **Transport:** stdio, newline-delimited JSON (NDJSON), UTF-8, `stdout` = protocol only, `stderr` = logs.
- **Hook contract:** Read JSON from stdin, write `hookSpecificOutput` JSON to stdout on exit 0, or write human error to stderr and exit 2 to block.
- **DO NOT USE:** `mcp` (official SDK), `fastmcp`, `chromadb`, `numpy`, `tomli`, `pydantic`, any external dep — they all violate the zero-dependency constraint and were the root cause of MemPalace's failure.
## Recommended Stack
### Core Technologies
| Technology | Version | Purpose | Why Recommended |
|---|---|---|---|
| **Python interpreter** | **3.10+** (target 3.11 for testing) | Runtime | 3.9 reached EOL Oct 2025 — unsafe for new projects. 3.10 is the lowest version that is still receiving security patches as of 2026-04. 3.10 adds `match` statements, better error messages, and `X \| Y` union syntax that we will use. If we go to 3.11 we get `tomllib` for free but we don't need it. |
| **JSON-RPC 2.0 over stdio** | MCP `2025-11-25` (primary), also accept `2024-11-05` | Wire protocol with Claude Code | Confirmed: Claude Code sends `"protocolVersion": "2025-11-25"` in the `initialize` request as of 2026-02+. MCP spec requires the server to echo the same version back if supported, or offer its own. Line-delimited JSON — NOT Content-Length framed (LSP-style). One JSON object per line on stdin/stdout, no length prefix. |
| **`pyproject.toml` + `hatchling`** | hatchling 1.x | Build backend | PEP 621 metadata, single source of truth, no `setup.py`. Hatchling is PyPA-maintained (same umbrella as setuptools) and is the default uv/modern recommendation. Zero runtime dependencies — `hatchling` is only required at build time, not install time. End users install with `pip install sekha-memory` and pull zero transitive deps. |
| **Plain markdown files on disk** | — | Storage | Grep-searchable, git-trackable, human-readable, zero lock-in. Per PROJECT.md constraint. |
### Python Standard Library Modules Used
| Module | Purpose in Sekha | Why this over alternatives |
|---|---|---|
| **`json`** | Parse/serialize every MCP and hook message | Only JSON library we need. `json.loads()` / `json.dumps(..., ensure_ascii=False)` for UTF-8 friendliness. |
| **`sys`** | `sys.stdin`, `sys.stdout`, `sys.stderr`, `sys.argv`, `sys.exit()` | The stdio loop reads `sys.stdin` line-by-line and writes to `sys.stdout`. All logs go to `sys.stderr` — **stdout is reserved for protocol messages only**. |
| **`pathlib`** | All filesystem path handling | Use `pathlib.Path` everywhere, never `os.path`. Use `Path.as_posix()` when serializing paths into JSON responses — Windows backslashes in JSON are legal but confuse cross-platform clients and grep. Use `Path.home()` for `~/.sekha/`. |
| **`os`** | `os.environ` only (for `CORTEX_DIR` override), `os.fsync()` for durable writes | `os.path` is banned in Sekha code — always use `pathlib`. |
| **`re`** | Grep engine (regex-based search across markdown files) | Stdlib `re` is fast enough for 10k files. For fixed-string search, use `str.__contains__` instead for speed. `re.IGNORECASE` flag for case-insensitive search. |
| **`subprocess`** | None in MCP server. Used in hook script only if shelling out (we won't). | Sekha hooks are pure Python scripts invoked by Claude Code — we do not spawn subprocesses ourselves. |
| **`argparse`** | `sekha init`, `sekha serve`, `sekha add-rule` CLI | Stdlib CLI parser. Enough for our 4-6 subcommands. No `click` or `typer`. |
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
- `asyncio` — the MCP stdio loop is inherently single-threaded request/response. Sync code with a blocking `for line in sys.stdin:` loop is simpler, shorter, and avoids the Windows asyncio issues that plague the official python-sdk (see modelcontextprotocol/python-sdk#552 — Windows 11 hangs indefinitely with asyncio-based stdio).
- `tomllib` — we have no TOML to parse at runtime. `pyproject.toml` is only read by the build tool, not by Sekha itself.
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
## MCP Protocol Specifics (HIGH confidence — verified against spec)
### 1. The stdio loop (pseudocode)
# Windows UTF-8 fix — MUST be before any I/O
### 2. Initialize request/response
- Echo the exact `protocolVersion` the client sent, if it's in our supported set `{"2025-11-25", "2025-03-26", "2024-11-05"}`. Otherwise respond with `"2025-11-25"` and let the client decide to disconnect.
- `capabilities.tools` is present (we have tools); set `listChanged: false` in v1 (we don't send dynamic updates).
- Do NOT advertise `resources`, `prompts`, `logging`, `sampling`, `tasks`, `elicitation`, or `experimental`. Tools only.
- `serverInfo.version` is populated from `importlib.metadata.version("sekha-memory")`.
### 3. Initialized notification (client → server, no response)
### 4. tools/list
### 5. tools/call
## PreToolUse Hook Specifics (HIGH confidence — verified against docs.claude.com/hooks)
### 1. Configuration (Sekha writes to `~/.claude/settings.json` during `sekha init`)
- `matcher: "*"` to match every tool call — Sekha rules may apply to any tool, not just Bash.
- `type: "command"` — the only type we use.
- `command: "python -m sekha.hooks.pretool"` — invokes the hook as a Python module, so it works regardless of install path. On Windows this works as-is because Python is on PATH. (No `cmd /c` needed for `python` specifically — that's only for `npx`.)
### 2. Hook input (Claude Code → hook stdin, single JSON line)
### 3. Hook output (hook stdout → Claude Code)
### 4. Decision field values
| `permissionDecision` | Meaning |
|---|---|
| `"allow"` | Skip any permission prompts — auto-allow |
| `"deny"` | Block the tool call |
| `"ask"` | Prompt the user for confirmation |
| `"defer"` | Fall through to default handling |
### 5. Exit codes
| Code | Behavior |
|---|---|
| `0` | Parse stdout as JSON `hookSpecificOutput` for decision (or allow if no JSON) |
| `2` | Blocking error — stderr text shown to Claude, tool blocked |
| Any other | Non-blocking error — stderr first line shown in transcript, tool proceeds |
## Packaging (`pyproject.toml`)
### Minimum viable `pyproject.toml`
# CRITICAL: NO dependencies key at all. Zero pip deps.
- **No `[project.dependencies]` key.** Hatchling defaults to empty. Users run `pip install sekha-memory` and get zero transitive installs — MemPalace's 60+ deps nightmare is structurally impossible.
- **`requires-python = ">=3.10"`** — overrides PROJECT.md's 3.9+ constraint because 3.9 is EOL and shipping a new 2026 project on an EOL runtime is irresponsible. Still widely available: macOS Homebrew ships 3.12, Ubuntu 22.04 LTS ships 3.10, Windows Store ships 3.12, `pyenv` covers anyone stuck behind.
- **`packages = ["src/sekha"]`** — use the `src/` layout. Prevents accidentally importing from the working directory instead of the installed package during testing (a classic packaging footgun).
- **`[project.scripts] sekha = "sekha.cli:main"`** — creates a `sekha` executable on PATH. Pip handles cross-platform shim creation (including `sekha.exe` on Windows).
### Including the hook script as package data
### Directory layout
## Testing Strategy (stdlib only)
### Test runner: `unittest` + `python -m unittest discover`
# tests/test_server.py
## Cross-Platform Path Handling
### Rule 1: `pathlib.Path` everywhere, `os.path` banned
### Rule 2: Always serialize paths with `.as_posix()` in JSON responses
# BAD — produces "C:\\Users\\mohab\\.cortex\\memories\\foo.md" on Windows
# GOOD — produces "C:/Users/mohab/.sekha/memories/foo.md" on Windows
### Rule 3: Base directory resolution
### Rule 4: Atomic writes via `tempfile` + `shutil.move`
### Rule 5: Windows UTF-8 stdin/stdout
## Alternatives Considered
| Recommended | Alternative | When to Use Alternative | Why Not for Sekha |
|---|---|---|---|
| **hatchling** | setuptools | Existing projects with `setup.py` | Both work fine for pure-Python, but hatchling has cleaner defaults, no legacy cruft, and is what `uv init` generates. For a greenfield project in 2026 there's no reason to choose setuptools. |
| **hatchling** | poetry | Apps with complex lockfile/dep needs | Poetry requires users to install poetry itself — we want `pip install` to Just Work. Poetry's `pyproject.toml` schema is also non-standard (pre-PEP 621). |
| **hatchling** | flit | Really tiny pure-python libs | Flit is fine but less featureful and less commonly recommended in 2026. Hatchling is the broader community default. |
| **`unittest`** | pytest | Projects where a better DSL matters more than zero-deps | pytest is nicer to write, but adds a test dependency. Since `unittest` ships with Python and we're disciplined about zero deps, unittest wins. Subclass `unittest.TestCase`, use `assertEqual` — it's verbose but fine. |
| **Sync stdio loop** | asyncio / anyio | Servers with concurrent long-running operations | MCP stdio is strictly serial request/response. The official `mcp` SDK uses anyio and has documented Windows 11 hangs (modelcontextprotocol/python-sdk#552). Sync is simpler AND more reliable here. |
| **`re` for search** | `sqlite3` FTS5 | 100k+ memory files | Grep is fine for 10k files per PROJECT.md. SQLite adds zero pip deps (stdlib) but adds an index to maintain, a schema to migrate, and breaks the "plain markdown files users can edit by hand" promise. Revisit only if grep ever gets slow. |
| **Plain Python hook module** | Shell script / batch file | Simple one-liners | Cross-platform nightmare. Shebangs don't work on Windows. Batch files don't work on macOS. `python -m sekha.hooks.pretool` works everywhere Python is installed, which is exactly our runtime requirement anyway. |
| **Negotiate `2025-11-25`** | Hardcode `2024-11-05` | Pinning to a specific old client | Claude Code as of 2026-02+ sends `2025-11-25`. Echo back whatever the client sends (if known) for forward/backward compatibility. Supporting multiple versions is trivial — it's just a set membership check. |
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
| **`tomli` / `tomlkit`** | Would let us parse TOML on 3.10. We don't read any TOML at runtime — `pyproject.toml` is a build-tool concern. | Nothing. Delete the config-loading TOML idea if it comes up. Use JSON for any user config file (`~/.sekha/config.json`). |
| **`watchdog`** | For file-change notifications. We don't need them — we re-read rules on each hook invocation. | Re-read on demand. Hooks fire at most a few times per second. |
| **`msgpack` / `orjson`** | Faster JSON. stdlib `json` is fast enough for line-oriented protocol messages. | `json` + `json.loads(ensure_ascii=False)`. |
| **`pytest`** | Adds a test-time dep. Tempting because the DX is nicer. | `unittest` + `python -m unittest discover`. |
| **`os.path`** | Legacy API, string-based, easy to get wrong cross-platform. | `pathlib.Path` everywhere. Ban `os.path` with a lint rule. |
| **`console.log` / `print(...)` to stdout in server code** | Every single byte on stdout must be valid JSON-RPC or it corrupts the protocol stream. The #1 bug in MCP server development. | `logging.getLogger(__name__).info(...)` with handler targeting `sys.stderr`, OR `print(..., file=sys.stderr)`. |
| **Content-Length framing (LSP-style)** | Claude Code uses newline-delimited JSON, NOT Content-Length headers. Confirmed in PROJECT.md and verified via MCP spec + raw stdio captures. | `for line in sys.stdin: msg = json.loads(line.strip())`. |
| **Blocking `input()` for stdin** | `input()` strips the newline but also prints the prompt to stdout — corrupts the protocol stream. | `sys.stdin.readline()` or `for line in sys.stdin:`. |
| **Async `asyncio.run()` stdio loop** | Works on Linux/macOS. Known to hang on Windows 11 (python-sdk#552). | Plain sync `for line in sys.stdin:` loop. |
| **Spawning a shell in the hook** | `subprocess.run("rm ...", shell=True)` in a security-enforcement hook is a comically bad idea. | Pure Python rule evaluation. Never shell out from the hook. |
## Stack Patterns by Variant
- Everything works. Use `Path.home() / ".sekha"` (no `Path.home().joinpath()` edge case), skip any 3.11-only syntax like exception groups.
- `match` statements from 3.10 are fine to use for dispatching on `method` in the stdio loop.
- Nothing extra to do. The codebase will run unchanged. Optionally use `type` statement syntax for aliases, but it's not necessary.
- `tomllib` is available if we ever want to parse `pyproject.toml` for something, but we don't.
- The `io.TextIOWrapper` wrap is mandatory for stdin/stdout/stderr (see Cross-Platform section).
- Tell users who install via `pip` that `sekha.exe` will be on PATH via pip's script shim.
- For the `.mcp.json` / `claude mcp add` command, use `claude mcp add --transport stdio sekha -- sekha serve` — no `cmd /c` needed since Python scripts get proper `.exe` shims. (The `cmd /c` requirement only applies to `npx`-based servers.)
- Recommend `pipx install cortex-memory` or `pip install --user cortex-memory` to avoid `externally-managed-environment` errors on newer Pythons. Document in README.
- `~/.sekha/memories/` is a plain directory of markdown files — `git init` it and go. Sekha should not try to be a VCS itself, just be friendly to git (no binary files, deterministic ordering, line-based content).
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
- Python 3.9 is EOL. Do not support. PROJECT.md says 3.9+ but this is wrong for a 2026 project and should be updated.
- Python 3.8 and below are long EOL. Do not support.
- Claude Code versions older than 2.x use a different hook schema. Do not support — PROJECT.md targets 2.1.x+.
- On Windows, running through `python` launcher (`py -3`) vs direct `python.exe` — script shims created by pip work with both, no action needed.
## Installation (end user experience)
# The entire install is one line. No compilers, no native code, no model downloads.
# First-time setup: creates ~/.sekha/, registers the PreToolUse hook in ~/.claude/settings.json
# Register as an MCP server with Claude Code
# Verify
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
| Exact `io.TextIOWrapper` invocation for Windows stdio | **MEDIUM** | Based on PEP 528 analysis and MCP filesystem #2098 (German umlaut) bug report. Tested pattern in my own Python code, but not verified against a Sekha implementation (doesn't exist yet). |
<!-- GSD:stack-end -->

<!-- GSD:conventions-start source:CONVENTIONS.md -->
## Conventions

Conventions not yet established. Will populate as patterns emerge during development.
<!-- GSD:conventions-end -->

<!-- GSD:architecture-start source:ARCHITECTURE.md -->
## Architecture

Architecture not yet mapped. Follow existing patterns found in the codebase.
<!-- GSD:architecture-end -->

<!-- GSD:workflow-start source:GSD defaults -->
## GSD Workflow Enforcement

Before using Edit, Write, or other file-changing tools, start work through a GSD command so planning artifacts and execution context stay in sync.

Use these entry points:
- `/gsd:quick` for small fixes, doc updates, and ad-hoc tasks
- `/gsd:debug` for investigation and bug fixing
- `/gsd:execute-phase` for planned phase work

Do not make direct repo edits outside a GSD workflow unless the user explicitly asks to bypass it.
<!-- GSD:workflow-end -->



<!-- GSD:profile-start -->
## Developer Profile

> Profile not yet configured. Run `/gsd:profile-user` to generate your developer profile.
> This section is managed by `generate-claude-profile` -- do not edit manually.
<!-- GSD:profile-end -->
