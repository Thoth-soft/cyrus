"""JSON-RPC 2.0 helpers + stdio hardening for the Sekha MCP server.

Stdlib only. Imported by sekha.server (main loop) and sekha.tools (error
shaping). Kept deliberately small so the CI lint gate

    grep -rE "^\\s*print\\(" src/sekha/jsonrpc.py

trivially stays at zero hits forever. Every stray print anywhere in this
module (or any module it imports) corrupts the MCP protocol channel —
Pitfall #2 from the MemPalace autopsy.

Public surface:
- Error code constants: PARSE_ERROR, INVALID_REQUEST, METHOD_NOT_FOUND,
  INVALID_PARAMS, INTERNAL_ERROR
- ACCEPTED_PROTOCOL_VERSIONS frozenset (MCP negotiation table)
- JsonRpcError: carries a .code attribute for server-loop conversion
- parse(line) -> dict
- emit(stream, payload) -> None
- emit_error(stream, request_id, code, message) -> None
- harden_stdio() -> protected real-stdout TextIOWrapper

harden_stdio is the single most important function in this codebase for
MCP correctness. It implements the three fixes that keep MemPalace's
Windows + print-pollution + UTF-8 failures from happening again.
"""
from __future__ import annotations

import io
import json
import os
import sys
from typing import Any

# --------------------------------------------------------------------------
# JSON-RPC 2.0 reserved error codes (per spec, pre-defined range)
# --------------------------------------------------------------------------
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603

# --------------------------------------------------------------------------
# MCP protocol versions this server accepts. The server echoes back
# whatever the client sent during initialize; this set is the whitelist
# the negotiation check in Plan 05-02 consults. Do NOT force-downgrade to
# the oldest version — that breaks forward compatibility.
# --------------------------------------------------------------------------
ACCEPTED_PROTOCOL_VERSIONS = frozenset({
    "2025-11-25",
    "2025-03-26",
    "2024-11-05",
})


class JsonRpcError(ValueError):
    """Raised by parse() on malformed input.

    `.code` is one of the PARSE_ERROR / INVALID_REQUEST constants. The
    server loop catches this exception and converts it to an emit_error()
    response (request_id=null when the id could not be recovered).
    """

    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code


# --------------------------------------------------------------------------
# parse / emit
# --------------------------------------------------------------------------
def parse(line: str) -> dict[str, Any]:
    """Parse one newline-delimited JSON-RPC message.

    Strips leading/trailing whitespace (so callers can pass `stdin.readline()`
    output verbatim, CRLF tolerated). Raises JsonRpcError(PARSE_ERROR) on
    malformed JSON. Raises JsonRpcError(INVALID_REQUEST) on JSON-RPC batch
    arrays (unsupported in v1 per CONTEXT.md scope) and on non-object
    payloads (strings, numbers, null).
    """
    stripped = line.strip()
    try:
        obj = json.loads(stripped)
    except json.JSONDecodeError as e:
        raise JsonRpcError(PARSE_ERROR, f"Parse error: {e}") from e
    if isinstance(obj, list):
        raise JsonRpcError(
            INVALID_REQUEST, "JSON-RPC batch requests are not supported"
        )
    if not isinstance(obj, dict):
        raise JsonRpcError(
            INVALID_REQUEST, "JSON-RPC request must be an object"
        )
    return obj


def emit(stream: Any, payload: dict[str, Any]) -> None:
    """Write payload as one newline-delimited JSON line and flush.

    Uses separators=(',',':') so there are no stray spaces and no embedded
    newlines in the serialized form (json.dumps escapes \\n inside string
    values to the two-character sequence \\n — the only literal newline in
    the output is the framing delimiter appended here).

    The caller-supplied stream must be a text stream with write() + flush().
    Protocol integrity: flush() is REQUIRED because Claude Code's stdio
    client reads line-by-line with a blocking read; an unflushed buffer
    hangs the handshake forever.
    """
    line = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    stream.write(line + "\n")
    stream.flush()


def emit_error(
    stream: Any, request_id: Any, code: int, message: str
) -> None:
    """Emit a JSON-RPC error response.

    request_id may be None (serialized as JSON null) when the request was
    so malformed we could not recover an id. The server loop uses this
    shape for every error path: parse errors, unknown methods, handler
    exceptions.
    """
    emit(
        stream,
        {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": code, "message": message},
        },
    )


# --------------------------------------------------------------------------
# Stdio hardening — the MemPalace-killer function
# --------------------------------------------------------------------------
def harden_stdio() -> Any:
    """Swap sys.stdout -> sys.stderr and return a protected protocol handle.

    Called once at server boot, BEFORE any non-stdlib import in the caller.
    Returns a utf-8 TextIOWrapper over the real stdout's binary buffer;
    that handle is the one the server loop writes every JSON-RPC response
    through. The raw sys.stdout attribute is now aliased to sys.stderr so
    any stray print() from a later import (third-party library, rogue
    debug line) lands on stderr harmlessly instead of corrupting the
    protocol channel.

    Steps, in order:
      1. Capture the real stdout's underlying binary buffer.
      2. Swap sys.stdout -> sys.stderr (Pitfall 2 — stdout pollution).
      3. On Windows, put stdin + real-stdout file descriptors into
         O_BINARY mode so CRLF translation cannot mangle JSON payloads
         (Pitfall 3 — Windows text mode).
      4. Wrap the real buffer in a utf-8, errors='replace', newline='\\n',
         write_through=True TextIOWrapper so cp1252 default encoding on
         Windows Python 3.14+ cannot UnicodeEncodeError us (Pitfall 4).

    Not idempotent — calling twice swaps stderr back into stdout and
    returns a second wrapper over the original buffer. The server loop
    calls it exactly once in main().
    """
    # (1) Grab the binary buffer under the current stdout before we swap.
    #     Test harnesses install io.TextIOWrapper(io.BytesIO()) as stdout;
    #     that path still has a .buffer attribute so this works.
    real_stdout_buffer = sys.stdout.buffer

    # (2) Any bare print() from here on writes to stderr harmlessly.
    sys.stdout = sys.stderr

    # (3) Windows binary-mode for fd-backed streams. Real processes have
    #     int file descriptors; test harnesses with BytesIO-backed streams
    #     raise on .fileno(), so we swallow and continue — the test path
    #     doesn't need msvcrt.setmode anyway.
    if sys.platform == "win32":
        try:
            import msvcrt  # type: ignore[import-not-found]

            msvcrt.setmode(sys.stdin.fileno(), os.O_BINARY)
            msvcrt.setmode(real_stdout_buffer.fileno(), os.O_BINARY)
        except (OSError, AttributeError, ValueError):
            # Test harnesses or unusual stdio redirections lack real fds;
            # binary-mode is a real-process-only concern and a no-op here
            # is strictly safer than raising.
            pass
        # Also rewrap stdin in a UTF-8 text stream so the server's
        # `for line in sys.stdin:` read path decodes correctly. Guard for
        # the same test-harness-lacks-.buffer case.
        try:
            sys.stdin = io.TextIOWrapper(
                sys.stdin.buffer,
                encoding="utf-8",
                errors="replace",
                newline="\n",
            )
        except (AttributeError, ValueError):
            pass

    # (4) Return the protected handle. write_through=True so every write
    #     flushes to the underlying buffer immediately — Claude Code
    #     reads blocking and an unflushed buffer hangs the handshake.
    protected = io.TextIOWrapper(
        real_stdout_buffer,
        encoding="utf-8",
        errors="replace",
        newline="\n",
        write_through=True,
    )
    return protected
