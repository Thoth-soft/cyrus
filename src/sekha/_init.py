"""`sekha init` implementation.

One-shot setup. Ensures ~/.sekha/ exists with the 5-category subdir layout,
writes the default config.json, and merges the PreToolUse hook registration
into ~/.claude/settings.json. Idempotent: running twice produces exactly
one sekha hook entry in settings.json and leaves existing user data intact.

Separated from cli.py so tests can drive the full flow via `_init.run([])`
without going through argparse again. cli.py's "init" subcommand is a thin
shim that calls this run().

Design invariants:
- Status messages go to stderr via say(); stdout is reserved for the single
  user-facing directive (the `claude mcp add` hint) so scripts can pipe it.
- settings.json is backed up BEFORE any merge so a broken merge never
  destroys the user's prior config. The backup lives next to the file with
  a timestamped suffix -- humans can recover it by hand.
- Merge logic is idempotent: merge_claude_settings returns changed=False
  when the sekha command is already present, and the file is not rewritten.
- Every output byte is pure ASCII (cp1252 safe on Windows cmd.exe).
"""
# Requirement coverage:
#   CLI-01: `sekha init` creates ~/.sekha/ tree + config.json + merges
#           hook into ~/.claude/settings.json + prints MCP-add hint.
#   CLI-02: Running twice produces exactly one sekha hook entry.
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sekha._cliutil import (
    backup_file,
    merge_claude_settings,
    say,
    write_json_atomic,
)
from sekha.paths import CATEGORIES, sekha_home

_DEFAULT_CONFIG = {
    "version": "0.0.0",
    "hook_enabled": True,
    "hook_budget_ms": {"p50": 50, "p95": 150},
}

# The single user-facing directive printed to stdout on success. stderr
# carries progress logs; stdout carries the command the user should run
# next, so pipeline consumers (`sekha init | grep claude`) see just that.
_MCP_ADD_HINT = (
    "Next step: register the MCP server:\n"
    "  claude mcp add sekha -- sekha serve\n"
    "Verify with: sekha doctor\n"
)


def run(argv: list[str] | None = None) -> int:
    """Execute `sekha init`. Returns process exit code (0 on success)."""
    parser = argparse.ArgumentParser(
        prog="sekha init",
        description="Create ~/.sekha/ tree, write config, register hook in "
                    "~/.claude/settings.json",
    )
    parser.parse_args(argv or [])

    # 1. ~/.sekha/ tree + category subdirs.
    home = sekha_home()
    home.mkdir(parents=True, exist_ok=True)
    for cat in CATEGORIES:
        (home / cat).mkdir(parents=True, exist_ok=True)
    say(f"[OK] created {home}")

    # 2. ~/.sekha/config.json (only if missing; do not clobber user edits).
    config_path = home / "config.json"
    if not config_path.exists():
        write_json_atomic(config_path, _DEFAULT_CONFIG)
        say(f"[OK] wrote {config_path}")
    else:
        say("[OK] config.json already present")

    # 3. ~/.claude/settings.json merge: read existing, back up, merge, write.
    settings_path = Path.home() / ".claude" / "settings.json"
    existing: dict = {}
    if settings_path.exists():
        try:
            existing = json.loads(settings_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            say(f"[FAIL] cannot parse {settings_path}: {exc}")
            return 1
        if not isinstance(existing, dict):
            say(f"[FAIL] {settings_path} is not a JSON object")
            return 1

    merged, changed = merge_claude_settings(existing)

    if changed:
        # Only back up when we are actually about to write a new settings.json.
        # Pre-existing file => backup; missing file => nothing to back up.
        if settings_path.exists():
            bak = backup_file(settings_path)
            if bak is not None:
                say(f"[OK] backed up settings.json -> {bak.name}")
        write_json_atomic(settings_path, merged)
        say(f"[OK] merged sekha hook into {settings_path}")
    else:
        say("[OK] sekha hook already registered in settings.json")

    # 4. Tell the user what to do next. STDOUT so pipelines can capture it.
    sys.stdout.write(_MCP_ADD_HINT)
    try:
        sys.stdout.flush()
    except (ValueError, OSError):
        pass
    return 0
