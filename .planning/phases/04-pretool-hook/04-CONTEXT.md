# Phase 4: PreToolUse Hook - Context

**Gathered:** 2026-04-13
**Status:** Ready for planning
**Mode:** Auto-generated (infrastructure phase — the differentiator, ships before the MCP server)

<domain>
## Phase Boundary

Build `cyrus.hook` — a short-lived Python process invoked by Claude Code's PreToolUse hook. Reads JSON from stdin, evaluates rules, emits `permissionDecision: deny` JSON to stdout when a block-severity rule matches. Ships before the MCP server so the core value proposition is validated on real Claude Code before anything else.

If the hook doesn't actually block tool calls on a real Claude Code install, the project has no moat. This phase exists to find that out on day 7, not day 30.

</domain>

<decisions>
## Implementation Decisions

### Module: `cyrus.hook`

Entry point registered as `cyrus hook run` via `[project.scripts]` in pyproject.toml (add alongside existing `cyrus` entry point — or repurpose existing as umbrella CLI with `hook run` subcommand).

```python
def main() -> int:
    """PreToolUse hook entrypoint. Reads JSON stdin, emits decision JSON stdout.
    Returns 0 on normal operation, 2 on explicit block as belt-and-suspenders fallback."""
```

### CLI Routing

Since `[project.scripts] cyrus = "cyrus.cli:main"` already exists, we need a `cyrus.cli` module with argparse routing. For now, implement a minimal CLI in `src/cyrus/cli.py`:

```python
def main():
    parser = argparse.ArgumentParser(prog="cyrus")
    sub = parser.add_subparsers(dest="command", required=True)
    hook = sub.add_parser("hook", help="Hook operations")
    hook_sub = hook.add_subparsers(dest="hook_command", required=True)
    hook_sub.add_parser("run", help="Run PreToolUse hook (invoked by Claude Code)")
    hook_sub.add_parser("bench", help="Benchmark hook latency (100 runs, p50/p95)")
    
    args = parser.parse_args()
    if args.command == "hook" and args.hook_command == "run":
        from cyrus.hook import main as hook_main
        return hook_main()
    if args.command == "hook" and args.hook_command == "bench":
        from cyrus.hook import bench as hook_bench
        return hook_bench()
```

This also positions `cyrus init`, `cyrus doctor`, `cyrus add-rule`, `cyrus list-rules` for Phase 6.

### PreToolUse Schema (input)

Read JSON from stdin matching Claude Code's schema:
```json
{
  "session_id": "...",
  "transcript_path": "...",
  "cwd": "...",
  "permission_mode": "default",
  "hook_event_name": "PreToolUse",
  "tool_name": "Bash",
  "tool_input": {"command": "rm -rf /"},
  "tool_use_id": "..."
}
```

### Block Output

On block: emit to stdout, exit 0:
```json
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": "<rule message>"
  }
}
```

Belt-and-suspenders fallback: also write reason to stderr and exit 2. Research says Claude Code prefers JSON stdout, but stderr+exit-2 is a documented backup path.

### Warn Output

On `severity: warn`: emit to stdout, exit 0:
```json
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "additionalContext": "<rule message>"
  }
}
```

No allow output — absence of decision allows by default.

### Performance Budget (HARD CI GATE)

- **p50 < 50ms, p95 < 150ms** on Win/macOS/Linux
- Python cold-start on Windows is 100-250ms baseline — the tightest platform
- `cyrus hook bench` runs 100 invocations with realistic rules, reports p50/p95/p99
- CI gate: bench run must stay within budget; build fails otherwise (but same platform-aware approach as search bench — Windows budget can be relaxed with `CYRUS_HOOK_P95_MS` override)

### Lazy Imports

Top of `hook.py` imports only `sys, json`. Every other import inside `main()` function body:
```python
def main():
    try:
        from cyrus.rules import load_rules, evaluate
        from cyrus.paths import cyrus_home
        from cyrus.logutil import get_logger
        # ... rest
    except Exception as e:
        _fail_open(e)
```

`python -X importtime cyrus.hook` should show total import <30ms.

### Compiled Rules Cache

Handled by `cyrus.rules` module already — mtime-based cache in-process. Since the hook is a short-lived process (one invocation per tool call), in-process cache doesn't persist. Options:
1. Accept the per-invocation parse cost (~5ms for 50 rules)
2. Persist compiled rules as pickle file keyed on rules-dir mtime (optimization if needed)

