"""Cyrus rules engine — pure-logic matcher for tool-scoped rules.

Public surface:
- Rule: frozen dataclass representing a compiled rule
- load_rules(rules_dir, hook_event, tool_name) -> list[Rule]
- evaluate(rules, tool_input) -> Rule | None
- test_rule(rule_name, tool_name, tool_input) -> dict  (dry-run)
- clear_cache() -> None

load_rules reads from disk (with mtime-based cache) and filters to rules
matching the given (hook_event, tool_name). evaluate is a pure function over
an already-loaded rule list — no I/O inside. This split is deliberate: the
Phase 4 PreToolUse hook wants load_rules on startup / on rule-dir change and
evaluate on every tool call, hot-path-friendly.

Precedence (RULES-05): block severity beats warn; within the same severity
the highest priority wins; within the same (severity, priority) the first
rule by sorted filename wins AND a tie warning is logged to stderr naming
every tied rule.

Cache (RULES-06): keyed on (file_count, max_mtime) of *.md files in the
rules dir. Touching or adding any .md file invalidates. We cache the FULL
parsed rule list per directory (not per hook_event/tool filter) so changing
the filter arguments reuses the same parse. clear_cache() drops everything
and forces a re-parse on the next load.

Pause (RULES-08): CYRUS_PAUSE is a comma-separated list of rule names to
suppress. Read every load_rules call so tests can flip it per-test.

Strict parsing (RULES-02): invalid frontmatter / unknown severity / broken
regex is logged loudly to stderr and skipped — never silently ignored. The
offending filename and the reason both appear in the log.
"""
# Requirement coverage (Phase 3 / RULES-*):
#   RULES-01: Rule file format + required fields — _parse_rule_file
#   RULES-02: Strict parsing, loud stderr, skip-don't-silence — _load_all
#   RULES-03: Tool-scoped matching + "*" wildcard — load_rules filter
#   RULES-04: Anchored-by-default regex — _anchor_pattern + anchored frontmatter
#   RULES-05: block > warn, priority, first-match tie + log — evaluate
#   RULES-06: Compile cache keyed on dir mtime + count — _CACHE + _dir_cache_key
#   RULES-07: test_rule() dry-run — public function
#   RULES-08: CYRUS_PAUSE env var override — _paused_names
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cyrus._rulesutil import (
    _compile_rule_pattern,  # noqa: F401 — re-exported for Phase 5 cyrus_add_rule validation
    _dir_cache_key,
    _flatten_tool_input,
    _parse_rule_file,
)
from cyrus.logutil import get_logger
from cyrus.paths import category_dir

_log = get_logger(__name__)

_PAUSE_ENV = "CYRUS_PAUSE"

# Cache: resolved-dir-str → (dir_cache_key, parsed_rule_list).
# The parsed list is the FULL result of walking the dir — filtering by
# hook_event + tool_name happens in load_rules after the cache lookup, so
# changing either filter does not cost a re-parse.
_CACHE: dict[str, tuple[tuple[int, float], list["Rule"]]] = {}


@dataclass(frozen=True)
class Rule:
    """Compiled rule loaded from a ~/.cyrus/rules/<name>.md markdown file.

    Frozen + hashable: `triggers` and `matches` are tuples (not lists) so the
    dataclass can live in sets / be used as a dict key. `pattern` is an
    `re.Pattern` — not reliably equality-comparable, so equality on Rule is
    useful chiefly for (name, severity, priority) inspection rather than
    identity. `raw_pattern` is preserved verbatim for logging / re-display.
    """

    name: str
    severity: str                    # "block" | "warn"
    triggers: tuple[str, ...]
    matches: tuple[str, ...]
    pattern: re.Pattern[str]
    priority: int
    message: str
    raw_pattern: str
    anchored: bool


def clear_cache() -> None:
    """Drop every cached parsed-rule list. Next load_rules re-reads from disk."""
    _CACHE.clear()


def _paused_names() -> set[str]:
    """Parse CYRUS_PAUSE env var into a set of rule names to suppress.

    Read every call (no caching) so tests can flip the env mid-process. CSV
    format; whitespace around each name is stripped; empty entries skipped.
    """
    raw = os.environ.get(_PAUSE_ENV, "")
    return {n.strip() for n in raw.split(",") if n.strip()}


