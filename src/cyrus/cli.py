"""Cyrus CLI router. `cyrus <subcommand>` entry point.

Subcommands live in their own modules and are lazy-imported so the CLI
startup cost stays low for future Phase 6 commands (`doctor`, `init`,
`add-rule`) that don't need the hook machinery.

The existing `pyproject.toml [project.scripts] cyrus = cyrus.cli:main`
console script dispatches here.

Phase 4 subcommands:
- `cyrus hook run`     - invoked by Claude Code per tool call (stdin JSON to stdout decision)
- `cyrus hook bench`   - benchmark p50/p95/p99 latency (implemented in plan 04-02)
- `cyrus hook enable`  - clear kill-switch marker
- `cyrus hook disable` - create kill-switch marker (short-circuits to allow)

Phase 6 will add: init, doctor, add-rule, list-rules, rule test, pause.

Design constraint: `main(argv)` accepts an explicit argv list so tests can
drive it without mutating `sys.argv`. All subcommand module imports live
inside main() branches.
"""
# Requirement coverage:
#   HOOK-01: `cyrus hook run` entry point registered via argparse +
#            pyproject.toml [project.scripts] cyrus = "cyrus.cli:main".
from __future__ import annotations

import argparse
import sys


def _build_parser() -> argparse.ArgumentParser:
    """Construct the root argparse parser with the `hook` sub-subparser tree."""
    parser = argparse.ArgumentParser(
        prog="cyrus",
        description="Cyrus — AI memory system with hook-level rules enforcement",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    hook = sub.add_parser("hook", help="PreToolUse hook operations")
    hook_sub = hook.add_subparsers(dest="hook_command", required=True)
    hook_sub.add_parser(
        "run",
        help="Run PreToolUse hook (reads stdin JSON, writes decision JSON to stdout)",
    )
    hook_sub.add_parser(
        "bench",
        help="Benchmark hook latency (100 runs, p50/p95/p99)",
    )
    hook_sub.add_parser(
        "enable",
        help="Clear kill-switch marker; re-enable hook",
    )
    hook_sub.add_parser(
        "disable",
        help="Create kill-switch marker; short-circuit hook to allow",
    )

    # Phase 5: MCP stdio server. `claude mcp add cyrus -- cyrus serve`
    # wires this into Claude Code. The subparser takes no arguments — the
    # server reads every directive off stdin as JSON-RPC frames.
    sub.add_parser(
        "serve",
        help="Run MCP stdio server (invoked by Claude Code via `claude mcp add cyrus`)",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    """Dispatch the requested subcommand and return its exit code.

    `argv` defaults to sys.argv[1:] (argparse handles the None case). Passing
    an explicit list keeps tests hermetic. Subcommand modules are imported
    lazily inside each branch so `cyrus --help` never pulls in cyrus.hook.

    Windows cp1252 guard (Pitfall 4): if stdout/stderr support reconfigure(),
    force UTF-8 with errors="replace" so non-ASCII help text or error
    messages can never crash the CLI with UnicodeEncodeError. The `hook run`
    subcommand itself only emits ASCII JSON, so this is a defense for future
    commands (init, doctor, add-rule) that might include smart quotes.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass  # stream already closed or non-reconfigurable — skip

    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "hook":
        if args.hook_command == "run":
            from cyrus.hook import main as hook_main
            return hook_main()
        if args.hook_command == "bench":
            # Plan 04-02 lands cyrus.hook.bench. Until then, emit a friendly
            # stderr message instead of raising AttributeError/ImportError.
            try:
                from cyrus.hook import bench as hook_bench  # type: ignore[attr-defined]
            except ImportError:
                sys.stderr.write(
                    "cyrus hook bench: not yet implemented (lands in plan 04-02)\n"
                )
                return 1
            return hook_bench()
        if args.hook_command == "enable":
            from cyrus.hook import enable as hook_enable
            return hook_enable()
        if args.hook_command == "disable":
            from cyrus.hook import disable as hook_disable
            return hook_disable()

    if args.command == "serve":
        # Lazy import: keeps `cyrus hook run` cold-start unaffected by the
        # server module (which pulls in cyrus.jsonrpc + cyrus.logutil at
        # import time — cheap, but still not free on the hook path).
        from cyrus.server import main as server_main
        return server_main()

    # Unreachable — argparse would have exited on unknown commands.
    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
