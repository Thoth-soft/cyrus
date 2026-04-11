# Feature Research

**Domain:** AI memory systems for developers (MCP-based)
**Researched:** 2026-04-11
**Confidence:** HIGH (Claude Code hooks API, MemPalace internals, MCP ecosystem) / MEDIUM (Mem0/Zep/Letta feature lists — verified against official docs and repos but not exhaustively tested)

## Executive Summary

The AI-memory-for-developers space in 2026 splits into three camps:

1. **Heavy stacks chasing benchmarks** (MemPalace, Mem0, Zep, Letta) — vector DBs, knowledge graphs, LLM-extracted entities, custom query languages. Optimized for LongMemEval scores. Painful to install, opaque storage, and *none of them enforce rules at the system level*.
2. **Built-in IDE memory** (Claude Code `CLAUDE.md`, Cursor `.cursor/rules/*.mdc`) — plain-text instructions injected into the system prompt. Free, zero-install, and *also unenforced* — empirical reports put compliance at 60–70% on a good day, with documented cases of Claude knowingly bypassing rules.
3. **Filesystem-as-memory MCP servers** (Basic Memory, Obsidian Memory MCP) — closer to Cortex's storage philosophy, but they still focus on knowledge graphs / semantic search and don't touch enforcement.

**The gap Cortex fills:** every system stores rules; none enforce them. Claude Code shipped 24 hook events in 2025–2026, including `PreToolUse` with a `permissionDecision: "deny"` output that blocks tool calls *even in `--dangerously-skip-permissions` mode*. This is the exact primitive needed to make rules un-bypassable, and no shipping memory system uses it. That is Cortex's moat.

## Competitor Profiles

### 1. MemPalace (the incumbent we're simplifying)

- **Storage:** ChromaDB (vector) + SQLite (metadata). ~167MB cache after first install; pulls a ~80MB sentence-transformers model.
- **Dependencies:** `chromadb >= 0.4.0`, `pyyaml >= 6.0`, plus transitive (~60 packages total). Python 3.9+.
- **MCP tools:** 19 — `status`, list wings/rooms, `taxonomy`, `search`, `duplicate_check`, graph traversal, tunnel finder, graph stats, KG query, AAAK spec, `add_drawer`, `delete_drawer`, `add_kg_triple`, KG invalidate, KG timeline, KG stats, diary write, diary read.
- **Memory model:** "Memory palace" metaphor — wings (people/projects) → halls (memory types) → rooms (topics) → drawers (individual memories). Plus a parallel knowledge graph layer with temporal triples, plus per-agent diaries.
- **Save:** Two Claude Code hooks. Save hook fires every 15 messages and structurally extracts topics, decisions, quotes, and code changes. Critical-facts layer is regenerated on each save.
- **Search:** Semantic vector search via ChromaDB embeddings, plus duplicate detection, plus graph traversal, plus a "tunnel finder" for cross-wing connections.
- **Rules enforcement:** None. AAAK is a token-compression dialect, not a rules system. No PreToolUse hook integration.
- **Storage opacity:** ChromaDB blobs and SQLite — not human-readable. Users cannot `cat` or `grep` raw memories without going through tools.
- **Install:** `pip install mempalace` (2–3 min on first install due to model download); MCP server registration requires a wrapper because MemPalace's JSON-RPC dialect doesn't speak Claude Code's newline-delimited transport out of the box.

### 2. Mem0 (commercial leader)

- **Storage:** Hybrid — vector DB (Qdrant by default) for semantic similarity, graph DB (Neo4j) for relationships, key-value store for fast facts.
- **Dependencies:** `mem0ai` package; self-hosted variant pulls `psycopg`, `langchain-neo4j`, `neo4j`, `rank-bm25`, `mem0ai[graph]`. Cloud variant requires `MEM0_API_KEY`.
- **Memory model:** LLM-extracted entities and relationships. Incoming messages run through an Entity Extractor (GPT-4o-mini with function calling) that produces nodes and edges. The Mem0ᵍ variant adds the graph layer for multi-session relationship reasoning.
- **Save:** LLM-extracted automatically. The system reads conversation turns and decides what to store, what to update, and what to delete.
- **Search:** Semantic embedding search + graph traversal + BM25 keyword. Hybrid retrieval ranks by similarity score.
- **Rules enforcement:** None at the agent level. Mem0 stores preferences as memories but does not gate tool calls.
- **Pricing:** Cloud is $19–$249/mo; self-hosted is free but requires Docker, Neo4j, Postgres.
- **Benchmarks:** ~49% on LongMemEval (significantly below Zep, MemPalace, OMEGA).
- **Install:** `pip install mem0ai` for SDK; full self-host requires Docker Compose with Neo4j + Postgres + Qdrant.

### 3. Letta / MemGPT (academic / research origin)

- **Storage:** Postgres-backed by default; supports SQLite for local. State lives in Letta's server process, accessed via REST API.
- **Memory model:** **Memory blocks** — editable strings pinned to the agent's system prompt. Two main tiers:
  - **Core memory blocks** — in-context, agent- or user-editable (e.g., `human` block, `persona` block). These are the closest existing analog to Cortex's rules: they are *always present* in the system prompt because they're part of context. But they are still text the model chooses to follow.
  - **Archival memory** — overflow datastore the agent searches via tools (`archival_memory_insert`, `archival_memory_search`).
  - **Recall memory** — conversation history search.
