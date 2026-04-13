# Project Research Summary

**Project:** Sekha
**Domain:** Local-first AI memory system + MCP server + PreToolUse hook rules enforcement (Python stdlib only)
**Researched:** 2026-04-11
**Confidence:** HIGH

---

## Blockers — Resolve Before Phase 1

These are non-negotiable. The project cannot start coding until both are decided.

### BLOCKER 1: PyPI name — RESOLVED

**`sekha` is available on PyPI** (verified 2026-04-11). All variants (`sekha-ai`, `sekha-memory`, `sekha-cc`, `sekha-hook`, `sekha-rules`) are also free. Claiming the bare `sekha` — no suffix needed.

**Action needed:** Reserve `sekha` on PyPI with a v0.0.0 placeholder during Phase 0.

### BLOCKER 2: Python 3.9 minimum is wrong

PROJECT.md says "Python 3.9+." Python 3.9 reached **end-of-life in October 2025**.

**Recommendation:** **Bump the minimum to Python 3.11.** Rationale:

- 3.9 EOL → unsafe.
- 3.11 ships `tomllib` in stdlib (clean frontmatter alternative if YAML-subset proves brittle).
- 3.11 has a measurably faster interpreter cold-start — directly attacks the hook-latency budget.
- 3.11 ships on Ubuntu 23.10+, macOS via Homebrew, Windows Store, and `pyenv`.

Fall back to **3.10 minimum** only if broader compatibility is critical. Do **not** ship 3.9.

---

## Executive Summary

Sekha is a small, local-first product with a single high-value insight: **AI memory systems all store rules; none of them enforce them**. Every competitor (MemPalace, Mem0, Letta, Zep, Basic Memory, CLAUDE.md, Cursor `.mdc`) puts rules into the system prompt and trusts the model to comply. Real-world compliance sits at 60–70%, with documented cases of Claude Code knowingly bypassing rules. Claude Code 2.x ships a `PreToolUse` hook with a `permissionDecision: "deny"` output that **hard-blocks tool execution even in `--dangerously-skip-permissions` mode**. No shipping memory system uses it. That gap is Sekha's entire moat.

The recommended approach is opinionated and small: **Python stdlib only**, plain markdown files in `~/.sekha/`, ~2,000 LOC across three independent processes (long-lived MCP server, short-lived PreToolUse hook, one-shot CLI) that share state through the filesystem and never talk to each other directly. Build the libraries first (`storage`, `search`, `rules`), then the **hook before the server** so the differentiator can be dogfooded as early as Phase 4. Storage is plain markdown with a 5-folder taxonomy and a hand-rolled ~80-line frontmatter parser (no PyYAML). Search is `os.walk` + `re.compile` with term-frequency × recency scoring. The MCP server is ~200 LOC of newline-delimited JSON-RPC, the hook is another ~150 LOC, and the entire surface is six tools prefixed with `sekha_`.

The project's biggest risks are not technical complexity but **stealth operational footguns**: a PyPI name conflict (BLOCKER 1), an EOL Python version (BLOCKER 2), Python's 100–250ms cold-start on Windows turning the hook into the product killer, MCP stdio buffering bugs that silently hang Claude Code, Windows cp1252 encoding crashing `sekha init`, and rule false-positives blocking legitimate edits. Mitigations exist for every one of them but must be wired into specific phase exit criteria — particularly the **hook latency budget (<50ms p50, <150ms p95) enforced in CI**.

**One-line positioning:** *Sekha = MemPalace's value proposition at 1% of its complexity, plus the only AI memory system with hook-level rules enforcement that survives `--dangerously-skip-permissions`.*

---

## Key Findings

### Recommended Stack

**Python 3.11+, stdlib only, hatchling build backend, hand-written everything else.** The constraint is the strategy: every dependency is a potential install failure, and install failure is the documented cause of MemPalace's churn.

**Core technologies:**
- **Python 3.11+** — lowest safe version (3.9 EOL), ships `tomllib`, fastest cold-start.
- **`hatchling` via `pyproject.toml`** — build-time only, end users pull zero deps.
- **Newline-delimited JSON-RPC 2.0 over stdio** — MCP transport. NOT Content-Length framing.
- **Plain markdown files in `~/.sekha/`** — filenames are `YYYY-MM-DD_<id>_<slug>.md`.
- **`pathlib`, `re`, `json`, `argparse`, `unittest`** — total stdlib surface. `os.path` and `asyncio` banned.
- **`hatchling` `[project.scripts]` entry point** — generates `sekha` binary. Hook registered as `sekha hook run`, **never** as a shell script.

