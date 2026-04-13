"""CLI utilities shared across init / doctor / add-rule / list-rules.

Stdlib only, ASCII-only output. Everything here must be cp1252-safe so it
survives Windows cmd.exe's default code page without UnicodeEncodeError.

Public surface:
- format_table(headers, rows) -> str
    Render an ASCII table with `|` column separators and `+---+` divider
    rows. No Unicode box-drawing. Empty rows render just the header block.

- merge_claude_settings(existing, cyrus_command="cyrus hook run")
        -> (merged_dict, changed_bool)
    Idempotent merge of Cyrus's PreToolUse hook into ~/.claude/settings.json.
    Scans every nested `hooks[*].command` for `cyrus_command`; if already
    present anywhere under hooks.PreToolUse[*].hooks[*], returns the input
    unchanged with changed=False. Otherwise appends a fresh matcher="*"
    block and returns the deep-copied result. Never mutates the input.

- backup_file(path) -> Path | None
    Copy `path` to a sibling `<name>.bak.<YYYYMMDD-HHMMSS>` if it exists.
    Returns the backup path (None if the source did not exist).

- write_json_atomic(path, data) -> None
    json.dumps with indent=2 + sort_keys=True (stable diffs), wrapped in
    cyrus.storage.atomic_write so partial writes can never corrupt a user's
    settings.json.

- say(message, stream=sys.stderr) -> None
    Print a status line to stderr (stdout is reserved for the single
    user-facing directive in `cyrus init`). Appends newline + flushes.

Design notes:
- `merge_claude_settings` walks arbitrary nested shapes because real
  user settings.json files contain a zoo of matcher/hook combinations --
  we do not assume our own output shape on input.
- backup_file uses a plain datetime.now() (local time) for the timestamp
  suffix. Collision within one-second of re-invocation is vanishingly
  unlikely for an interactive init command and the filename is just a
  disposable backup reference.
- format_table reserves a minimum column width matching the header text
  so an empty-rows table still renders a usable header line.
"""
from __future__ import annotations

import copy
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, TextIO

from cyrus.storage import atomic_write

__all__ = (
    "format_table",
    "merge_claude_settings",
    "backup_file",
    "write_json_atomic",
    "say",
)


# ----------------------------------------------------------------------
# ASCII table formatter
# ----------------------------------------------------------------------
def format_table(headers: list[str], rows: list[list[str]]) -> str:
    """Render a pure-ASCII table.

    Columns are auto-sized to the max of header / cell width. Dividers use
    `+---+---+` and row separators use `| a | b |`. Cell text is cast to
    str and any non-ASCII is replaced with `?` so the output encodes as
    pure ASCII regardless of input.
    """
    cols = len(headers)
    # Normalize every row to `cols` cells; str-coerce + ASCII-squash.
    norm_rows: list[list[str]] = []
    for row in rows:
        cells = [_ascii_squash(str(c)) for c in row]
        if len(cells) < cols:
            cells = cells + [""] * (cols - len(cells))
        elif len(cells) > cols:
            cells = cells[:cols]
        norm_rows.append(cells)

    ascii_headers = [_ascii_squash(h) for h in headers]
    widths = [len(h) for h in ascii_headers]
    for row in norm_rows:
        for i, cell in enumerate(row):
            if len(cell) > widths[i]:
                widths[i] = len(cell)

    def _divider() -> str:
        return "+" + "+".join("-" * (w + 2) for w in widths) + "+"

    def _row(cells: list[str]) -> str:
        padded = [cells[i].ljust(widths[i]) for i in range(cols)]
        return "| " + " | ".join(padded) + " |"

    lines: list[str] = [_divider(), _row(ascii_headers), _divider()]
    for row in norm_rows:
        lines.append(_row(row))
    if norm_rows:
        lines.append(_divider())
    return "\n".join(lines)


