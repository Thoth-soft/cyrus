"""Sekha MCP stdio server. Long-lived process invoked as `sekha serve`.

Transport: newline-delimited JSON-RPC 2.0. NO Content-Length framing
(Pitfall #1 — the framing choice that killed MemPalace with Claude Code).

Stdout is sacred. main() calls sekha.jsonrpc.harden_stdio() FIRST — before
any non-stdlib import in this module that could transitively print — so
any stray print() lands on stderr harmlessly. All protocol writes go
through the protected real-stdout handle returned by harden_stdio().

Lazy-import policy: heavyweight modules (sekha.tools, sekha.schemas,
sekha.search, sekha.storage) are imported inside helper functions
AFTER harden_stdio() has run. Keeps the window during which a stray
print from a third-party transitive import could corrupt the protocol
stream vanishingly small.

handle_request() is a pure function over dicts. It never raises — every
error path returns a well-formed JSON-RPC response (or None for
notifications). Tests call it directly; the stdio loop in main() wires
parse -> handle_request -> emit around it.
"""
# Requirement coverage:
#   MCP-01: `sekha serve` entrypoint (long-lived stdio JSON-RPC loop)
#   MCP-02: protocol-version negotiation across all three accepted versions
#   MCP-11: no print() in server.py (hard CI lint gate)
#   MCP-12: subprocess-driven handshake survival (verified in Task 2 tests)
from __future__ import annotations

import sys
from typing import Any

# Deliberately NO top-level imports from sekha.tools / .search / .schemas /
# .storage — see module docstring. handle_request() uses lazy imports so
# the only module cost paid on handshake-critical methods (initialize,
# ping, notifications) is sekha.jsonrpc + sekha.logutil.
from sekha.jsonrpc import (
    ACCEPTED_PROTOCOL_VERSIONS,
    INTERNAL_ERROR,
    INVALID_PARAMS,
    INVALID_REQUEST,
    JsonRpcError,
    METHOD_NOT_FOUND,
    emit,
    emit_error,
    harden_stdio,
    parse,
)
from sekha.logutil import get_logger

_log = get_logger(__name__)

# When the client requests a protocolVersion outside ACCEPTED_PROTOCOL_VERSIONS
# we echo back this preferred version rather than erroring — Claude Code
# tolerates an unknown-to-it version so long as the response is well-formed.
_PREFERRED_VERSION = "2025-03-26"


def _server_version() -> str:
    """Return the installed sekha package version, or '0.0.0' in dev.

    importlib.metadata.version() raises PackageNotFoundError in editable
    checkouts that haven't been `pip install -e .`'d yet; tests and dev
    loops tolerate that by falling back to 0.0.0 rather than crashing
    the handshake.
    """
    try:
        from importlib.metadata import PackageNotFoundError, version
        try:
            return version("sekha")
        except PackageNotFoundError:
            return "0.0.0"
    except ImportError:  # pragma: no cover — stdlib on 3.8+
        return "0.0.0"


def _initialize(params: dict[str, Any]) -> dict[str, Any]:
    """Build the initialize response body.

    protocolVersion is echoed back if the client sent one we accept; any
    other value (including missing) falls back to _PREFERRED_VERSION so
    the handshake never fails on a version mismatch.
    """
    client_version = params.get("protocolVersion", "")
    echo = (
        client_version
        if client_version in ACCEPTED_PROTOCOL_VERSIONS
        else _PREFERRED_VERSION
    )
    return {
        "protocolVersion": echo,
        "serverInfo": {"name": "sekha", "version": _server_version()},
        "capabilities": {"tools": {}},
    }


def _tools_list() -> dict[str, Any]:
    """Return the tools/list result. Lazy-imports sekha.schemas."""
    from sekha.schemas import TOOLS
    return {"tools": TOOLS}


def _tools_call(params: dict[str, Any]) -> dict[str, Any]:
    """Dispatch to a sekha_* handler.

    Unknown tool name -> raises JsonRpcError(METHOD_NOT_FOUND); the outer
    handle_request converts that to a JSON-RPC error response (spec-
    compliant: unknown-tool errors travel as JSON-RPC errors, not as MCP
    isError payloads — Claude Code's tool-picker needs the hard error to
    invalidate its cached tools list).

    TypeError from handler invocation (missing/extra kwargs) -> raised as
    INVALID_PARAMS so bad arguments round-trip cleanly rather than hiding
    inside an isError block.

    Every other handler exception -> caught and returned as the MCP-style
    {content:[{type:text,text:...}], isError: true} payload. Per spec,
    tools/call handler failures are NOT JSON-RPC errors; they are data.
    """
    import json as _json
    from sekha.tools import HANDLERS

    name = params.get("name")
    arguments = params.get("arguments") or {}
    if name not in HANDLERS:
        raise JsonRpcError(METHOD_NOT_FOUND, f"Unknown tool: {name}")
    try:
        result = HANDLERS[name](**arguments)
    except TypeError as e:
        raise JsonRpcError(
            INVALID_PARAMS, f"Invalid arguments for {name}: {e}"
        ) from e
    except Exception as e:  # noqa: BLE001 — surface to client as isError
        return {
            "content": [
                {"type": "text", "text": f"{type(e).__name__}: {e}"}
            ],
            "isError": True,
        }
    # Success: JSON-stringify the handler result into an MCP text block.
    # separators=(',',':') keeps the embedded JSON compact; ensure_ascii
    # left at default True so unicode content round-trips safely through
    # the outer single-line JSON-RPC frame.
    return {
        "content": [
            {
                "type": "text",
                "text": _json.dumps(result, separators=(",", ":")),
            }
        ]
    }