**Banned:** PyYAML, FastMCP, official `mcp` SDK, ChromaDB, NumPy, Pydantic, Click, Typer.

**CI matrix:** Windows + macOS + Linux × Python 3.11, 3.12, 3.13.

Full detail: [STACK.md](./STACK.md)

### Validated Differentiator

Claude Code's `PreToolUse` hook with `permissionDecision: "deny"` was **independently verified against the official hooks documentation**. The guarantee: *"A PreToolUse hook that returns `permissionDecision: deny` blocks the tool even in bypassPermissions mode or with `--dangerously-skip-permissions`."* Decision precedence is `deny > defer > ask > allow`.

The cross-client caveat: **PreToolUse hooks are Claude Code-only**. Cursor, Cline, Windsurf, Zed, and Continue will see the memory tools but only get soft enforcement.

### Expected Features

Full detail: [FEATURES.md](./FEATURES.md)

**Must have (table stakes):** save / search / list / delete / status, categorized storage, persist across sessions, one-command setup, cross-platform paths, MCP server, human-readable storage.

**Differentiators:** `sekha_add_rule` MCP tool, PreToolUse hook, zero pip dependencies, grep-based search, 4–6 tools max, git-trackable memories.

**Defer or skip:** auto-save hook (v1.x), per-project memory dirs, vector search (anti-feature), knowledge graphs (anti-feature), GUI dashboard (anti-feature), cloud sync (anti-feature).

### Architecture Approach

Full detail: [ARCHITECTURE.md](./ARCHITECTURE.md)

**Three independent processes that share state through `~/.sekha/`:**

1. **`sekha.server`** (long-lived, one per Claude Code session) — MCP stdio loop, ~200 LOC
2. **`sekha.hook`** (short-lived, one per tool call) — PreToolUse enforcement, ~150 LOC, **<50ms p50**
3. **`sekha.cli`** (one-shot) — `init`, `add-rule`, `doctor`, `list-rules`, ~150 LOC

**Shared libraries:**
- **`storage.py`** — atomic write, frontmatter parse/dump, filelock, `sekha_home()`
- **`search.py`** — `os.walk` + `re.compile` with scoring
- **`rules.py`** — load, parse, match, evaluate severity

**Patterns:** Filesystem as message bus. Thin entry points, fat libraries. Read-only hook (no lock contention). Fail open for perf, fail safe for correctness. Re-read don't cache. Grep-first data design.

**Build order:** storage → search → rules → **hook** → server → cli → packaging. **The hook ships before the server** — if the enforcement flow doesn't work on real Claude Code, we find out on day 7, not day 30.

### Critical Pitfalls

1. **PyPI name conflict** — BLOCKER, Phase 0.
2. **Hook cold-start latency** — BLOCKER, Phase 4 exit criterion. Budget: <50ms p50, <150ms p95 enforced in CI.
3. **MCP stdio framing + stdout pollution** — BLOCKER, Phase 5. Content-Length vs newline-delimited; stray `print()` corrupts channel; Windows text-mode mangles `\r\n`. Lint for `print(`, swap stdout→stderr at boot, force binary+UTF-8 on Windows.
4. **Hook decision JSON format** — BLOCKER, Phase 4. Correct: `{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": "..."}}`. Belt-and-suspenders (JSON + stderr + exit 2).
5. **False positives in rule enforcement** — MAJOR, Phase 3. Tool-scoped, anchored regex by default, `sekha rule test` dry-run, temp override via env var.

**Hook failure policy:** Fail open with loud warning to stderr. Top-level try/except. Log to `~/.sekha/hook-errors.log`. Kill switch: 3+ consecutive errors auto-disable.

Full detail: [PITFALLS.md](./PITFALLS.md)

---

## Implications for Roadmap

### Suggested Phases

