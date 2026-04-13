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
import re as _re
import sys

# Rule-name validator: lowercase alnum + hyphens, 2-50 chars total, starting
# and ending alnum so backup suffixes like `-bak` can never produce an
# unparseable `.md` filename. Matches Path.stem format expectations.
_NAME_RE = _re.compile(r"^[a-z0-9][a-z0-9-]{0,48}[a-z0-9]$")


def _build_parser() -> argparse.ArgumentParser:
    """Construct the root argparse parser with the `hook` sub-subparser tree."""
    parser = argparse.ArgumentParser(
        prog="cyrus",
        description="Cyrus -- AI memory system with hook-level rules enforcement",
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
    # wires this into Claude Code. The subparser takes no arguments; the
    # server reads every directive off stdin as JSON-RPC frames.
    sub.add_parser(
        "serve",
        help="Run MCP stdio server (invoked by Claude Code via `claude mcp add cyrus`)",
    )

    # Phase 6: install/diagnostic/rules commands. Lazy-imported in main().
    sub.add_parser(
        "init",
        help="Create ~/.cyrus/ tree, write config, register hook in "
             "~/.claude/settings.json",
    )

    doctor = sub.add_parser(
        "doctor",
        help="Run 7 diagnostic checks (Python, PATH, ~/.cyrus, settings.json, "
             "MCP canary, kill switch, recent errors)",
    )
    doctor.add_argument(
        "--json",
        dest="json_mode",
        action="store_true",
        help="Emit machine-readable JSON to stdout",
    )

    addrule = sub.add_parser(
        "add-rule",
        help="Create a new rule file in ~/.cyrus/rules/<name>.md",
    )
    addrule.add_argument("--name", required=True)
    addrule.add_argument(
        "--severity", required=True, choices=["block", "warn"]
    )
    addrule.add_argument(
        "--matches",
        required=True,
        nargs="+",
        help="One or more tool names, or '*' for wildcard",
    )
    addrule.add_argument("--pattern", required=True)
    addrule.add_argument("--message", required=True)
    addrule.add_argument("--priority", type=int, default=50)
    addrule.add_argument(
        "--triggers",
        nargs="+",
        default=["PreToolUse"],
        help="Hook events to trigger on (default: PreToolUse)",
    )
    addrule.add_argument(
        "--anchored",
        dest="anchored",
        action="store_true",
        default=True,
        help="Anchor the pattern with ^ and $ (default: on)",
    )
    addrule.add_argument(
        "--no-anchored",
        dest="anchored",
        action="store_false",
        help="Do not anchor the pattern (allow substring match)",
    )

    sub.add_parser(
        "list-rules",
        help="List rules in ~/.cyrus/rules/ as an ASCII table",
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
                pass  # stream already closed or non-reconfigurable; skip

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
        # import time; cheap, but still not free on the hook path).
        from cyrus.server import main as server_main
        return server_main()

    if args.command == "init":
        from cyrus._init import run as init_run
        return init_run([])

    if args.command == "doctor":
        from cyrus._doctor import run as doctor_run
        extra = ["--json"] if args.json_mode else []
        return doctor_run(extra)

    if args.command == "add-rule":
        return _cmd_add_rule(args)

    if args.command == "list-rules":
        return _cmd_list_rules()

    # Unreachable: argparse would have exited on unknown commands.
    parser.error(f"unknown command: {args.command}")
    return 2


def _cmd_add_rule(args: argparse.Namespace) -> int:
    """Validate args, compile the regex, and write the rule file.

    Validation order:
    1. Name matches _NAME_RE (lowercase alnum + hyphens, 2-50 chars).
    2. Pattern compiles (anchored per --anchored flag).
    3. Target file does not already exist (no accidental overwrite).

    On any validation failure: exit 2, write a single-line error to stderr,
    leave the filesystem untouched. On success: write the file via
    atomic_write + dump_frontmatter and exit 0.
    """
    from cyrus._rulesutil import _compile_rule_pattern
    from cyrus.paths import category_dir
    from cyrus.storage import atomic_write, dump_frontmatter

    if not _NAME_RE.match(args.name):
        sys.stderr.write(
            f"cyrus add-rule: invalid name {args.name!r}; "
            "must be lowercase alnum + hyphens, 2-50 chars\n"
        )
        return 2

    try:
        _compile_rule_pattern(args.pattern, anchored=args.anchored)
    except Exception as exc:  # noqa: BLE001 -- surface re.error and friends
        sys.stderr.write(
            f"cyrus add-rule: regex will not compile: {exc}\n"
        )
        return 2

    rules_dir = category_dir("rules")
    rules_dir.mkdir(parents=True, exist_ok=True)
    path = rules_dir / f"{args.name}.md"
    if path.exists():
        sys.stderr.write(
            f"cyrus add-rule: {path} already exists; choose a different --name\n"
        )
        return 2

    metadata = {
        "name": args.name,
        "severity": args.severity,
        "triggers": list(args.triggers),
        "matches": list(args.matches),
        "pattern": args.pattern,
        "priority": int(args.priority),
        "message": args.message,
        "anchored": bool(args.anchored),
    }
    document = dump_frontmatter(metadata, "")
    atomic_write(path, document)
    sys.stderr.write(f"[OK] wrote {path}\n")
    return 0


def _cmd_list_rules() -> int:
    """Print an ASCII table of rules in ~/.cyrus/rules/ to stdout.

    Broken rules (missing required frontmatter, bad regex, I/O error) get
    a STATUS=BROKEN row rather than crashing the command -- surfacing the
    mess is the point. Exit is always 0; a broken rule is a data issue,
    not a program failure.
    """
    from cyrus._cliutil import format_table
    from cyrus._rulesutil import _parse_rule_file
    from cyrus.paths import category_dir

    rules_dir = category_dir("rules")
    headers = ["NAME", "SEVERITY", "MATCHES", "PATTERN", "STATUS"]
    rows: list[list[str]] = []
    if rules_dir.exists():
        for path in sorted(rules_dir.glob("*.md")):
            try:
                r = _parse_rule_file(path)
                rows.append([
                    r.name,
                    r.severity,
                    ",".join(r.matches),
                    r.raw_pattern[:40],
                    "OK",
                ])
            except (ValueError, OSError) as exc:
                detail = str(exc)[:40]
                rows.append([path.stem, "?", "?", detail, "BROKEN"])
    sys.stdout.write(format_table(headers, rows) + "\n")
    try:
        sys.stdout.flush()
    except (ValueError, OSError):
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
