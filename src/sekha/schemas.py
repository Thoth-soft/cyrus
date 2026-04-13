"""Hand-written JSON schemas for the 6 Sekha MCP tools.

Source of truth for the MCP `tools/list` response. Every schema is
authored by hand — we ship no jsonschema runtime dependency (stdlib-only
policy, Zero runtime deps per CONTRIBUTING.md) — and is intentionally
small so Claude Code's tool-card renderer can display them readably.

Consumed by:
  - sekha.tools.HANDLERS dispatch table (name -> handler)
  - sekha.server (Plan 05-02) `tools/list` method returns TOOLS verbatim

Any change here is also a change to the MCP protocol surface: update
REQUIREMENTS.md MCP-03..MCP-09 if the set of tools or their required
fields evolves.
"""
from __future__ import annotations

from typing import Any

from sekha.paths import CATEGORIES

# --------------------------------------------------------------------------
# TOOLS — ordered for stable output on tools/list. Ordering has no protocol
# meaning; it's just deterministic so diffs stay minimal when we add a
# field to one schema.
# --------------------------------------------------------------------------
TOOLS: list[dict[str, Any]] = [
    {
        "name": "sekha_save",
        "description": (
            "Save a memory. category must be one of: "
            + ", ".join(CATEGORIES) + "."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "enum": list(CATEGORIES),
                },
                "content": {"type": "string"},
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "source": {"type": "string"},
            },
            "required": ["category", "content"],
        },
    },
    {
        "name": "sekha_search",
        "description": (
            "Full-text search over saved memories, ranked by term "
            "frequency * recency * filename match."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "category": {"type": "string"},
                "limit": {"type": "integer", "default": 10},
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "sekha_list",
        "description": (
            "List memories in a category with metadata only (no body "
            "content)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "category": {"type": "string"},
                "limit": {"type": "integer", "default": 20},
                "since": {
                    "type": "string",
                    "description": "ISO-8601 timestamp",
                },
            },
            "required": [],
        },
    },
    {
        "name": "sekha_delete",
        "description": "Delete a memory by path. Returns success/failure.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "sekha_status",
        "description": (
            "Return total memory count, category breakdown, rules count, "
            "recent activity, hook error count."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "sekha_add_rule",
        "description": (
            "Create a new rule file. Validates regex compiles before "
            "writing."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "severity": {
                    "type": "string",
                    "enum": ["block", "warn"],
                },
                "matches": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "pattern": {"type": "string"},
                "message": {"type": "string"},
                "priority": {"type": "integer", "default": 50},
                "triggers": {
                    "type": "array",
                    "items": {"type": "string"},
                    "default": ["PreToolUse"],
                },
            },
            "required": [
                "name", "severity", "matches", "pattern", "message",
            ],
        },
    },
]


# --------------------------------------------------------------------------
# Convenience lookup for server dispatch and tool_call handlers. Built from
# the authoritative TOOLS list so the two stay in sync automatically.
# --------------------------------------------------------------------------
TOOLS_BY_NAME: dict[str, dict[str, Any]] = {t["name"]: t for t in TOOLS}
