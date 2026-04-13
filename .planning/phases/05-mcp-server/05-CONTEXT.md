# Phase 5: MCP Server - Context

**Gathered:** 2026-04-13
**Status:** Ready for planning
**Mode:** Auto-generated (infrastructure phase)

<domain>
## Phase Boundary

Build the long-lived MCP server `sekha.server` over newline-delimited JSON-RPC 2.0. Exposes exactly 6 `sekha_*`-prefixed tools: `save`, `search`, `list`, `delete`, `status`, `add_rule`. Implements `initialize`, `notifications/initialized`, `tools/list`, `tools/call`, `ping`, `notifications/cancelled`.

With the hook already proven in Phase 4, this phase focuses on stdio framing correctness, Windows hardening, and the JSON-RPC handshake — the boring-but-deadly details that killed MemPalace.

</domain>

<decisions>
## Implementation Decisions

### Protocol

- **Transport:** Newline-delimited JSON-RPC 2.0 over stdio. NOT Content-Length framed. Confirmed from MemPalace debugging: Claude Code uses line-delimited, not LSP-style framing.
- **Protocol versions accepted:** `{"2025-11-25", "2025-03-26", "2024-11-05"}` — echo back whatever client sends in initialize response
- **Server info:** `{"name": "sekha", "version": "<package version>"}`
- **Capabilities:** `{"tools": {}}`

### The 6 Tools (all prefixed `sekha_`)

```python
TOOLS = {
    "sekha_save": {
        "description": "Save a memory. category must be one of: sessions, decisions, preferences, projects, rules.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "category": {"type": "string", "enum": ["sessions", "decisions", "preferences", "projects", "rules"]},
                "content": {"type": "string"},
                "tags": {"type": "array", "items": {"type": "string"}},
                "source": {"type": "string"}
            },
            "required": ["category", "content"]
        }
    },
    "sekha_search": {
        "description": "Full-text search over saved memories, ranked by term frequency × recency × filename match.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "category": {"type": "string"},
                "limit": {"type": "integer", "default": 10},
                "tags": {"type": "array", "items": {"type": "string"}}
            },
            "required": ["query"]
        }
    },
    "sekha_list": {
        "description": "List memories in a category with metadata only (no body content).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "category": {"type": "string"},
                "limit": {"type": "integer", "default": 20},
                "since": {"type": "string", "description": "ISO-8601 timestamp"}
            }
        }
    },
    "sekha_delete": {
        "description": "Delete a memory by path. Returns success/failure.",
        "inputSchema": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"]
        }
    },
    "sekha_status": {
        "description": "Return total memory count, category breakdown, rules count, recent activity, hook error count.",
        "inputSchema": {"type": "object", "properties": {}}
    },
    "sekha_add_rule": {
        "description": "Create a new rule file. Validates regex compiles before writing.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "severity": {"type": "string", "enum": ["block", "warn"]},
                "matches": {"type": "array", "items": {"type": "string"}},
                "pattern": {"type": "string"},
                "message": {"type": "string"},
                "priority": {"type": "integer", "default": 50},
                "triggers": {"type": "array", "items": {"type": "string"}, "default": ["PreToolUse"]}
            },
            "required": ["name", "severity", "matches", "pattern", "message"]
        }
    }
}
```

### Tool Handlers

Each tool is a pure function in `sekha.tools`:

```python
def sekha_save(category: str, content: str, tags: list[str] = None, source: str = None) -> dict:
    """Delegates to sekha.storage.save_memory. Returns {"path": str, "id": str}."""

def sekha_search(query: str, category: str = None, limit: int = 10, tags: list[str] = None) -> dict:
    """Delegates to sekha.search.search. Returns {"results": [{"path": ..., "score": ..., "snippet": ..., "metadata": ...}]}."""

# ... etc
```

No logic in server.py beyond dispatch — each tool wraps library calls.

### Server Loop

```python
def main():
    _harden_stdio()   # swap stdout→stderr for imports, force binary+UTF-8 on Windows
    
    for line in sys.stdin:   # blocking stdio read line-by-line
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
            response = handle_request(request)
            if response is not None:
                sys.stdout.write(json.dumps(response) + "\n")
                sys.stdout.flush()
        except json.JSONDecodeError as e:
            _emit_error(-32700, f"Parse error: {e}")
        except Exception as e:
            _emit_error(-32603, f"Internal error: {e}")
```

### Stdio Hardening (CRITICAL)

This is where MemPalace died. Must do at server startup:

```python
def _harden_stdio():
    # 1. Swap stdout → stderr for any stray imports that print
    _real_stdout = sys.stdout
    sys.stdout = sys.stderr
    
    # 2. Force binary-safe UTF-8 on Windows
    if sys.platform == "win32":
        import msvcrt
        msvcrt.setmode(sys.stdin.fileno(), os.O_BINARY)
        msvcrt.setmode(_real_stdout.fileno(), os.O_BINARY)
    
    # 3. Wrap both in UTF-8 TextIOWrappers (handles Python 3.14 cp1252 default on Windows)
    sys.stdin = io.TextIOWrapper(sys.stdin.buffer, encoding="utf-8", errors="replace", newline="\n")
    sys.stdout_real = io.TextIOWrapper(_real_stdout.buffer, encoding="utf-8", errors="replace", newline="\n", write_through=True)
    
    # 4. Return the protected real stdout for protocol output
    return sys.stdout_real
```

Tool handlers write to `sys.stdout_real` (the protected handle); any `print()` elsewhere goes to stderr harmlessly.

### Protocol Methods

- `initialize`: return server info + capabilities, echo protocol version
- `notifications/initialized`: no response (it's a notification)
- `tools/list`: return the 6 tools
- `tools/call`: dispatch to handler, wrap result in `{"content": [{"type": "text", "text": json.dumps(result)}]}`
- `ping`: return `{}` (MCP spec)
- `notifications/cancelled`: no response, log to stderr

### Hard CI Lint Gate

```bash
grep -rE "^\s*print\(" src/sekha/server.py src/sekha/tools.py src/sekha/jsonrpc.py src/sekha/schemas.py
```
MUST return zero results. Any stray print corrupts the protocol.

### Module Layout

```
src/sekha/
    server.py       # main() + server loop
    tools.py        # 6 tool handler functions
    jsonrpc.py      # parse/emit helpers, error codes, stdio harden
    schemas.py      # hand-written JSON schemas for each tool
tests/
    test_server.py     # full handshake + tool dispatch tests
    test_tools.py      # each tool handler unit-tested
    test_jsonrpc.py    # parse/emit + stdio harden tests
```

### Testing Strategy

- Unit test each tool handler in isolation
- Integration test: scripted JSON-RPC sequence piped into subprocess running `sekha serve` (NOT bench — actual server spin-up)
- Test protocol version negotiation (all 3 versions)
- Test error responses (parse error, unknown tool, invalid params)
- Test stdio hardening: deliberately `print("OOPS")` from inside a tool handler, assert protocol stream untouched
- Test `notifications/cancelled` mid-call

### CLI Entry Point

Add to `sekha.cli` in Phase 5:
```python
# alongside `hook run` and `hook bench`
sub.add_parser("serve", help="Run MCP server (invoked by Claude Code)")
# router: if args.command == "serve": from sekha.server import main; return main()
```

Claude Code invokes as: `sekha serve` (added to `.claude.json` via `claude mcp add sekha -- sekha serve`).

### Claude's Discretion

- Whether to implement `prompts/list` and `resources/list` methods (return empty lists, don't error out on unknown methods the client might send)
- Exact format for tool error responses (suggest: return `{"content": [...], "isError": true}` instead of JSON-RPC error)
- Whether to validate tool inputs against schemas in Python (suggest: minimal validation, let handlers raise, catch and return error)

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `sekha.storage.save_memory`, `sekha.storage.parse_frontmatter`, `sekha.storage.CATEGORIES` — for save/list/delete
- `sekha.search.search` — for sekha_search tool
- `sekha.rules.load_rules`, `sekha.rules.evaluate` — not directly used by tools but indirectly via sekha_add_rule
- `sekha.paths.sekha_home()` — home dir
- `sekha.logutil.get_logger()` — stderr logging
- `sekha.cli` — existing argparse router, add `serve` subcommand

### Established Patterns
- Stdlib only
- pathlib.Path
- unittest
- TDD (RED→GREEN commits)
- Lazy imports where protocol integrity matters

### Integration Points
- Phase 6 `sekha init` registers the server via `claude mcp add sekha -- sekha serve`
- Hook (Phase 4) runs in a separate process — no shared state with server
- Both hook and server read from `~/.sekha/` — filesystem is the message bus

</code_context>

<specifics>
## Specific Ideas

- Integration tests for the server MUST spawn the actual `sekha serve` subprocess. Protocol bugs only surface when stdout buffering is real.
- Test `initialize` → `tools/list` → `tools/call sekha_status` → graceful shutdown as the canonical happy path
- Test `initialize` with unknown protocol version — should echo back something reasonable
- Test a tool call that throws — should return error in response, not crash server
- Write one test that pipes a `print("pollution")` in via stdin and proves the server survives

</specifics>

<deferred>
## Deferred Ideas

- Streaming tool results (for long-running searches) — v2
- `resources/` endpoints for exposing memories as resources — v2
- `prompts/` endpoints — v2
- Observability / metrics — v2
- Rate limiting — v2

</deferred>

---

*Phase: 05-mcp-server*
*Context gathered: 2026-04-13 via infrastructure auto-detection*
