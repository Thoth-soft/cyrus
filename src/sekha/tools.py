"""Tool handlers for the Sekha MCP server.

Every handler is a pure function that delegates to existing library code
(sekha.storage, sekha.search, sekha.rules). Handlers accept kwargs
matching each tool's inputSchema (see sekha.schemas.TOOLS) and return
JSON-serializable dicts. On bad input they raise — the server loop
(Plan 05-02) wraps raises into MCP error responses with isError=True.

No protocol logic here. No I/O outside the library calls we already
own. No print() anywhere — the CI lint gate enforces that on every
commit. The boring-but-deadly stuff (stdio, framing, negotiation)
lives in sekha.jsonrpc and sekha.server.

HANDLERS dict at the bottom is the name -> callable dispatch table the
server's tools/call method consumes.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from sekha.logutil import get_logger
from sekha.paths import CATEGORIES, category_dir, sekha_home
from sekha.storage import (
    atomic_write,
    dump_frontmatter,
    parse_frontmatter,
    save_memory,
)

_log = get_logger(__name__)


# --------------------------------------------------------------------------
# sekha_save (MCP-04)
# --------------------------------------------------------------------------
def sekha_save(
    category: str,
    content: str,
    tags: list[str] | None = None,
    source: str | None = None,
) -> dict[str, Any]:
    """Delegates to sekha.storage.save_memory.

    Returns {"path": str, "id": str} where `id` is the 8-hex blake2b
    digest embedded in the filename (YYYY-MM-DD_<id>_<slug>.md). Raises
    ValueError on unknown category (propagated from save_memory).
    """
    path = save_memory(
        category=category,
        content=content,
        tags=tags,
        source=source,
    )
    # Filename carries the id: YYYY-MM-DD_<id>_<slug>.md
    id_hex = path.stem.split("_", 2)[1]
    return {"path": str(path), "id": id_hex}


# --------------------------------------------------------------------------
# sekha_search (MCP-05)
# --------------------------------------------------------------------------
def sekha_search(
    query: str,
    category: str | None = None,
    limit: int = 10,
    tags: list[str] | None = None,
) -> dict[str, Any]:
    """Delegates to sekha.search.search. Serializes SearchResult objects.

    The search import is lazy: sekha.search pulls in re/dataclasses/heapq
    on import, which we don't want to pay on a hook-light sekha_status
    call. Import-time still amortized well because most server sessions
    will issue at least one search.
    """
    # Lazy import — sekha.search is heavier than the others.
    from sekha.search import search as _search

    results = _search(
        query=query,
        category=category,
        limit=limit,
        tags=tags,
    )
    return {
        "results": [
            {
                "path": str(r.path),
                "score": r.score,
                "snippet": r.snippet,
                "metadata": r.metadata,
            }
            for r in results
        ]
    }


# --------------------------------------------------------------------------
# sekha_list (MCP-06)
# --------------------------------------------------------------------------
def sekha_list(
    category: str | None = None,
    limit: int = 20,
    since: str | None = None,
) -> dict[str, Any]:
    """List memory metadata (no body content).

    Walks the selected category subtree(s), parses frontmatter, returns
    the metadata keys per file. The `since` filter is an ISO-8601 string
    comparison (same as sekha.search — lex order == chronological order
    for ISO-8601 with consistent precision). Results sorted by updated
    desc and truncated to `limit`.
    """
    if category is not None and category not in CATEGORIES:
        raise ValueError(
            f"Unknown category {category!r}. Valid: {CATEGORIES}"
        )
    roots = (
        [category_dir(category)]
        if category is not None
        else [sekha_home() / c for c in CATEGORIES]
    )
    out: list[dict[str, Any]] = []
    for root in roots:
        if not root.exists():
            continue
        for p in sorted(root.glob("*.md")):
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
                metadata, _body = parse_frontmatter(text)
            except (OSError, ValueError) as e:
                _log.warning("sekha_list: skipping %s: %s", p, e)
                continue
            if since is not None:
                updated = metadata.get("updated", "")
                if not updated or updated < since:
                    continue
            out.append(
                {
                    "path": str(p),
                    "category": metadata.get("category", root.name),
                    "id": metadata.get("id", ""),
                    "created": metadata.get("created", ""),
                    "updated": metadata.get("updated", ""),
                    "tags": metadata.get("tags", []),
                }
            )
    out.sort(key=lambda m: m.get("updated", ""), reverse=True)
    return {"memories": out[:limit]}


# --------------------------------------------------------------------------
# sekha_delete (MCP-07)
# --------------------------------------------------------------------------
def sekha_delete(path: str) -> dict[str, Any]:
    """Delete a memory file. Path MUST resolve under sekha_home().

    Security requirement: the MCP tool MUST refuse arbitrary filesystem
    deletion — an attacker who compromised Claude could otherwise call
    sekha_delete("/etc/passwd"). We resolve the path and confirm it lives
    under sekha_home() before touching it.

    Returns {"success": True, "path": ...} on success,
    {"success": False, "error": ...} on any failure. Does NOT raise for
    missing files or scope violations — those are normal failure modes
    callers expect to get back as data, not exceptions.
    """
    try:
        target = Path(path).resolve()
        home = sekha_home().resolve()
        # Scope check — refuse arbitrary FS access.
        try:
            target.relative_to(home)
        except ValueError:
            return {
                "success": False,
                "error": f"path not under sekha_home(): {path}",
            }
        if not target.exists():
            return {"success": False, "error": f"not found: {path}"}
        target.unlink()
        return {"success": True, "path": str(target)}
    except OSError as e:
        return {"success": False, "error": str(e)}


# --------------------------------------------------------------------------
# sekha_status (MCP-08)
# --------------------------------------------------------------------------
def sekha_status() -> dict[str, Any]:
    """Report totals, per-category counts, rules count, recent, hook errors.

    All counts come from a cheap glob walk — no frontmatter parse for the
    per-category numbers. The `recent` list parses frontmatter for up to
    the 5 most recently updated memories so callers can render a "last
    activity" ribbon. hook_errors is the line count of
    ~/.sekha/hook-errors.log (written by sekha.hook fail-open); returns
    0 when the log is absent, -1 on read error.
    """
    home = sekha_home()

    by_category: dict[str, int] = {}
    total = 0
    for cat in CATEGORIES:
        d = home / cat
        n = sum(1 for _ in d.glob("*.md")) if d.exists() else 0
        by_category[cat] = n
        total += n

    rules_dir = home / "rules"
    rules_count = (
        sum(1 for _ in rules_dir.glob("*.md")) if rules_dir.exists() else 0
    )

    # Hook errors: line count of ~/.sekha/hook-errors.log. Every entry is
    # a single line (sekha._hookutil.record_error appends one per error),
    # so sum(1 for _ in open(...)) is a faithful count.
    hook_errors = 0
    err_log = home / "hook-errors.log"
    if err_log.exists():
        try:
            with err_log.open("r", encoding="utf-8", errors="replace") as f:
                hook_errors = sum(1 for _ in f)
        except OSError:
            hook_errors = -1

    # Recent: walk every category, parse frontmatter, sort updated desc,
    # keep top 5. O(total) — fine for sekha_status's expected usage.
    recent: list[dict[str, Any]] = []
    for cat in CATEGORIES:
        d = home / cat
        if not d.exists():
            continue
        for p in d.glob("*.md"):
            try:
                meta, _ = parse_frontmatter(
                    p.read_text(encoding="utf-8", errors="replace")
                )
            except (OSError, ValueError):
                continue
            recent.append(
                {
                    "path": str(p),
                    "category": meta.get("category", cat),
                    "updated": meta.get("updated", ""),
                }
            )
    recent.sort(key=lambda m: m.get("updated", ""), reverse=True)

    return {
        "total": total,
        "by_category": by_category,
        "rules_count": rules_count,
        "recent": recent[:5],
        "hook_errors": hook_errors,
    }


# --------------------------------------------------------------------------
# sekha_add_rule (MCP-09)
# --------------------------------------------------------------------------
def sekha_add_rule(
    name: str,
    severity: str,
    matches: list[str],
    pattern: str,
    message: str,
    priority: int = 50,
    triggers: list[str] | None = None,
) -> dict[str, Any]:
    """Create a rule file under rules/. Validates regex BEFORE write.

    MCP-09's hard requirement is that a broken pattern must NOT leave a
    corrupt rule file on disk. We route the pattern through the same
    _compile_rule_pattern helper sekha.rules uses so anchoring behavior
    stays consistent (anchored=True by default — matches sekha.rules
    load-time behavior).

    Raises re.error if the pattern doesn't compile (before any disk I/O).
    Raises ValueError on unknown severity or an invalid rule name.
    """
    if severity not in ("block", "warn"):
        raise ValueError(
            f"severity must be 'block' or 'warn', got {severity!r}"
        )
    if not name or "/" in name or "\\" in name:
        raise ValueError(f"invalid rule name: {name!r}")

    # Hard pre-flight: regex must compile. Delegates to the same helper
    # sekha.rules uses at load time so a rule accepted here loads cleanly
    # later. Raises re.error on a bad pattern — we let that propagate
    # rather than wrap, because the server loop already converts raises
    # into MCP error responses.
    from sekha._rulesutil import _compile_rule_pattern
    _compile_rule_pattern(pattern, anchored=True)

    rules_dir = category_dir("rules")
    rules_dir.mkdir(parents=True, exist_ok=True)
    rule_path = rules_dir / f"{name}.md"
    effective_triggers = list(triggers) if triggers else ["PreToolUse"]
    metadata: dict[str, Any] = {
        "name": name,
        "severity": severity,
        "triggers": effective_triggers,
        "matches": list(matches),
        "pattern": pattern,
        "priority": int(priority),
        "message": message,
    }
    document = dump_frontmatter(metadata, "")
    atomic_write(rule_path, document)
    return {"path": str(rule_path)}


# --------------------------------------------------------------------------
# Dispatch table — tools/call method looks up handlers by name.
# --------------------------------------------------------------------------
HANDLERS: dict[str, Any] = {
    "sekha_save":     sekha_save,
    "sekha_search":   sekha_search,
    "sekha_list":     sekha_list,
    "sekha_delete":   sekha_delete,
    "sekha_status":   sekha_status,
    "sekha_add_rule": sekha_add_rule,
}
