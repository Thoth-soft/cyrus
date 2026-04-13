# Phase 3: Rules Engine - Context

**Gathered:** 2026-04-13
**Status:** Ready for planning
**Mode:** Auto-generated (infrastructure phase detected)

<domain>
## Phase Boundary

Build `sekha.rules` as pure-logic library — no I/O orchestration, no hook integration. Given a directory of rule markdown files + a tool_name + tool_input, return the winning rule (if any) and its severity.

The "brain" of the differentiator, shipped as a testable unit before any process wiring.

</domain>

<decisions>
## Implementation Decisions

### Module: `sekha.rules`

```python
@dataclass(frozen=True)
class Rule:
    name: str           # filename sans .md
    severity: str       # "block" | "warn"
    triggers: list[str] # ["PreToolUse"], ["PostToolUse"], etc
    matches: list[str]  # ["Bash", "Edit"] or ["*"]
    pattern: re.Pattern # compiled, anchored by default
    priority: int       # higher wins ties
    message: str        # what AI sees on block
    raw_pattern: str    # original string (for logging)
    anchored: bool      # from frontmatter, default True

def load_rules(rules_dir: Path, hook_event: str, tool_name: str) -> list[Rule]:
    """Load rules matching hook event + tool, strict-parse frontmatter,
    surface errors loudly to stderr, skip invalid rules rather than silently ignoring."""

def evaluate(rules: list[Rule], tool_input: dict) -> Rule | None:
    """Return the winning rule per precedence: block > warn, highest priority wins.
    Ties: first match (stable iteration order) + log the tie to stderr."""
```

### Rule File Format

`~/.sekha/rules/<name>.md`:

```markdown
---
severity: block
triggers: [PreToolUse]
matches: [Bash]
pattern: 'rm\s+-rf\s+/'
priority: 100
anchored: false
---

Never run `rm -rf /` — catastrophic data loss.
```

Frontmatter parsed via existing `sekha.storage.parse_frontmatter()` (reuse).
Body (below `---`) is the `message`.

### Matching Semantics

- `matches`: list of exact tool names (`["Bash"]`) or wildcard (`["*"]`)
- `triggers`: list of hook event names (`["PreToolUse"]`)
- `pattern`: regex compiled with `re.IGNORECASE` by default (simple rules)
- `anchored: true` (default) wraps as `^<pattern>$` before compile
- Rule matches input if: hook_event in triggers AND (tool_name in matches OR `*` in matches) AND pattern.search(flatten(tool_input)) returns a match
- `flatten(tool_input)` = JSON-serialize the dict for pattern matching against all fields

### Precedence & Evaluation

1. Filter rules where `triggers` includes `hook_event` AND (`matches` includes `tool_name` OR `*`)
2. For each filtered rule, test `pattern` against `flatten(tool_input)`
3. From matching rules, select by precedence:
   - `severity=block` wins over `severity=warn`
   - Within same severity, highest `priority` wins
   - Ties: first (stable dir-sort order), log tie to stderr with both rule names
4. Return the winner or `None`

### Strict Parsing & Error Handling

- Missing required field (`severity`, `pattern`, `matches`, `triggers`) → log "invalid rule: <path>: missing <field>" to stderr, skip, continue
- Invalid regex (fails to compile) → log "invalid rule: <path>: <regex error>", skip, continue  
- Invalid severity value (not `block`/`warn`) → log, skip
- `raise_on_error=False` default (always continue); `raise_on_error=True` optional for testing

### Compile Cache

- Cache key: rules-dir mtime + count of .md files
- Cache stored in memory per-process (pickled if needed by hook layer later)
- Invalidates when any file in rules dir changes
- Cache hit ~10µs, cache miss full re-parse ~5ms for 50 rules

### Temporary Override

- `SEKHA_PAUSE` env var: comma-separated rule names to ignore
- Alternative: marker file `~/.sekha/rules/.paused/<name>` (allows `sekha pause <rule>` CLI to create)
- Ship env var in this phase; CLI `pause` command is Phase 6

### CLI Hook (Phase 6 preview)

`sekha rule test <rule-name> <tool> <input-json>` — dry-run evaluation. Exposed as function `test_rule(rule_name: str, tool: str, tool_input: dict) -> dict` in this phase, CLI wrapper in Phase 6.

### Module Layout

```
src/sekha/
    rules.py          # Rule dataclass, load_rules, evaluate, test_rule
    _rulesutil.py     # private: frontmatter reader, pattern anchoring, flatten
tests/
    test_rules.py
    test_rulesutil.py
    fixtures/rules/   # sample rules for testing (block-bash-rm, warn-force-push, etc)
```

### Claude's Discretion

- Whether `flatten(tool_input)` uses `json.dumps` or a custom flat-string builder (suggest `json.dumps(..., sort_keys=True)` — deterministic)
- Whether to case-fold rule names (suggest preserve exactly as filename)
- Exact stderr format for tie warning (suggest `sekha.rules: tie between <name1> and <name2>, using <winner>`)

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `sekha.storage.parse_frontmatter()` — frontmatter dict + body split
- `sekha.storage.CATEGORIES` — includes "rules"
- `sekha.paths.sekha_home()` — for locating `~/.sekha/rules/`
- `sekha.logutil.get_logger()` — stderr logging

### Established Patterns
- Stdlib only
- pathlib.Path
- unittest
- `SEKHA_HOME=tempfile.mkdtemp()` test isolation
- stderr-only logging

### Integration Points
- Phase 4 hook imports `sekha.rules.load_rules` and `evaluate`
- Phase 5 MCP server's `sekha_add_rule` tool writes rule files (using `sekha.storage.save_memory` with category="rules" or direct write)

</code_context>

<specifics>
## Specific Ideas

- Rules are pure functions — no file I/O inside `evaluate()`, only in `load_rules()`
- Tests must cover: valid rule loads, invalid rule skipped with log, tie-breaking, anchored vs unanchored, wildcard match, env-var pause, cache invalidation
- At least 10 sample rule fixtures: block-rm-rf, block-drop-table, block-force-push, block-sudo, warn-git-reset, warn-no-tests, block-eval-string, block-curl-bash, block-delete-branch, warn-todo-comments

</specifics>

<deferred>
## Deferred Ideas

- Rule conflict-resolution UI / `sekha rules list --conflicts` — Phase 6
- Compiled-rules pickle cache persisted to disk — optimization for Phase 4 if hot-path profiling needs it
- Rule templating / reusable rule fragments — v2

</deferred>

---

*Phase: 03-rules-engine*
*Context gathered: 2026-04-13 via infrastructure auto-detection*
