# Sekha

## What This Is

Sekha is a zero-dependency AI memory system for developers using Claude Code, Cursor, and other MCP-compatible AI tools. It gives your AI persistent memory across sessions — conversations, decisions, preferences — stored as plain markdown files you can read, grep, git-track, and edit by hand. The anti-MemPalace: same core value proposition, 1% of the complexity.

## Core Value

**The AI actually follows rules you give it.** Rules enforcement is enforced at the system level via PreToolUse hooks, not relying on the AI to "remember." Memory + enforcement in one system. If this works and nothing else does, Sekha succeeds.

## Requirements

### Validated

(None yet — ship to validate)

### Active

- [ ] Save memories (conversations, decisions, preferences) to plain markdown files
- [ ] Search memories via grep (zero dependencies, fast enough for 10k+ files)
- [ ] List and browse stored memories by category
- [ ] Delete memories
- [ ] **Rules enforcement system** — store mandatory AI directives that get injected before every tool call via PreToolUse hook
- [ ] MCP server exposing 4-6 tools (save, search, list, delete, status, add-rule)
- [ ] Auto-save hook that fires every N messages (configurable)
- [ ] One-command setup: `pip install sekha-memory && sekha init && claude mcp add sekha`
- [ ] Cross-platform (Windows, macOS, Linux) — tested on all three
- [ ] Python stdlib only (no chromadb, no numpy, no tokenizers, no ML models)
- [ ] Open source on GitHub with clear README, examples, and contribution guide

### Out of Scope

- **Vector / semantic search** — grep is good enough, and vector search means heavy dependencies (chromadb, embedding models, 100MB+ downloads). Not what we want.
- **Custom compression dialects (like AAAK)** — clever but unreadable by humans. Plain markdown wins.
- **Knowledge graphs / temporal triples** — overkill for v1. Could be a v2 feature if users ask for it.
- **Entity detection / auto-classification** — fragile and fails on real data. AI writes memories explicitly; no guessing.
- **Conversation mining from external sources** (Slack, ChatGPT exports) — nice-to-have but scope creep. v2 feature.
- **Non-MCP clients (CLI-only workflows)** — MCP integration is the primary interface. CLI is a thin wrapper for debugging.
- **GUI / dashboard** — files in a folder. Users can browse them with any editor. No web UI in v1.
- **Cloud sync / multi-device** — local files only. Users can sync via Dropbox/iCloud/git if they want. Not our problem.

## Context

**Why this exists:** We tried MemPalace (github.com/milla-jovovich/mempalace). Great pitch — AI memory that persists across sessions, 96.6% LongMemEval recall, local-only, free. Reality: ~60 pip dependencies, 167MB ChromaDB cache, custom "AAAK" compression dialect, 19 MCP tools, custom JSON-RPC protocol that required a wrapper to connect to Claude Code. Installation took ~20 minutes of debugging. The palace metaphor (wings, rooms, halls, tunnels, closets, drawers) added cognitive overhead without clear benefit. It worked eventually, but the effort-to-value ratio was poor.

**The bigger insight:** AI assistants read rules then ignore them. Memory systems store preferences but don't enforce them. We repeatedly had incidents where feedback memories ("always confirm before action") were written but violated anyway. The missing piece is **enforcement**, not storage. Sekha's differentiator is a rules system that runs at the hook level — the AI literally cannot bypass it because the system blocks tool calls that violate active rules.

**Target users:** Solo developers and small teams using Claude Code (primary), Cursor, Cline, and other MCP-compatible AI coding tools. Users who want AI memory without a database, without a cloud service, without a custom query language. Users who have been burned by AI forgetting their preferences mid-session.

**Technical environment:** Claude Code 2.1.x+ on Windows/macOS/Linux. Python 3.9+ (widely available). MCP protocol (stdio transport, newline-delimited JSON-RPC — the version Claude Code actually speaks).

## Constraints

- **Tech stack**: Python stdlib only — no pip dependencies beyond what's already in the interpreter. Why: installation friction was MemPalace's biggest failure. Every dependency is a potential install failure.
- **Storage**: Plain markdown files on local disk. Why: grep-searchable, git-trackable, human-readable, editable with any tool. No database lock-in.
- **MCP protocol**: Newline-delimited JSON-RPC over stdio. Why: this is what Claude Code actually uses, confirmed by directly testing MemPalace's server.
- **Tool count**: 4-6 MCP tools max. Why: MemPalace had 19 — overwhelming. Fewer tools = easier to learn and harder to misuse.
- **Cross-platform**: Windows paths, macOS paths, Linux paths must all work. Why: the user encountered Windows-specific issues with MemPalace (UTF-8 encoding, text-mode stdin).
- **Rules enforcement**: Must work via PreToolUse hook, not just prompt injection. Why: prompt injection gets ignored; hook-level blocking cannot be bypassed by the AI.
- **License**: MIT. Why: maximum adoption, zero friction for contributors.

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Name: "Sekha" | Short, memorable, brain metaphor, not already taken in this space | — Pending |
| Plain markdown files over SQLite/ChromaDB | Zero deps, git-trackable, human-readable, grep-searchable | — Pending |
| Grep-based search over semantic search | Zero deps, fast enough, good enough for most queries | — Pending |
| Rules enforcement as a core feature (not optional) | This is the key differentiator from MemPalace and every other memory system | — Pending |
| PreToolUse hook for rule enforcement | Only way to actually block the AI from violating rules | — Pending |
| Python stdlib only | Installation must not fail; every dep is a risk | — Pending |
| Newline-delimited JSON-RPC (not Content-Length) | Claude Code uses this; confirmed via MemPalace debugging | — Pending |
| GitHub repo at github.com/Mo-Hendawy/sekha | User's account, open source, MIT | — Pending |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd:transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd:complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-04-07 after initialization*