def handle_request(
    request: dict[str, Any],
) -> dict[str, Any] | None:
    """Dispatch one JSON-RPC request. Returns the response dict, or None
    for notifications (requests without an "id" field).

    Never raises: every error path returns a well-formed JSON-RPC error
    response (unless the request was a notification, in which case no
    response is emitted at all — per JSON-RPC 2.0 spec).

    Called directly from the server's stdin loop AND from unit tests in
    tests/test_server.py, which is why it operates on dicts rather than
    streams: keeps the method-dispatch logic testable without spinning
    up a subprocess.
    """
    method = request.get("method")
    request_id = request.get("id")
    is_notification = "id" not in request

    # Bad shape — missing method. Notifications swallow silently; requests
    # get a JSON-RPC INVALID_REQUEST back with the id we could recover.
    if not isinstance(method, str) or not method:
        if is_notification:
            return None
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {
                "code": INVALID_REQUEST,
                "message": "missing method",
            },
        }

    params = request.get("params") or {}

    try:
        if method == "initialize":
            result: Any = _initialize(params)
        elif method == "notifications/initialized":
            # Pure notification — log nothing, no response.
            return None
        elif method == "notifications/cancelled":
            _log.info(
                "sekha.server: notifications/cancelled requestId=%s",
                params.get("requestId"),
            )
            return None
        elif method == "tools/list":
            result = _tools_list()
        elif method == "tools/call":
            result = _tools_call(params)
        elif method == "ping":
            result = {}
        else:
            # Unknown notifications are swallowed (JSON-RPC 2.0 §4.1). Unknown
            # requests get METHOD_NOT_FOUND. Phase 5 explicitly doesn't
            # implement prompts/list or resources/list — v2 work.
            if is_notification:
                return None
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {
                    "code": METHOD_NOT_FOUND,
                    "message": f"Method not found: {method}",
                },
            }
    except JsonRpcError as e:
        if is_notification:
            return None
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": e.code, "message": str(e)},
        }
    except Exception as e:  # noqa: BLE001 — fail-loud but survive the loop
        _log.exception("sekha.server: handler crashed on %s", method)
        if is_notification:
            return None
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {
                "code": INTERNAL_ERROR,
                "message": f"{type(e).__name__}: {e}",
            },
        }

    if is_notification:
        # request_id is absent AND method completed without raising — still
        # a notification, still no response (covers user-defined notifs).
        return None
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def main() -> int:
    """Server entry point. Blocks on stdin until EOF or fatal error.

    FIRST action: harden_stdio(), which swaps sys.stdout -> sys.stderr so
    any stray print from downstream imports cannot corrupt the protocol
    stream, and returns a protected real-stdout handle that we write every
    JSON-RPC response through. Called BEFORE any sekha.tools / .schemas /
    .search / .storage import reaches this module (those are lazy-imported
    inside the _tools_* helpers).

    Returns 0 on normal shutdown (stdin EOF, Ctrl-C, BrokenPipe from the
    client closing its end of the pipe). The loop never propagates
    handler-level exceptions — handle_request converts those into JSON-RPC
    error responses so a misbehaving handler cannot wedge the server.
    """
    protected_stdout = harden_stdio()

    _log.info("sekha.server: started")
    try:
        for line in sys.stdin:
            if not line.strip():
                # Blank keepalive or CRLF from a Windows client: skip silently.
                continue
            try:
                request = parse(line)
            except JsonRpcError as e:
                # Parse error: id unrecoverable (null per JSON-RPC spec).
                emit_error(protected_stdout, None, e.code, str(e))
                continue
            response = handle_request(request)
            if response is not None:
                emit(protected_stdout, response)
    except KeyboardInterrupt:
        return 0
    except BrokenPipeError:
        # Claude Code closed stdin — normal shutdown path.
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