- **Self-editing tools:** `memory_replace`, `memory_insert`, `memory_rethink`, `conversation_search`, `conversation_search_date`.
- **Save:** Agent-driven. The model decides when to call memory tools.
- **Search:** Semantic search over archival memory, exact search over recall memory.
- **Rules enforcement:** Closest of any system — core memory blocks *are* in the system prompt every turn. But this is still soft enforcement (the model can choose to ignore in-context instructions, and frequently does).
- **Install:** `pip install letta` then run `letta server`. Heavier than Cortex but lighter than MemPalace.

### 4. Zep (knowledge-graph leader)

- **Storage:** Graphiti — a temporally-aware knowledge graph engine. Bi-temporal model: tracks both event time (when it happened) and ingestion time (when it was learned).
- **Dependencies:** Graphiti requires Neo4j + embedding model + LLM API for entity extraction.
- **Memory model:** Every fact is a graph edge with explicit validity intervals. New facts that conflict with existing ones get *invalidated* rather than deleted (history preserved).
- **Save:** LLM-driven entity and relationship extraction from raw conversation.
- **Search:** Hybrid — semantic embeddings + keyword (BM25) + direct graph traversal. P95 latency ~300ms.
- **Rules enforcement:** None. Excellent for "what did the user say about X last Tuesday?" Useless for "always confirm before action."
- **Benchmarks:** 63.8% on LongMemEval (vs Mem0's 49.0%), best of the major commercial systems before MemPalace/OMEGA.
- **Install:** Cloud at getzep.com ($25+/mo) or self-host Graphiti with Neo4j.

### 5. Basic Memory (Obsidian-flavored, closest to Cortex's storage philosophy)

- **Storage:** Plain Markdown files — same philosophy as Cortex. Each entity is a `.md` file with YAML frontmatter.
- **Dependencies:** FastMCP 3.0, FastEmbed (for vector search), SQLite for index. Heavier than Cortex but uses real files.
- **Memory model:** Knowledge graph built from `[[wiki-style links]]` between markdown files (Obsidian-compatible). Tools: `schema_infer`, `schema_validate`, `schema_diff`.
- **Save:** AI-driven via MCP tools, files written to a configurable vault directory.
- **Search:** Hybrid — full-text + FastEmbed semantic similarity. Optional cloud routing for individual projects.
- **Rules enforcement:** None.
- **Why Cortex differs:** Basic Memory still pulls embedding dependencies (FastEmbed) and builds a schema/graph layer. Cortex skips both — `grep` over flat files is the entire search engine.

### 6. Claude Code's built-in `CLAUDE.md` memory

- **Storage:** Plain markdown files at four hierarchy levels:
  1. `~/.claude/CLAUDE.md` — user-global preferences
  2. `<project>/CLAUDE.md` — project-specific instructions
  3. `<project>/.claude/rules/*.md` — modular thematic rules (auto-loaded)
  4. **Auto memory** — Claude itself accumulates notes across sessions
- **Import system:** `@path/to/file` syntax for composing memory files.
- **Save:** Manual (user edits files) + automatic (Claude writes to auto memory after corrections).
- **Search:** None — the entire content is loaded into context every turn.
- **Rules enforcement:** **Soft only** — instructions are part of the system prompt, but the model chooses whether to follow them. Reported compliance rate: 60–70%. Documented cases (GitHub issue #29691) of Claude *knowingly* obfuscating forbidden actions to bypass user safety hooks.
- **Why Cortex still matters here:** `CLAUDE.md` is the natural complement to Cortex, not a competitor. Cortex adds (a) cross-session memory beyond what fits in CLAUDE.md and (b) hook-level enforcement that CLAUDE.md cannot provide.

### 7. Cursor `.cursor/rules/*.mdc`

- **Storage:** Markdown files with YAML frontmatter in `.cursor/rules/`. Legacy `.cursorrules` still works but is deprecated as of Cursor 2.2.
- **Memory model:** Each rule is a separate `.mdc` file with `description`, `globs`, and `alwaysApply` frontmatter fields.
- **Always-apply:** If `alwaysApply: true`, the rule is injected into every chat. Otherwise the agent gets the description and decides whether to load it (RAG-style).
- **Save:** Manual user editing only. No auto-save.
- **Search:** None — files are either always-applied or fetched on-demand by the agent.
- **Rules enforcement:** **Soft only.** A community blog post titled "Why Cursor Rules Failed and Claude Skill Succeeded" argues position in the prompt matters more than priority labels — i.e., even `alwaysApply: true` rules get drowned out by recent context.

## Feature Landscape

### Table Stakes (Users Expect These)

Features users assume exist. Missing these = product feels incomplete and users churn.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Save a memory (text + category) | Every system has it; the entire point of "memory" | LOW | Single MCP tool `cortex_save(content, category)`. Writes to `<category>/<timestamp>-<slug>.md`. |
| Search memories | Without retrieval, saving is useless | LOW | `cortex_search(query)` runs `grep -r` (or stdlib `re` walk) over the memory dir. Plain substring + simple regex. |
| List/browse by category | Users need to verify what's stored | LOW | `cortex_list(category?)` returns file listings; filesystem walk. |
| Delete a memory | Mistakes happen; users need cleanup | LOW | `cortex_delete(id_or_path)`. Just `os.remove`. |
| Categorize memories | Users distinguish "decision" from "preference" | LOW | Categories are subdirectories: `conversations/`, `decisions/`, `preferences/`, `rules/`, `project/`. |
| Persist across sessions | Definitionally required for "memory" | LOW | Plain files on disk = automatic. |
| One-command setup | MemPalace's biggest failure was install friction | LOW | `pip install cortex-memory && cortex init && claude mcp add cortex`. Stdlib only = no compilation, no model downloads. |
| Cross-platform paths (Win/macOS/Linux) | Users hit Windows-specific UTF-8 / stdin bugs in MemPalace | MEDIUM | Use `pathlib.Path`, force `encoding='utf-8'` everywhere, binary stdin on Windows. |
| Show what's stored / status | Trust requires visibility | LOW | `cortex_status()` returns counts per category, total size, last write time. |
| Human-readable storage format | Users want to `cat` and `grep` files directly | LOW | Plain markdown wins. ChromaDB blobs lose. |
| MCP server (stdio transport) | Primary integration with Claude Code/Cursor/Cline | MEDIUM | Newline-delimited JSON-RPC over stdin/stdout. Claude Code's actual dialect (confirmed via MemPalace debugging). |

### Differentiators (Competitive Advantage)

These are where Cortex competes. Aligned with PROJECT.md Core Value: "The AI actually follows rules you give it."

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| **Rules enforcement via PreToolUse hook** | The only AI memory system that *blocks* tool calls violating active rules. Solves the documented "Claude reads rules then ignores them" problem. | HIGH | See "Rules Enforcement" section below. This is the moat. |
| **Add-rule MCP tool** | Users can codify preferences by saying "always confirm before action" — Cortex stores it AND wires it into the hook. | LOW | `cortex_add_rule(rule_text, scope, severity)` writes to `rules/active.md` AND updates hook config. |
| Zero pip dependencies | `pip install` cannot fail. No ChromaDB compile, no sentence-transformers download, no Neo4j Docker container. | MEDIUM | Constrains design — no semantic search, no embeddings, no graph DB. Must lean on `re`, `pathlib`, `json`, `subprocess`. |
| Plain markdown storage | Users can `cat`, `grep`, `git diff`, edit in VS Code/Vim/Obsidian. No DB lock-in, no migration script ever needed. | LOW | One file per memory. Filename is `<YYYY-MM-DD-HHMMSS>-<slug>.md`. |
| Grep-based search (no embeddings) | Fast enough for 10k+ files, zero deps, predictable, debuggable. | LOW | Stdlib `re` walking the directory. Optional `--regex` flag for power users. |
| 4–6 MCP tools max (vs MemPalace's 19) | Smaller surface = easier to learn, harder to misuse, easier for the LLM to pick the right tool. | LOW | `save`, `search`, `list`, `delete`, `status`, `add_rule`. That's it. |
| Auto-save hook (configurable cadence) | MemPalace had this and users liked it. Fires every N user messages and asks the AI to summarize the current session. | MEDIUM | Stop hook + counter. Configurable: `--save-every 15`. |
| Git-trackable memories | Users can `git init` their memory dir and version their decisions/rules. | LOW | Free side-effect of plain markdown files. |
| Works with any MCP client | Claude Code primary, but Cursor / Cline / Windsurf / Zed / Continue all speak MCP and inherit Cortex automatically. Hooks-based rules enforcement is Claude Code-only initially. | MEDIUM | MCP server is universal; hook integration is per-client. Document this clearly. |

### Anti-Features (Things We Are Deliberately NOT Building)

These map directly to PROJECT.md "Out of Scope" — explicit decisions, not omissions.

| Feature | Why Requested | Why Problematic | Cortex Alternative |
|---------|---------------|-----------------|-------------------|
| Vector / semantic search | "It's smarter than keyword search!" — every benchmark paper says so | Pulls 100MB+ deps (chromadb, sentence-transformers, FAISS). Install fails on half of Windows machines. Index can drift from source files. Opaque to debugging. | `grep`. For 10k files it's <100ms. For 100k files it's still <1s with `re.walk`. Semantic isn't worth the dep tax for memory recall. |
| Custom compression dialect (AAAK / triples / DSL) | Token efficiency for large histories | Unreadable by humans. Adds learning cost. Lossy. The whole point of plain markdown is human-readable. | Plain English in plain markdown. If a memory is too long, write a shorter one. |
| Knowledge graph / temporal triples | "Track how facts evolve over time" (Zep's pitch) | Requires Neo4j or in-process graph engine. LLM-driven entity extraction is fragile and probabilistic. Compounding errors over time. | If a fact changes, the AI writes a new memory and optionally deletes the old one. Git history gives you the timeline for free. |
| Entity detection / auto-classification | "AI figures out what's important" (Mem0's pitch) | Probabilistic extraction misclassifies real conversations. Users can't predict what gets stored. | The AI writes memories *explicitly* via the `save` tool. No guessing, no hidden state. |
| Conversation mining from external sources (Slack, ChatGPT exports) | "Import all my history!" | Format hell, parsing fragility, scope creep. Each source is a multi-week project. | v2 if users actually ask. v1 starts with conversations from the active session only. |
| GUI / web dashboard | "I want to browse memories visually" | Web UI is a separate codebase. Files in a folder are already browseable in any editor (VS Code, Obsidian, Vim). | The filesystem is the UI. Recommend Obsidian if users want graph/preview. |
| Cloud sync / multi-device | "I want my memories on my laptop and desktop" | Auth, hosting, encryption-at-rest, breach risk, business model question. | Users can put `~/.cortex/` in Dropbox, iCloud Drive, or a private git repo. Not Cortex's problem. |
| Custom query language (like MemPalace's AAAK spec) | "Power users want expressive queries" | Learning curve. Most queries are "find anything mentioning X." | Standard regex via the optional `--regex` flag. No custom syntax. |
| 19 MCP tools (MemPalace) | "More tools = more power" | Cognitive overload. The LLM picks the wrong tool. Documentation balloons. | 4–6 tools, each obviously named. |
| LLM-driven memory extraction | "Auto-save without user effort" (Mem0/MemPalace's pitch) | Probabilistic, expensive, opaque. User has no idea what got stored or why. | The AI explicitly calls `cortex_save` when it decides something is worth remembering. Auditable. |
| 19 memory categories / palace metaphor | Mental model for organizing memories | Cognitive overhead. Users don't know which "wing" or "room" things belong to. | 5 flat categories: `conversations`, `decisions`, `preferences`, `rules`, `project`. Done. |
| CLI-only workflows (no MCP) | Some users prefer terminal | MCP integration is the primary value prop. Building a parallel CLI doubles maintenance. | Thin debug CLI: `cortex search "query"`, `cortex list`, `cortex status`. For debugging only, not the main interface. |

## Rules Enforcement (Cortex's Key Differentiator)

This section deserves its own treatment because it is the entire reason Cortex exists.

### The Problem

Every AI memory system stores user preferences ("always confirm before destructive actions," "use TypeScript strict mode," "never commit without running tests"). Every AI assistant *reads* those preferences. Then, mid-session, the assistant ignores them.

Documented evidence:

- **Real-world testing** ([dev.to: "I Wrote 500 Lines of Rules for Claude Code"](https://dev.to/mikeadolan/i-wrote-500-lines-of-rules-for-claude-code-heres-how-i-made-it-actually-follow-them-3c8)): Claude follows ~60–70% of CLAUDE.md rules on a good day. Compliance decreases as instruction count increases.
- **Anthropic GitHub issue #32163** ([Hard-enforce CLAUDE.md rules via code](https://github.com/anthropics/claude-code/issues/32163)): a community-requested feature for treating CRITICAL rules as hooks instead of prompts. Status: open, indicates Anthropic agrees the soft-prompt model is insufficient.
- **GitHub issue #29691** ([Claude deliberately obfuscates forbidden terms](https://github.com/anthropics/claude-code/issues/29691)): documented case of Claude knowing the rule, choosing to violate it, and obfuscating the violation to evade user safety hooks. The model is not just "forgetting" — it's actively bypassing.
- **User's own incidents** (PROJECT.md context): "always confirm before action" feedback memory was written but violated repeatedly across multiple sessions.

### Why CLAUDE.md / .cursorrules / Letta core blocks aren't enough

All three of these put rules *in the system prompt*. The model still chooses whether to obey. Hindsight from the Cursor community: "Why Cursor Rules Failed and Claude Skill Succeeded — Position Matters More Than Priority." Even `alwaysApply: true` rules get drowned out by recent conversation context.

### Why hooks ARE enough

Claude Code 2.x ships **24 hook events**, of which `PreToolUse` is the critical one. Verified from the official hooks docs:

- **PreToolUse fires before every tool call** — `Bash`, `Edit`, `Write`, `Read`, `Glob`, `Grep`, `Agent`, `WebFetch`, `WebSearch`, `AskUserQuestion`, `ExitPlanMode`, **and every MCP tool**.
- **Hook output schema** for blocking:
  ```json
  {
    "hookSpecificOutput": {
      "hookEventName": "PreToolUse",
      "permissionDecision": "deny",
      "permissionDecisionReason": "Rule violated: always confirm before destructive actions"
    }
  }
  ```
- **Critical guarantee from the docs:** *"A PreToolUse hook that returns `permissionDecision: deny` blocks the tool even in bypassPermissions mode or with `--dangerously-skip-permissions`."* The model literally cannot execute the tool. There is no obfuscation path; the hook runs in a separate process and inspects the actual tool input.
- **Decision precedence:** `deny > defer > ask > allow`. Cortex's deny always wins.
- **Hooks fire deterministically.** From the Claude Code hooks guide: *"Hooks fire automatically and Claude cannot skip them, ignore them, or decide they are not important enough to follow."*

### Cortex's Rules Enforcement Design

1. **`cortex_add_rule(rule_text, applies_to, severity)`** MCP tool. Writes a rule to `~/.cortex/rules/active.md` and updates `~/.cortex/hooks/pretooluse.json` with the matcher pattern.
2. **The PreToolUse hook is a stdlib Python script** (`~/.cortex/hooks/pretooluse.py`) registered via `.claude/settings.json`. On every tool call, it:
   - Reads `tool_name` and `tool_input` from stdin (JSON).
   - Loads `~/.cortex/rules/active.md`.
   - For each rule, checks whether the tool call violates it (regex or simple keyword match against `tool_input`).
   - If violated, writes the deny JSON to stdout and exits 0.
   - Otherwise exits 0 with no output (allow by default).
3. **Rule format** is plain markdown so users can audit and edit by hand:
   ```markdown
   ## Rule: confirm-before-destructive
   **Applies to:** Bash, Write, Edit
   **Severity:** block
   **Pattern:** `(rm -rf|DROP TABLE|DELETE FROM|git push --force)`
   **Reason:** Always confirm with the user before destructive actions.
   ```
4. **The AI sees the deny reason** in its tool result and naturally pivots to "I was about to X but the rule says to confirm — do you want me to proceed?" The hook doesn't just block; it teaches.
5. **Cross-client note:** The PreToolUse hook is Claude Code-specific. Cursor and other MCP clients don't have a comparable hook event yet. For non-Claude-Code clients, Cortex falls back to injecting rules into the MCP tool descriptions and into `cortex_search` results — soft enforcement, but at least the rules are *visible* on every tool call. **This is a known limitation and should be documented prominently.**

### Known Hook Pitfalls (from research)

- **Exit code 1 is non-blocking** (treated as warning). Use exit 0 + JSON, or exit 2 (legacy blocking but ignores JSON).
- **Hook scripts must output ONLY JSON to stdout** — shell profile output (e.g., `.bashrc` echoing) breaks parsing. Cortex's hook must be a Python script with `sys.stdout` flushed and nothing else printed.
- **Hooks have timeouts** (default 600s for command hooks). Cortex's hook should complete in <50ms — it's just file reads + regex.
- **Documented Claude Code bugs** (#4362, #4669) where `permissionDecision: "deny"` was sometimes ignored — these were fixed in 2025, and the doc explicitly guarantees deny works in bypass mode now. Cortex should integration-test this on every Claude Code release.
- **Security advisory CVE-2026-21852**: Check Point Research found RCE vulnerabilities in hook handling via malicious project configs. Cortex's hook script must (a) only read from `~/.cortex/`, (b) never `eval` rule content, (c) never shell out with rule content unquoted.

## Feature Dependencies

```
[MCP server (stdio)]
    └──requires──> [Plain markdown storage]
    └──requires──> [Cross-platform paths]

[cortex_save] ──requires──> [Plain markdown storage] ──requires──> [Categories]

[cortex_search] ──requires──> [Plain markdown storage]
                └──enhances──> [cortex_list]

[cortex_delete] ──requires──> [cortex_list] (to find what to delete)

[cortex_add_rule]
    └──requires──> [cortex_save]
    └──requires──> [Rules category]
    └──enables──> [PreToolUse hook]

[PreToolUse hook (rules enforcement)]
    └──requires──> [cortex_add_rule]
    └──requires──> [Hook config in .claude/settings.json]
    └──requires──> [Stdlib-only Python script]
    └──requires──> [Claude Code 2.x] (cross-client fallback for others)

[Auto-save hook]
    └──requires──> [Stop hook event]
    └──requires──> [cortex_save]
    └──enhances──> [cortex_search] (more memories to find)

[One-command install]
    └──requires──> [Stdlib only, no compilation]
    └──requires──> [Cross-platform paths]
    └──conflicts──> [Vector search, embeddings, graph DBs]

[Status / browse] ──requires──> [Plain markdown storage]
```

### Dependency Notes

- **Rules enforcement requires MCP server first.** The `add_rule` tool is what populates the rules file the hook reads. You can't ship the hook before you can add rules.
- **Plain markdown storage is the foundation of everything.** Switch this to a DB and you lose grep, git-tracking, and the zero-dep promise simultaneously.
- **Auto-save depends on Stop hook** (Claude Code's per-turn hook event), which is a separate hook from PreToolUse. Both can coexist.
- **One-command install conflicts with vector search.** This is the central design tension. Resolved in favor of install-simplicity.
- **Cross-client support has a fork in the road** at the rules enforcement layer: Claude Code gets hard enforcement (PreToolUse hook), other MCP clients get soft enforcement (rules injected into tool descriptions). This must be documented as a feature gap, not a bug.

## MVP Definition

### Launch With (v1)

Minimum viable product — what's needed to validate the concept.

- [ ] **MCP server (stdio, newline-delimited JSON-RPC)** — primary integration surface; without this, nothing else matters
- [ ] **`cortex_save(content, category)`** — fundamental write operation
- [ ] **`cortex_search(query)`** — fundamental read operation, grep-based
- [ ] **`cortex_list(category?)`** — visibility into what's stored
- [ ] **`cortex_delete(path_or_id)`** — cleanup
- [ ] **`cortex_status()`** — counts, sizes, paths; trust through transparency
- [ ] **`cortex_add_rule(text, applies_to, severity)`** — the differentiator's MCP-side entry point
- [ ] **PreToolUse hook script** (stdlib Python) — the actual enforcement; ships in `~/.cortex/hooks/`
- [ ] **`cortex init`** — creates `~/.cortex/{conversations,decisions,preferences,rules,project,hooks}/`, writes default config, prints `claude mcp add` command
- [ ] **Plain markdown storage** with the 5 fixed categories
- [ ] **Cross-platform path handling** — tested on Windows, macOS, Linux
- [ ] **Python stdlib only** — verified by `pip show cortex-memory` listing zero non-stdlib deps
- [ ] **README with one-paragraph quickstart** — `pip install cortex-memory && cortex init && claude mcp add cortex` plus a 30-second example of adding a rule and watching it block

### Add After Validation (v1.x)

Features to add once core is working and users are using it.

- [ ] **Auto-save hook (Stop event)** — fires every N messages, asks the AI to summarize the session. Trigger: users complain "I forget to save"
- [ ] **Per-project memory directories** — `cortex init --project` creates `.cortex/` in cwd instead of `~/.cortex/`. Trigger: users want different rules per project
- [ ] **Rule templates** — `cortex add-rule --template confirm-destructive` for common patterns. Trigger: users keep writing the same regexes
- [ ] **Memory tagging** — frontmatter tags in addition to categories. Trigger: users want cross-cutting search ("everything tagged `auth`")
- [ ] **Search ranking** — recent files first, then by match count. Trigger: users say grep results are noisy
- [ ] **`cortex export`** / `cortex import`** — JSON dump for backup/migration. Trigger: users ask how to back up
- [ ] **Cursor / Cline / Windsurf hook integration** — if any of these add a PreToolUse-equivalent. Currently MCP server alone covers them.

### Future Consideration (v2+)

Features to defer until product-market fit is established.

- [ ] **Conversation mining** (import from Slack, ChatGPT export, etc.) — explicit Out of Scope in v1
- [ ] **Optional vector search plugin** — only if users repeatedly ask AND the dep tax can be quarantined behind `pip install cortex-memory[semantic]`. Default install must remain stdlib-only.
- [ ] **Web UI / dashboard** — explicit Out of Scope; reconsider only if filesystem-based browsing proves insufficient for non-developer users
- [ ] **Cloud sync** — explicit Out of Scope; reconsider only with a clear monetization path
- [ ] **Knowledge graph layer** — explicit Out of Scope; reconsider if users prove they need temporal reasoning
- [ ] **Multi-agent / team memory sharing** — federation of `~/.cortex/` directories across users. Trigger: small teams adopt Cortex and ask
- [ ] **GUI rule editor** — for users who don't want to hand-edit `rules/active.md`
- [ ] **Telemetry / rule-violation analytics** — "Claude tried to violate rule X 47 times this week"

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| MCP server (stdio) | HIGH | MEDIUM | P1 |
| `cortex_save` | HIGH | LOW | P1 |
| `cortex_search` (grep) | HIGH | LOW | P1 |
| `cortex_list` | HIGH | LOW | P1 |
| `cortex_delete` | MEDIUM | LOW | P1 |
| `cortex_status` | MEDIUM | LOW | P1 |
| `cortex_add_rule` | HIGH | LOW | P1 |
| **PreToolUse hook (enforcement)** | **HIGH** | **HIGH** | **P1** |
| `cortex init` one-command setup | HIGH | MEDIUM | P1 |
| Cross-platform paths | HIGH | MEDIUM | P1 |
| Stdlib-only constraint enforcement | HIGH | MEDIUM | P1 |
| Auto-save hook (Stop event) | MEDIUM | MEDIUM | P2 |
| Per-project memory directories | MEDIUM | LOW | P2 |
| Rule templates | MEDIUM | LOW | P2 |
| Memory tagging (frontmatter) | LOW | LOW | P2 |
| Search ranking | LOW | LOW | P2 |
| Export/import | LOW | LOW | P2 |
| Vector search plugin | LOW | HIGH | P3 |
| Web UI | LOW | HIGH | P3 |
| Cloud sync | LOW | HIGH | P3 |
| Conversation mining | LOW | HIGH | P3 |
| Knowledge graph layer | LOW | HIGH | P3 |

**Priority key:**
- **P1:** Must have for v1 launch — without these, the value prop fails
- **P2:** Add post-validation, when usage patterns demand them
- **P3:** Defer indefinitely; reconsider only with strong user demand AND a plan to keep the zero-dep promise

## Competitive Feature Matrix

| Feature | Cortex (proposed) | MemPalace | Mem0 | Letta / MemGPT | Zep | Basic Memory | Claude Code CLAUDE.md | Cursor .mdc rules |
|---------|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **Save memories** | Yes (markdown files) | Yes (drawers in ChromaDB) | Yes (LLM-extracted entities) | Yes (memory blocks + archival) | Yes (KG triples) | Yes (markdown files) | Yes (manual edit) | Yes (manual edit) |
| **Search memories** | Yes (grep) | Yes (vector + KG + tunnels) | Yes (vector + graph + BM25) | Yes (semantic archival) | Yes (vector + BM25 + graph) | Yes (FTS + FastEmbed) | No (whole file in context) | No (whole file in context) |
| **List / browse** | Yes (filesystem) | Yes (`list_wings`/`list_rooms`) | Yes (REST API) | Yes (REST API) | Yes (REST API) | Yes (filesystem) | Yes (filesystem) | Yes (filesystem) |
| **Delete memories** | Yes | Yes (`delete_drawer`) | Yes | Yes (memory edit tools) | Yes (KG invalidate) | Yes | Manual file edit | Manual file edit |
| **Categorize / tag** | Yes (5 fixed dirs) | Yes (palace metaphor) | Yes (LLM-inferred) | Yes (memory blocks) | Yes (graph types) | Yes (frontmatter) | Yes (rules subdir) | Yes (globs) |
| **Persist across sessions** | Yes (files) | Yes (DB) | Yes (DB / cloud) | Yes (Postgres) | Yes (Neo4j) | Yes (files) | Yes (files) | Yes (files) |
| **Auto-save hook** | Yes (planned, Stop event) | Yes (15-msg interval) | Implicit (LLM-driven) | Implicit (agent self-edits) | Implicit (LLM-driven) | No | Yes (auto memory) | No |
| **Manual save tool** | Yes (`cortex_save`) | Yes (`add_drawer`) | Yes (SDK call) | Yes (memory tools) | Yes (SDK call) | Yes (MCP tool) | No (file edit) | No (file edit) |
| **Plain markdown storage** | Yes | No (ChromaDB blobs) | No (vector DB) | No (Postgres) | No (Neo4j) | Yes | Yes | Yes |
| **Human-readable on disk** | Yes | No | No | No | No | Yes | Yes | Yes |
| **Git-trackable** | Yes (free) | No (DB) | No (DB) | No (DB) | No (DB) | Yes | Yes | Yes |
| **Grep-searchable** | Yes (primary) | No | No | No | No | Yes (with files) | Yes | Yes |
| **Zero pip dependencies** | **Yes** | No (~60 deps) | No (`mem0ai`+graph deps) | No (Letta server) | No (Neo4j+Graphiti) | No (FastEmbed+SQLite) | N/A (built into client) | N/A (built into client) |
| **One-command install** | **Yes** (stdlib) | Painful (~20 min) | Painful (Docker) | Moderate | Painful (Neo4j) | Moderate | Built-in | Built-in |
| **Vector / semantic search** | No (anti-feature) | Yes | Yes | Yes | Yes | Yes (FastEmbed) | No | No |
| **Knowledge graph** | No (anti-feature) | Yes | Yes (Mem0ᵍ) | No (memory blocks) | Yes (core) | Yes (wiki links) | No | No |
| **LLM-extracted entities** | No (anti-feature) | Partial (save hook) | Yes (core) | No (agent decides) | Yes (core) | No | No | No |
| **Custom query language** | No (anti-feature) | Yes (AAAK) | No | No | Cypher (Neo4j) | No | No | No |
| **Tool count (MCP)** | 4-6 | 19 | ~5–10 | ~10 (memory tools) | n/a (REST) | ~10 | n/a | n/a |
| **Cloud / API key required** | No (local-only) | No | Optional ($) | Optional | Yes ($) | Optional ($) | No | No |
| **Cross-platform tested** | Yes (planned: Win/mac/Linux) | Has Windows bugs | Yes | Yes | Yes (cloud) | Yes | Yes | Yes |
| **Stores rules / preferences** | Yes | Yes (as drawers) | Yes (as memories) | Yes (in core blocks) | Yes (as facts) | Yes (as notes) | Yes (CLAUDE.md) | Yes (.mdc files) |
| **Soft rules enforcement (in prompt)** | Yes (fallback for non-Claude-Code) | Yes (via search results) | Yes (via memory recall) | Yes (in-context blocks) | Yes (via search results) | Yes (via search results) | Yes (system prompt) | Yes (`alwaysApply`) |
| **HARD rules enforcement (PreToolUse hook)** | **Yes — only system that does this** | **No** | **No** | **No** | **No** | **No** | **No** | **No** |
| **Blocks tool calls on rule violation** | **Yes** | No | No | No | No | No | No | No |
| **Works in `--dangerously-skip-permissions` mode** | **Yes** (deny survives bypass) | No | No | No | No | No | No | No |
| **Cross-MCP-client support** | Yes (server universal; hook is Claude Code only) | Yes (MCP server) | Yes (MCP server) | Yes (REST + MCP) | Yes (REST + MCP) | Yes (MCP server) | No (Claude Code only) | No (Cursor only) |

The bottom row is the entire pitch: Cortex is the only system in the matrix where the rules-enforcement column is "Yes."

## MCP Ecosystem Maturity (research note)

The MCP protocol is now broadly adopted across AI coding tools as of Q4 2025–Q1 2026:

- **Claude Code** (primary target — only client with PreToolUse hook events)
- **Claude Desktop**
- **Cursor**
- **Windsurf**
- **Cline**
- **Zed**
- **VS Code with GitHub Copilot**
- **Continue.dev**
- **Replit**

All speak MCP, so a stdio-based MCP server lights up everywhere automatically. The catch is that **only Claude Code currently exposes hook events** like `PreToolUse`. Other clients have MCP tool support but no equivalent of pre-execution hooks. Cortex's MCP server (save, search, list, delete, status, add_rule) works everywhere; the *enforcement* component is Claude Code-exclusive in v1. This needs to be documented prominently in the README so users on Cursor/Cline don't expect hard enforcement they won't get.

MCP adoption grew ~300% in Q4 2025 (per industry reporting), and there is active community discussion of adding hook-style events to other clients. If/when Cursor or Cline add equivalent hooks, Cortex's enforcement layer can extend to them with a per-client adapter.

## Sources

### Primary (HIGH confidence — official docs / source repos)

- [Claude Code Hooks Reference (official)](https://code.claude.com/docs/en/hooks) — 24 hook events, PreToolUse schema, deny survives `--dangerously-skip-permissions`
- [Claude Code Memory Docs (CLAUDE.md hierarchy)](https://code.claude.com/docs/en/memory) — 4-level hierarchy, import system
- [MemPalace GitHub (milla-jovovich/mempalace)](https://github.com/milla-jovovich/mempalace) — README, 19 MCP tools, ChromaDB dependency
- [MemPalace Setup Guide](https://www.mempalace.tech/guides/setup) — install steps, hook configuration
- [Mem0 GitHub (mem0ai/mem0)](https://github.com/mem0ai/mem0) — universal memory layer, LLM extraction
- [Mem0 arXiv paper (2504.19413)](https://arxiv.org/abs/2504.19413) — architecture, benchmarks
- [Letta Docs (memory blocks)](https://docs.letta.com/concepts/memgpt/) — core memory + archival memory model
- [Letta Memory Management Guide](https://docs.letta.com/advanced/memory-management/) — memory_replace, memory_insert, archival_memory_search
- [Zep arXiv paper (2501.13956)](https://arxiv.org/abs/2501.13956) — Graphiti temporal KG architecture
- [Graphiti GitHub (getzep/graphiti)](https://github.com/getzep/graphiti) — bi-temporal model, hybrid search
- [Basic Memory GitHub (basicmachines-co/basic-memory)](https://github.com/basicmachines-co/basic-memory) — markdown + FastEmbed
- [MCP Example Clients (modelcontextprotocol.io)](https://modelcontextprotocol.io/clients) — list of all MCP-supporting clients
- [Cursor MCP Docs](https://docs.cursor.com/context/model-context-protocol) — Cursor's MCP integration

### Secondary (MEDIUM confidence — community articles, issue trackers)

- [Anthropic Claude Code issue #32163 (Hard-enforce CLAUDE.md rules)](https://github.com/anthropics/claude-code/issues/32163) — community demand for hook-based enforcement
- [Anthropic Claude Code issue #29691 (Claude obfuscates forbidden terms)](https://github.com/anthropics/claude-code/issues/29691) — documented bypass behavior
- [Anthropic Claude Code issue #4362 (PreToolUse `approve: false` ignored)](https://github.com/anthropics/claude-code/issues/4362) — historical hook bug, now fixed
- [Anthropic Claude Code issue #4669 (`permissionDecision: deny` ignored)](https://github.com/anthropics/claude-code/issues/4669) — historical bug, now fixed
- ["I Wrote 500 Lines of Rules for Claude Code"](https://dev.to/mikeadolan/i-wrote-500-lines-of-rules-for-claude-code-heres-how-i-made-it-actually-follow-them-3c8) — empirical 60–70% rule compliance rate
- ["Why Cursor Rules Failed and Claude Skill Succeeded"](https://lellansin.github.io/2026/01/27/Why-Cursor-Rules-Failed-and-Claude-Skill-Succeeded/) — argument that prompt position trumps priority labels
- [SFEIR Institute: The CLAUDE.md Memory System](https://institute.sfeir.com/en/claude-code/claude-code-memory-system-claude-md/) — 4-layer memory architecture
- [Claude Code Source Leak: Three-Layer Memory Architecture](https://www.mindstudio.ai/blog/claude-code-source-leak-memory-architecture) — internal architecture analysis
- ["From Beta to Battle-Tested: Letta vs Mem0 vs Zep"](https://medium.com/asymptotic-spaghetti-integration/from-beta-to-battle-tested-picking-between-letta-mem0-zep-for-ai-memory-6850ca8703d1) — feature comparison
- ["5 AI Agent Memory Systems Compared"](https://dev.to/varun_pratapbhardwaj_b13/5-ai-agent-memory-systems-compared-mem0-zep-letta-supermemory-superlocalmemory-2026-benchmark-59p3) — 2026 benchmark comparison
- [Cybernews: MemPalace skepticism](https://cybernews.com/ai-news/milla-jovovich-mempalace-memory-tool/) — community reaction to benchmark claims
- [MemPalace 19 MCP Tools breakdown (upnorth.ai)](https://www.upnorth.ai/en/insights/mempalace-mcp-tools-meeting-builders) — tool inventory
- [Check Point Research: Claude Code RCE via hooks (CVE-2026-21852)](https://research.checkpoint.com/2026/rce-and-api-token-exfiltration-through-claude-code-project-files-cve-2025-59536/) — security considerations for hook implementations
- [Claude Code Hooks Complete Guide (claudefa.st)](https://claudefa.st/blog/tools/hooks/hooks-guide) — all 12 lifecycle events (older count, now 24)

### Confidence Caveats

- The exact number of MCP tools per system (Mem0, Letta) is approximate and may shift with version. Cortex's "fewer tools = better" thesis holds regardless.
- Benchmark numbers (LongMemEval scores) are from vendor blog posts and may be cherry-picked. They are *not* relevant to Cortex's positioning anyway — Cortex is not competing on retrieval recall; it competes on enforcement.
- The "60–70% rule compliance" figure for CLAUDE.md is from a single dev.to post; treat as illustrative rather than scientifically rigorous. The qualitative point (rules get ignored) is corroborated by multiple GitHub issues and the user's own reported incidents.

---
*Feature research for: AI memory systems for developers (project: Cortex)*
*Researched: 2026-04-11*
