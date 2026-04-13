"""Private helpers for sekha.hook: JSON I/O, fail-open logging, kill switch.

Lightweight by design — imported from inside `sekha.hook._run()` along with
other dependencies. Only stdlib + sekha.paths. No sekha.rules / storage / search
imports (those belong inside hook.main so the PreToolUse fast path can skip
them when the kill switch is tripped).

Invariants this module defends:
- Stdout is sacred. Every helper that writes to stdout emits a single JSON
  document and nothing else. Log lines, warnings, and tracebacks go to stderr
  or to the file log.
- Fail-open is non-negotiable. fail_open() NEVER re-raises and always returns
  0 so the caller can `return fail_open(exc, stderr)` and let Claude Code
  proceed with the tool call.
- Kill switch is source-of-truthed by the error log. record_error() parses
  ISO timestamps from the tail of hook-errors.log rather than keeping a
  separate counter file — one source of truth, crash-safe, zero extra I/O
  on the hot path.

Kill-switch constants (HOOK-07):
- _KILL_WINDOW_SECONDS = 600 (10 minutes)
- _KILL_THRESHOLD = 3 errors
- Reading only the last ~40 lines caps parse cost at O(1) regardless of log
  size; users with 10,000-line logs still pay the same ~microsecond tail read.
"""
# Requirement coverage (HOOK-*):
#   HOOK-02: read_event parses PreToolUse JSON from stdin
#   HOOK-03: emit_block emits the exact deny shape
#   HOOK-04: emit_warn emits the exact additionalContext shape
#   HOOK-05: emit_block writes reason to stderr AND returns exit code 2
#   HOOK-06: fail_open appends to ~/.sekha/hook-errors.log + stderr warning
#   HOOK-07: record_error + create_marker trip after 3 errors within 10 min
from __future__ import annotations

import json
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TextIO

from sekha.paths import sekha_home

__all__ = (
    "read_event",
    "emit_block",
    "emit_warn",
    "emit_allow",
    "fail_open",
    "record_error",
    "check_kill_switch",
    "create_marker",
    "clear_marker",
    "error_log_path",
    "marker_path",
)

_KILL_WINDOW_SECONDS = 600  # 10 minutes
_KILL_THRESHOLD = 3
_TAIL_LINES = 40  # ~10 error entries at 4 lines each — covers threshold + slack


def error_log_path() -> Path:
    """Path to ~/.sekha/hook-errors.log (honors SEKHA_HOME)."""
    return sekha_home() / "hook-errors.log"


def marker_path() -> Path:
    """Path to ~/.sekha/hook-disabled.marker (honors SEKHA_HOME)."""
    return sekha_home() / "hook-disabled.marker"


def read_event(stream: TextIO) -> dict[str, Any]:
    """Read PreToolUse JSON from a text stream and return it as a dict.

    Raises ValueError (or json.JSONDecodeError, a ValueError subclass) on
    empty or malformed input. The caller is expected to convert this into
    the fail-open path — never propagate to Claude Code.
    """
    data = stream.read()
    if not data:
        raise ValueError("empty stdin")
    return json.loads(data)


def emit_block(reason: str, stdout: TextIO, stderr: TextIO) -> int:
    """Emit the PreToolUse deny shape (stdout + stderr) and return exit 2.

    Belt-and-suspenders (HOOK-05): writes the decision JSON to stdout AND
    the reason to stderr AND returns exit code 2. Claude Code accepts either
    signal; emitting all three survives schema drift across versions.
    """
    payload = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }
    stdout.write(json.dumps(payload))
    stderr.write(reason + "\n")
    return 2


def emit_warn(message: str, stdout: TextIO) -> int:
    """Emit the PreToolUse additionalContext shape and return exit 0.

    Warn rules surface advice to the model without blocking the call. No
    stderr write — only Claude Code's model sees additionalContext.
    """
    payload = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": message,
        }
    }
    stdout.write(json.dumps(payload))
    return 0


def emit_allow(stdout: TextIO) -> int:  # noqa: ARG001 — signature symmetry with emit_block/warn
    """Allow-by-default: write nothing to stdout, return exit 0.

    Absence of a decision is how Claude Code interprets allow. Writing any
    payload (even an empty JSON object) risks schema churn rejecting it.
    """
    return 0


def fail_open(exc: BaseException, stderr: TextIO) -> int:
    """Log the exception to hook-errors.log and warn on stderr; always return 0.

    Creates the parent directory if missing so a brand-new install with no
    ~/.sekha/ yet still captures the error. The log entry format is:

        <ISO-8601 UTC> <ExceptionType>: <message>
        <full traceback>
        <blank line>

    The blank-line separator is what record_error() uses to split entries.
    """
    path = error_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with path.open("a", encoding="utf-8") as f:
        f.write(f"{ts} {type(exc).__name__}: {exc}\n")
        f.write(traceback.format_exc())
        f.write("\n")
    stderr.write(f"sekha hook error: {exc}\n")
    return 0


def record_error(exc: BaseException) -> bool:  # noqa: ARG001 — exc kept for future tagging
    """Return True if the last _KILL_THRESHOLD errors all fall within the window.

    The error log is the source of truth — no separate counter file. We
    read the tail (~40 lines), parse ISO timestamps at the start of each
    line, and count how many are within _KILL_WINDOW_SECONDS of now.

    Returning True signals the caller (hook.main) to create the kill-switch
    marker. The actual marker creation is kept separate so tests can assert
    the count logic without filesystem side effects.
    """
    path = error_log_path()
    if not path.exists():
        return False
    try:
        tail = path.read_text(encoding="utf-8").splitlines()[-_TAIL_LINES:]
    except OSError:
        return False
    now = datetime.now(timezone.utc)
    recent = 0
    for line in tail:
        parts = line.split(" ", 1)
        if len(parts) < 2:
            continue
        try:
            ts = datetime.fromisoformat(parts[0])
        except ValueError:
            # Traceback continuation lines start with "  File", etc. — skip.
            continue
        delta = (now - ts).total_seconds()
        if 0 <= delta <= _KILL_WINDOW_SECONDS:
            recent += 1
    return recent >= _KILL_THRESHOLD


def check_kill_switch() -> bool:
    """True iff the kill-switch marker file exists under SEKHA_HOME."""
    return marker_path().exists()


def create_marker() -> None:
    """Create the kill-switch marker (idempotent). Parent dir auto-created."""
    p = marker_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.touch(exist_ok=True)


def clear_marker() -> None:
    """Remove the kill-switch marker (idempotent; no-op if absent)."""
    p = marker_path()
    try:
        p.unlink()
    except FileNotFoundError:
        pass