Start with option 1; measure in bench. If p95 misses target, add pickle cache in a follow-up plan.

### Fail-Open Policy

ANY exception in the hook:
```python
def main():
    try:
        # ... full hook logic
    except Exception as e:
        _fail_open(e)
        return 0  # allow tool call

def _fail_open(exc):
    # Log to ~/.cyrus/hook-errors.log with full traceback
    log_path = Path.home() / ".cyrus" / "hook-errors.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(f"{datetime.now().isoformat()} {type(exc).__name__}: {exc}\n")
        f.write(traceback.format_exc())
        f.write("\n")
    # Write warning to stderr (visible to Claude Code operator)
    print(f"cyrus hook error: {exc}", file=sys.stderr)
    # No block output → tool proceeds (fail open)
```

### Kill Switch

After 3 consecutive errors within the last N minutes, write `~/.cyrus/hook-disabled.marker`. `cyrus doctor` (Phase 6) surfaces this; user runs `cyrus hook enable` to clear.

```python
def _check_kill_switch():
    marker = cyrus_home() / "hook-disabled.marker"
    if marker.exists():
        # Log once per hour to avoid spam
        return True
    return False
```

### End-to-End Integration Test

A real Claude Code session with:
1. Install cyrus: `pip install -e .`
2. Create rule: `~/.cyrus/rules/block-bash-test.md` — blocks all Bash calls
3. Register hook in `.claude/settings.json` using `cyrus hook run`
4. Start Claude Code, ask it to run a Bash command
5. Assert: command was blocked, message visible to user

This test is **manual** in Phase 4. Automated version via headless Claude Code harness is a v2 concern.

### Module Layout

```
src/cyrus/
    cli.py             # NEW — argparse router
    hook.py            # NEW — PreToolUse hook entry + bench
    _hookutil.py       # NEW — private: JSON I/O, kill-switch, fail-open helpers
tests/
    test_cli.py
    test_hook.py
    test_hookutil.py
    fixtures/hook-events/  # sample PreToolUse JSON files
```

### Claude's Discretion

- Whether `cyrus hook bench` uses subprocess or in-process timing (suggest subprocess — measures real cold start)
- Bench result format (suggest: `p50=42ms p95=118ms p99=143ms runs=100`)
- Kill-switch error-rate window (suggest: last 5 errors within 10 minutes)
- Whether to ship a `cyrus hook enable/disable` command in this phase (suggest: yes, small addition, avoids Phase 6 retrofit)

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `cyrus.rules.load_rules`, `cyrus.rules.evaluate` — rules matching
- `cyrus.paths.cyrus_home()` — home dir
- `cyrus.logutil.get_logger()` — stderr logging
- `cyrus.storage` — atomic write for hook-errors.log (optional)

### Established Patterns
- Stdlib only
- pathlib.Path
- unittest
- stderr-only logging (EXCEPT for hook's protocol output on stdout)

### Integration Points
- Claude Code's `.claude/settings.json` hook config calls `cyrus hook run`
- Phase 5 MCP server is separate process; no shared state
- Phase 6 `cyrus init` will register hook in `.claude/settings.json` automatically

</code_context>

<specifics>
## Specific Ideas

- **Stdout is sacred** — only the hook decision JSON goes there, nothing else. Any stray `print(` breaks the protocol.
- Swap `sys.stdout` with `sys.stderr` at the top of `main()` before any rules module imports (which might log). Restore for final JSON emit.
- Bench script runs `cyrus hook run` as a subprocess 100 times with the same fixture input — measures real cold-start including Python interpreter launch.
- On Windows, `subprocess.run` with `.exe` entry point vs `python -m cyrus.cli` can differ by 20-30ms. Bench both paths, document difference.

</specifics>

<deferred>
## Deferred Ideas

- Long-lived daemon hook (IPC socket) — only if p95 can't hit budget with lazy-imports alone
- Hook that caches compiled rules in pickle file — optimization for later
- PostToolUse hook support — v2
- `UserPromptSubmit` hook — v2
- Automated end-to-end test via headless Claude Code — v2

</deferred>

---

*Phase: 04-pretool-hook*
*Context gathered: 2026-04-13 via infrastructure auto-detection*