def _ascii_squash(s: str) -> str:
    """Replace any non-printable-ASCII char with `?` so output is cp1252-safe."""
    out_chars: list[str] = []
    for ch in s:
        code = ord(ch)
        if 0x20 <= code <= 0x7E:
            out_chars.append(ch)
        else:
            out_chars.append("?")
    return "".join(out_chars)


# ----------------------------------------------------------------------
# settings.json merge
# ----------------------------------------------------------------------
def merge_claude_settings(
    existing: dict[str, Any],
    cyrus_command: str = "cyrus hook run",
) -> tuple[dict[str, Any], bool]:
    """Idempotently merge the cyrus PreToolUse hook into a settings.json dict.

    Returns (merged, changed). Never mutates `existing`. Scans every
    `hooks.PreToolUse[*].hooks[*]` entry for a matching `command`; if found
    anywhere, returns a deep-copy + changed=False (idempotent). Otherwise
    appends a fresh `{"matcher": "*", "hooks": [{"type":"command","command":cyrus_command}]}`
    block to `hooks.PreToolUse` and returns (merged, True).
    """
    merged = copy.deepcopy(existing) if existing else {}
    hooks_block = merged.setdefault("hooks", {})
    if not isinstance(hooks_block, dict):
        # User shipped a broken shape -- overwrite defensively rather than crash.
        hooks_block = {}
        merged["hooks"] = hooks_block

    pretool = hooks_block.get("PreToolUse")
    if not isinstance(pretool, list):
        pretool = []

    # Scan for an existing cyrus entry anywhere under PreToolUse.
    for entry in pretool:
        if not isinstance(entry, dict):
            continue
        nested = entry.get("hooks")
        if not isinstance(nested, list):
            continue
        for h in nested:
            if isinstance(h, dict) and h.get("command") == cyrus_command:
                # Already registered somewhere. Return the deep-copied input.
                hooks_block["PreToolUse"] = pretool
                return (merged, False)

    # Not found -- append a fresh block.
    pretool.append(
        {
            "matcher": "*",
            "hooks": [{"type": "command", "command": cyrus_command}],
        }
    )
    hooks_block["PreToolUse"] = pretool
    return (merged, True)


# ----------------------------------------------------------------------
# Backup helper
# ----------------------------------------------------------------------
def backup_file(path: Path) -> Path | None:
    """Copy `path` to a sibling `.bak.<timestamp>` file; return the bak path.

    Returns None if `path` does not exist (nothing to back up). Uses local
    time with a cp1252-safe digit-and-hyphen timestamp suffix.
    """
    path = Path(path)
    if not path.exists():
        return None
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    bak = path.with_name(f"{path.name}.bak.{ts}")
    bak.write_bytes(path.read_bytes())
    return bak


# ----------------------------------------------------------------------
# Atomic JSON write
# ----------------------------------------------------------------------
def write_json_atomic(path: Path, data: Any) -> None:
    """Write `data` as indented, sort-keyed JSON via cyrus.storage.atomic_write.

    Creates the parent directory as needed. Uses indent=2 + sort_keys=True
    so diffs between successive writes stay minimal and review-friendly.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(data, indent=2, sort_keys=True) + "\n"
    atomic_write(path, content)


# ----------------------------------------------------------------------
# stderr status line
# ----------------------------------------------------------------------
def say(message: str, stream: TextIO | None = None) -> None:
    """Write `message + '\\n'` to `stream` (default: sys.stderr) and flush.

    Status output in `cyrus init`, `cyrus doctor`, etc. goes to stderr so
    stdout stays reserved for single-purpose machine-readable output (the
    `claude mcp add` hint in init, the JSON blob in `doctor --json`).
    """
    target = stream if stream is not None else sys.stderr
    target.write(message + "\n")
    try:
        target.flush()
    except (ValueError, OSError):
        # Stream may be a StringIO that still supports flush, or a real
        # stream that's closed. Either way, the bytes are in the buffer.
        pass