def _load_all(rules_dir: Path) -> list[Rule]:
    """Parse every *.md file under `rules_dir`, cache-aware.

    Invalid rules (missing field, bad severity, broken regex, read error) are
    logged to stderr via cyrus.logutil and SKIPPED — never silenced. Other
    rules in the same directory continue to load.
    """
    rules_dir = Path(rules_dir).resolve()
    key = str(rules_dir)
    cache_key = _dir_cache_key(rules_dir)
    cached = _CACHE.get(key)
    if cached is not None and cached[0] == cache_key:
        return cached[1]

    rules: list[Rule] = []
    if rules_dir.exists():
        # sorted() ensures deterministic tie-break order (matches filename
        # alphabetic — the convention documented in RULES-05).
        for path in sorted(rules_dir.glob("*.md")):
            if not path.is_file():
                continue
            try:
                rules.append(_parse_rule_file(path))
            except (ValueError, OSError) as exc:
                # Loud — the filename AND the reason both appear.
                _log.error("invalid rule %s: %s", path.as_posix(), exc)
                continue
    _CACHE[key] = (cache_key, rules)
    return rules


def load_rules(
    rules_dir: Path,
    hook_event: str,
    tool_name: str,
) -> list[Rule]:
    """Return rules scoped to (hook_event, tool_name), pause-aware.

    The filter runs after the (cached) full parse so changing hook_event /
    tool_name between calls does not re-read disk. CYRUS_PAUSE is re-read
    on every call.

    Returns a list sorted by filename (same order as `_load_all`). Empty if
    the dir is missing or no rule matches.
    """
    paused = _paused_names()
    all_rules = _load_all(Path(rules_dir))
    out: list[Rule] = []
    for rule in all_rules:
        if rule.name in paused:
            continue
        if hook_event not in rule.triggers:
            continue
        if "*" not in rule.matches and tool_name not in rule.matches:
            continue
        out.append(rule)
    return out


def evaluate(rules: list[Rule], tool_input: dict[str, Any]) -> Rule | None:
    """Return the winning rule per precedence, or None.

    Precedence: block beats warn; highest priority wins; first match (the
    input list's order — load_rules sorts by filename) breaks ties. Ties on
    (severity, priority) write a stderr warning naming every tied rule.

    Pure: no disk I/O. `tool_input` is flattened via json.dumps so every
    value (including nested structures) is visible to the pattern search.
    """
    if not rules:
        return None
    flat = _flatten_tool_input(tool_input)
    matched = [r for r in rules if r.pattern.search(flat)]
    if not matched:
        return None

    # Sort key: block first (0), warn second (1); then highest priority first.
    # Python's sort is stable — rules tied on (severity, priority) retain
    # their input order, which from load_rules is filename-sorted.
    def _rank(r: Rule) -> tuple[int, int]:
        return (0 if r.severity == "block" else 1, -r.priority)

    matched.sort(key=_rank)
    winner = matched[0]
    winner_key = (winner.severity, winner.priority)
    tied = [r for r in matched if (r.severity, r.priority) == winner_key]
    if len(tied) > 1:
        others = [r.name for r in tied if r.name != winner.name]
        _log.warning(
            "cyrus.rules: tie between %s and %s, using %s",
            winner.name,
            ", ".join(others),
            winner.name,
        )
    return winner


def test_rule(
    rule_name: str,
    tool_name: str,
    tool_input: dict[str, Any],
) -> dict[str, Any]:
    """Dry-run a single rule by filename stem against `(tool_name, tool_input)`.

    Reads ~/.cyrus/rules/<rule_name>.md directly (no cache — this is a
    diagnostic aid, not the hot path). Returns a structured dict:

        {"matched": bool, "severity": str, "message": str, "rule": str}

    `matched` is True only when both the pattern matches the flattened input
    AND the tool_name is in the rule's matches list (or wildcard). Raises
    FileNotFoundError if the rule file does not exist.
    """
    rules_dir = category_dir("rules")
    rule_path = rules_dir / f"{rule_name}.md"
    if not rule_path.exists():
        raise FileNotFoundError(f"rule not found: {rule_path}")
    rule = _parse_rule_file(rule_path)
    flat = _flatten_tool_input(tool_input)
    tool_scoped = "*" in rule.matches or tool_name in rule.matches
    matched = tool_scoped and bool(rule.pattern.search(flat))
    return {
        "matched": matched,
        "severity": rule.severity,
        "message": rule.message,
        "rule": rule.name,
    }