**Phase 0 — Project setup and naming (gate phase, no code)**
Resolve PyPI name + Python 3.11 minimum. Reserve name with v0.0.0 placeholder. `pyproject.toml` skeleton. CI matrix scaffold. README skeleton.

**Phase 1 — Library foundation (`storage`, `paths`, `logutil`)**
Atomic write, filelock, frontmatter parse/dump, `sekha_home()`. Unit tests including 100-parallel-write stress test. Lint banning `os.path` and bare `print(`.

**Phase 2 — Search (`sekha.search`)**
TF × recency × filename scoring. Regex timeout guard (ReDoS prevention). 10k-file benchmark (p95 < 500ms).

**Phase 3 — Rules engine (`sekha.rules`)**
Rule class, strict parser, tool-scoped matching, precedence (deny wins), compile cache.

**Phase 4 — PreToolUse hook (`sekha.hook`) — THE DIFFERENTIATOR**
Fail-open policy, lazy imports (<30ms), compiled rules cache, `sekha hook bench`. **CI gate: p50 <50ms, p95 <150ms on all three OSes.** Manual integration test: "install block-all-Bash rule, attempt tool, assert blocked."
**Phase exit criterion:** "I have personally been blocked by a Sekha rule and appreciated it."

**Phase 5 — MCP server (`server`, `tools`, `jsonrpc`, `schemas`)**
6 tools prefixed `sekha_`. Stdio hardening (stdout→stderr swap, binary mode, UTF-8 on Windows). Test harness with scripted JSON-RPC sequences.

**Phase 6 — CLI and install experience**
`sekha init`, `sekha doctor`, ASCII output only (cp1252 safe). Tested on fresh VMs of Windows, macOS, Linux.

**Phase 7 — Polish, docs, release v0.1.0**
README with demo, threat model, example rules library, contribution guide, PyPI publish.

### What to Build First

After Phase 0 (naming + Python version), the **first file to write is `sekha/storage.py`**, and the first function is `atomic_write(path, content)`. That's Phase 1. Zero user-visible value but the bedrock — every downstream component breaks if storage has bugs.

### Research Flags

**Needs research during planning:**
- **Phase 4** — validate hook import-time budget on Windows VM before committing
- **Phase 5** — re-verify MCP spec version + hook schema against live Claude Code

**Standard patterns (skip research):** Phases 0, 1, 2, 3, 6, 7

---

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | **HIGH** | Verified against MCP spec, Claude Code hook docs, MemPalace behavior. |
| Features | **HIGH** | Competitor profiles verified. Rules-enforcement gap documented in real-world testing. |
| Architecture | **HIGH** | Three-process / shared-filesystem is well-understood. Search perf is MEDIUM — must benchmark Phase 2. |
| Pitfalls | **HIGH** | Most verified against MemPalace first-hand, MCP spec, Claude Code docs. |

**Overall confidence:** **HIGH**, conditional on resolving the two Phase 0 blockers.

### Gaps to Address

- Real PyPI name not yet chosen (Phase 0 blocker)
- Hook cold-start latency on Windows theoretically tight (Phase 4 empirical validation)
- Search 10k-file performance is extrapolation (Phase 2 benchmark)
- Claude Code hook schema stability across releases (integration-test on every release)
- Cross-MCP-client enforcement gap (must document prominently)
- Threat model under-specification (README must call out "consistency enforcer, not security sandbox")

---

## Sources

### Primary (HIGH confidence)
- Claude Code Hooks Reference (official)
- Claude Code MCP integration docs
- Model Context Protocol spec 2025-11-25
- Python stdlib reference (3.11)
- PEP 621 + hatchling docs
- MemPalace source and direct debugging experience
- Anthropic GitHub issues #29691, #32163
- PyPI registry verification (2026-04-11)

### Secondary (MEDIUM confidence)
- Mem0, Letta/MemGPT, Zep, Basic Memory docs and repos
- dev.to empirical rule compliance studies
- modelcontextprotocol/python-sdk issue #552 (Windows asyncio hang)

### Tertiary (LOW confidence, needs validation)
- Search perf estimates for 10k-file pure-Python regex scan (~200–400ms warm)
- Hook cold-start budget (<100ms with lazy imports)

---

*Research completed: 2026-04-11*
*Ready for roadmap: yes, conditional on Phase 0 blocker resolution*
