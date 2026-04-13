"""Private helpers for sekha.rules.

Frontmatter parsing, regex anchoring, tool_input flattening, and dir cache-key
computation. Not a public API — every function is underscore-prefixed and
subject to change. Public surface is re-exported piecemeal by `sekha.rules`.

Design notes:
- `_anchor_pattern` is idempotent: a pattern already carrying `^`/`$` is not
  double-anchored. This matters because rules are authored by humans who may
  pre-anchor — we preserve intent rather than corrupt it into `^^foo$$`.
- `_flatten_tool_input` uses `json.dumps(..., sort_keys=True, default=str)` so
  pattern matches are deterministic regardless of dict insertion order. The
  `default=str` is a safety net for non-JSON types (Path, datetime) that
  occasionally appear in tool_input payloads.
- `_parse_rule_file` is strict: missing required fields, invalid severity
  values, and broken regex all raise ValueError. Callers (sekha.rules.load_rules)
  convert these into loud stderr warnings and skip the offending file — we
  intentionally refuse to silently ignore bad rules, per RULES-02.
- `_dir_cache_key` uses `(file_count, max_mtime)` — a file added or touched
  changes at least one component. Delete-without-replace is detected because
  the count drops. We deliberately do NOT hash file contents: that would shift
  the cost from cache-miss (already acceptable) to every cache-hit.
- `Rule` is defined in `sekha.rules` to keep the public dataclass in the public
  module. We import it lazily inside `_parse_rule_file` to avoid a circular
  import at module-load time.

Stdlib only. No logging in this module — helpers are pure; `sekha.rules` does
the logging around them.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sekha.storage import parse_frontmatter

if TYPE_CHECKING:
    from sekha.rules import Rule

_REQUIRED_FIELDS: tuple[str, ...] = ("severity", "triggers", "matches", "pattern")
_VALID_SEVERITIES: frozenset[str] = frozenset({"block", "warn"})


def _anchor_pattern(raw: str, *, anchored: bool) -> str:
    """Wrap `raw` with `^`/`$` when `anchored=True`, idempotently.

    Already-anchored patterns (starting with `^`, ending with `$`, or both)
    are preserved verbatim — no double-anchoring. When `anchored=False` the
    pattern is returned unchanged regardless of existing anchors.
    """
    if not anchored:
        return raw
    prefix = "" if raw.startswith("^") else "^"
    suffix = "" if raw.endswith("$") else "$"
    return f"{prefix}{raw}{suffix}"


def _flatten_tool_input(tool_input: dict[str, Any]) -> str:
    """Serialize `tool_input` to a deterministic JSON string for pattern matching.

    Keys sorted so the output is reproducible. `default=str` catches
    non-JSON-serializable values (Path, datetime, custom objects) by falling
    back to their string representation rather than raising.
    """
    return json.dumps(tool_input, sort_keys=True, default=str)


def _compile_rule_pattern(raw: str, *, anchored: bool) -> re.Pattern[str]:
    """Compile `raw` (anchored as configured) with `re.IGNORECASE`.

    Raises `re.error` on invalid regex; callers convert that to ValueError
    with path context.
    """
    return re.compile(_anchor_pattern(raw, anchored=anchored), re.IGNORECASE)


def _parse_rule_file(path: Path) -> "Rule":
    """Parse a rule markdown file into a `Rule` instance.

    Strict: raises ValueError on missing required fields, invalid severity,
    or broken regex. Callers (sekha.rules.load_rules) catch and log-and-skip;
    individual-file consumers (test_rule) let the error propagate.
    """
    # Lazy import: Rule lives in sekha.rules, which imports from us.
    from sekha.rules import Rule

    text = path.read_text(encoding="utf-8")
    meta, body = parse_frontmatter(text)

    missing = [f for f in _REQUIRED_FIELDS if f not in meta]
    if missing:
        raise ValueError(f"missing field: {missing[0]} in {path}")

    severity = meta["severity"]
    if severity not in _VALID_SEVERITIES:
        raise ValueError(
            f"invalid severity {severity!r} in {path} (must be block|warn)"
        )

    anchored = bool(meta.get("anchored", True))
    raw_pattern = str(meta["pattern"])
    try:
        compiled = _compile_rule_pattern(raw_pattern, anchored=anchored)
    except re.error as exc:
        raise ValueError(
            f"invalid regex pattern in {path}: {exc}"
        ) from exc

    triggers_raw = meta["triggers"]
    triggers = (
        tuple(str(t) for t in triggers_raw)
        if isinstance(triggers_raw, list)
        else (str(triggers_raw),)
    )
    matches_raw = meta["matches"]
    matches = (
        tuple(str(m) for m in matches_raw)
        if isinstance(matches_raw, list)
        else (str(matches_raw),)
    )
    priority = int(meta.get("priority", 0))
    # `message` frontmatter override wins; otherwise body text (stripped).
    message = str(meta.get("message") or body).strip()

    return Rule(
        name=path.stem,
        severity=severity,
        triggers=triggers,
        matches=matches,
        pattern=compiled,
        priority=priority,
        message=message,
        raw_pattern=raw_pattern,
        anchored=anchored,
    )


def _dir_cache_key(rules_dir: Path) -> tuple[int, float]:
    """Return `(file_count, max_mtime)` for *.md files under `rules_dir`.

    Used as the cache invalidation key. Adding/removing a file shifts the
    count; touching a file shifts the max_mtime. Non-existent directory or
    empty directory yields `(0, 0.0)`.
    """
    if not rules_dir.exists():
        return (0, 0.0)
    files = sorted(p for p in rules_dir.glob("*.md") if p.is_file())
    if not files:
        return (0, 0.0)
    max_mtime = max(p.stat().st_mtime for p in files)
    return (len(files), max_mtime)
