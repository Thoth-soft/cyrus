"""PreToolUse hook entrypoint. Short-lived process invoked by Claude Code.

Reads a PreToolUse JSON event from stdin, evaluates rules via sekha.rules,
and emits a permissionDecision JSON to stdout. Fail-open on any internal
error; kill-switch marker disables the hook after repeated failures.

stdout is sacred — only the decision JSON goes there. sys.stdout is
swapped to sys.stderr inside _run() before any non-stdlib import so stray
log lines from dependencies (or a rogue `print()` anywhere in the import
chain) cannot corrupt the protocol stream. The real stdout is passed to
the emit_* helpers explicitly.

Module-top imports are strictly `sys` and `json` (plus `__future__`). Every
other import — sekha.rules, sekha.paths, sekha._hookutil, pathlib, even
`traceback` — lives inside _run() so `python -X importtime sekha.hook`
stays under the 30ms budget. The ast-introspection test in tests/test_hook.py
enforces this structurally.
"""
# Requirement coverage:
#   HOOK-01: `sekha hook run` entry (dispatched by sekha.cli → main())
#   HOOK-02: Reads PreToolUse JSON from stdin
#   HOOK-03: Emits deny JSON on block match
#   HOOK-04: Emits additionalContext JSON on warn match
#   HOOK-05: Belt-and-suspenders (stdout JSON + stderr + exit 2)
#   HOOK-06: Fail-open with ~/.sekha/hook-errors.log + stderr warning
#   HOOK-07: Kill switch after 3 errors in 10 min via marker file
#   HOOK-09: Lazy imports — only sys, json at module top
from __future__ import annotations

import sys
import json  # noqa: F401 — re-exported name for CLI & bench; imported here per CONTEXT budget


def _run(stdin, stdout, stderr) -> int:
    """Core PreToolUse decision loop. Test-callable with in-memory streams.

    Contract:
    - Swap sys.stdout → stderr early, before any heavyweight import.
    - Check kill switch first — if tripped, return allow-by-default.
    - Parse stdin → load rules for (hook_event, tool_name) → evaluate.
    - Emit block / warn / allow via sekha._hookutil helpers.
    - Top-level `except Exception` guarantees fail-open: log + stderr warn
      + exit 0. After 3 errors within 10 minutes, create the kill-switch
      marker so subsequent invocations short-circuit.

    Returns the exit code (2 on block, 0 otherwise). Callers in test code
    pass StringIO streams; main() delegates to sys.stdin/stdout/stderr.
    """
    real_stdout = stdout
    saved_stdout = sys.stdout
    # Redirect any stray print() from downstream imports to stderr so it
    # cannot corrupt the protocol channel.
    sys.stdout = stderr
    try:
        # Everything non-stdlib lives here — see module docstring.
        from sekha._hookutil import (
            check_kill_switch,
            create_marker,
            emit_allow,
            emit_block,
            emit_warn,
            fail_open,
            read_event,
            record_error,
        )

        # Kill switch — never evaluate rules when disabled. Short-circuit
        # BEFORE reading stdin so a malformed event while disabled still
        # produces a clean allow (Claude Code keeps working).
        if check_kill_switch():
            return emit_allow(real_stdout)

        try:
            event = read_event(stdin)
            from sekha.paths import category_dir
            from sekha.rules import evaluate, load_rules

            hook_event = event.get("hook_event_name", "PreToolUse")
            tool_name = event.get("tool_name", "")
            tool_input = event.get("tool_input") or {}

            rules = load_rules(category_dir("rules"), hook_event, tool_name)
            winner = evaluate(rules, tool_input)
            if winner is None:
                return emit_allow(real_stdout)
            if winner.severity == "block":
                return emit_block(winner.message, real_stdout, stderr)
            return emit_warn(winner.message, real_stdout)
        except Exception as exc:  # noqa: BLE001 — fail-open is intentional
            fail_open(exc, stderr)
            if record_error(exc):
                create_marker()
            return 0
    finally:
        sys.stdout = saved_stdout  # restore for process cleanliness


def main() -> int:
    """Real-process entrypoint. Reads sys.stdin, writes sys.stdout/stderr."""
    return _run(sys.stdin, sys.stdout, sys.stderr)


def enable() -> int:
    """Remove the kill-switch marker so the hook runs again."""
    from sekha._hookutil import clear_marker
    clear_marker()
    sys.stderr.write("sekha hook: enabled\n")
    return 0


def disable() -> int:
    """Create the kill-switch marker so the hook short-circuits to allow."""
    from sekha._hookutil import create_marker
    create_marker()
    sys.stderr.write("sekha hook: disabled\n")
    return 0


def bench(argv: list[str] | None = None) -> int:
    """Run `python -m sekha.cli hook run` 100 times, report p50/p95/p99.

    Measures real cold-start (Python interpreter launch + module imports +
    rules load + evaluate + JSON emit) by shelling out rather than timing
    in-process — in-process timing would hide exactly the overhead Claude
    Code pays per tool call.

    Exits 0 if p50 <= p50_budget_ms AND p95 <= p95_budget_ms; else 1.
    Defaults: p50=50ms, p95=150ms (per HOOK-08). Override via env vars
    SEKHA_HOOK_P50_MS and SEKHA_HOOK_P95_MS (mirrors the Phase 2 search
    bench SEKHA_BENCH_P95_MS precedent).

    Every import is local to this function — keeps `sekha hook run` cold
    start unaffected by bench code. `argv` accepted for future flag support
    (e.g., --runs) but currently ignored.
    """
    import os
    import shutil
    import subprocess
    import sys as _sys
    import tempfile
    import time
    from pathlib import Path

    del argv  # reserved for future flags; bench currently takes no args

    RUNS = 100
    p50_budget = float(os.environ.get("SEKHA_HOOK_P50_MS", "50"))
    p95_budget = float(os.environ.get("SEKHA_HOOK_P95_MS", "150"))

    # Locate fixtures relative to this module. src/sekha/hook.py → repo root
    # via three .parent hops. If the repo layout ever changes, this fails
    # loud below (explicit error, exit 1) rather than silently timing an
    # empty rules dir.
    pkg_root = Path(__file__).resolve().parent.parent.parent
    fixtures = pkg_root / "tests" / "fixtures" / "bench_rules"
    event_path = pkg_root / "tests" / "fixtures" / "hook_events" / "bash_rm_rf.json"
    if not fixtures.exists() or not event_path.exists():
        _sys.stderr.write(
            "sekha hook bench: bench fixtures missing. "
            "Run from a source checkout (editable install).\n"
        )
        return 1

    event_bytes = event_path.read_bytes()

    # Stage a temp SEKHA_HOME with the three bench rule fixtures. Isolates
    # the bench from the user's real ~/.sekha/rules/ so results are
    # reproducible and the bench doesn't depend on what's installed locally.
    with tempfile.TemporaryDirectory() as tmp:
        tmp_home = Path(tmp)
        rules_dir = tmp_home / "rules"
        rules_dir.mkdir(parents=True)
        for rule_file in fixtures.glob("*.md"):
            shutil.copy(rule_file, rules_dir / rule_file.name)

        env = {**os.environ, "SEKHA_HOME": str(tmp_home)}

        # Warm-up run — excluded from the sample so the first-run
        # filesystem cache miss doesn't contaminate p50.
        subprocess.run(
            [_sys.executable, "-m", "sekha.cli", "hook", "run"],
            input=event_bytes,
            env=env,
            capture_output=True,
            timeout=10,
        )

        latencies_ms: list[float] = []
        for _ in range(RUNS):
            t0 = time.perf_counter()
            subprocess.run(
                [_sys.executable, "-m", "sekha.cli", "hook", "run"],
                input=event_bytes,
                env=env,
                capture_output=True,
                timeout=10,
            )
            latencies_ms.append((time.perf_counter() - t0) * 1000.0)

    latencies_ms.sort()
    p50 = latencies_ms[RUNS // 2]
    p95 = latencies_ms[int(RUNS * 0.95) - 1]
    p99 = latencies_ms[int(RUNS * 0.99) - 1]
    _sys.stderr.write(
        f"p50={p50:.1f}ms p95={p95:.1f}ms p99={p99:.1f}ms runs={RUNS} "
        f"budget_p50={p50_budget:.0f}ms budget_p95={p95_budget:.0f}ms\n"
    )

    if p50 > p50_budget or p95 > p95_budget:
        _sys.stderr.write("sekha hook bench: BUDGET EXCEEDED\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
