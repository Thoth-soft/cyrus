"""`cyrus doctor` implementation: 7 diagnostic checks with ASCII and JSON modes.

Each check returns a `CheckResult(name, ok, detail)`. `collect_checks()` runs
all 7 in a fixed order and `run(argv)` renders them to stdout -- either as
human-readable `[OK] / [FAIL]` lines or as a single JSON object when --json
is passed. Exit code is 0 iff every check passed.

The 7 checks:
1. python_version            Python >= 3.11
2. cyrus_on_path             shutil.which('cyrus') returns a path
3. cyrus_home_writable       ~/.cyrus/ is writable
4. settings_hook_registered  ~/.claude/settings.json has cyrus hook run
5. mcp_canary                `cyrus serve` responds to initialize
6. kill_switch               not active
7. recent_hook_errors        informational, never hard-fails

Design constraints:
- ASCII-only output, cp1252 safe on Windows cmd.exe.
- The MCP canary spawns a subprocess; tests patch `_mcp_canary` so the
  fast unit suite never shells out.
- recent_hook_errors reports informationally (ok=True) even when errors
  are present -- surfacing them is the point, not failing the diagnostic.
"""
# Requirement coverage:
#   CLI-03: 7-check diagnostic with --json mode.
#   CLI-07: ASCII-only output.
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cyrus.paths import cyrus_home

__all__ = (
    "CheckResult",
    "collect_checks",
    "run",
)


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str


# ----------------------------------------------------------------------
# Individual checks
# ----------------------------------------------------------------------
def _check_python_version() -> CheckResult:
    v = sys.version_info
    ok = (v.major, v.minor) >= (3, 11)
    return CheckResult("python_version", ok, f"Python {v.major}.{v.minor}.{v.micro}")


def _check_cyrus_on_path() -> CheckResult:
    path = shutil.which("cyrus")
    return CheckResult(
        "cyrus_on_path",
        path is not None,
        path or "not found on PATH",
    )


def _check_cyrus_home_writable() -> CheckResult:
    home = cyrus_home()
    try:
        home.mkdir(parents=True, exist_ok=True)
        probe = home / ".doctor-probe"
        probe.write_text("probe", encoding="utf-8")
        probe.unlink()
        return CheckResult("cyrus_home_writable", True, str(home))
    except OSError as exc:
        return CheckResult("cyrus_home_writable", False, f"{home}: {exc}")


def _check_settings_hook_registered() -> CheckResult:
    settings = Path.home() / ".claude" / "settings.json"
    if not settings.exists():
        return CheckResult(
            "settings_hook_registered",
            False,
            f"{settings} missing; run `cyrus init`",
        )
    try:
        data = json.loads(settings.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return CheckResult(
            "settings_hook_registered", False, f"parse error: {exc}"
        )
    if not isinstance(data, dict):
        return CheckResult(
            "settings_hook_registered", False, "settings.json is not an object"
        )
    found = False
    hooks_block = data.get("hooks") or {}
    pretool = hooks_block.get("PreToolUse") or []
    if isinstance(pretool, list):
        for entry in pretool:
            if not isinstance(entry, dict):
                continue
            for h in entry.get("hooks") or []:
                if isinstance(h, dict) and h.get("command") == "cyrus hook run":
                    found = True
                    break
            if found:
                break
    detail = (
        "cyrus hook run registered"
        if found
        else "not found; run `cyrus init`"
    )
    return CheckResult("settings_hook_registered", found, detail)


def _mcp_canary(timeout: float = 5.0) -> tuple[bool, str]:
    """Spawn `cyrus serve`, send initialize, read one response, return (ok, detail).

    Returns (False, reason) on any exception -- the doctor never raises.
    """
    msg = json.dumps({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "doctor", "version": "0"},
        },
    }) + "\n"
    try:
        proc = subprocess.Popen(
            [sys.executable, "-m", "cyrus.cli", "serve"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            out, _ = proc.communicate(input=msg, timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            return (False, f"cyrus serve did not respond within {timeout}s")
        for line in out.splitlines():
            if not line.strip():
                continue
            try:
                resp = json.loads(line)
            except json.JSONDecodeError:
                continue
            pv = (resp.get("result") or {}).get("protocolVersion", "")
            if pv:
                return (True, f"protocolVersion={pv}")
        return (False, "no initialize response from cyrus serve")
    except Exception as exc:  # noqa: BLE001 -- doctor must not raise
        return (False, f"canary failed: {exc}")


def _check_mcp_canary() -> CheckResult:
    ok, detail = _mcp_canary()
    return CheckResult("mcp_canary", ok, detail)


def _check_kill_switch() -> CheckResult:
    # Lazy import: cyrus._hookutil pulls in cyrus.paths -- cheap but keeps
    # the top-level module strictly to stdlib + cyrus.paths.
    from cyrus._hookutil import check_kill_switch
    tripped = check_kill_switch()
    if tripped:
        return CheckResult(
            "kill_switch",
            False,
            "kill switch ACTIVE; run `cyrus hook enable`",
        )
    return CheckResult("kill_switch", True, "not active")


def _check_recent_hook_errors() -> CheckResult:
    log = cyrus_home() / "hook-errors.log"
    if not log.exists():
        return CheckResult("recent_hook_errors", True, "no errors logged")
    try:
        text = log.read_text(encoding="utf-8")
    except OSError as exc:
        return CheckResult("recent_hook_errors", False, f"read error: {exc}")

    # Count entries whose leading timestamp falls within the last 24h. Lines
    # that don't parse as ISO timestamps (traceback continuations, etc.)
    # are skipped rather than counted.
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    recent: list[str] = []
    for line in text.splitlines():
        parts = line.split(" ", 1)
        if len(parts) < 2:
            continue
        try:
            ts = datetime.fromisoformat(parts[0])
        except ValueError:
            continue
        # Allow naive timestamps by assuming UTC.
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        if ts >= cutoff:
            recent.append(line)

    if not recent:
        return CheckResult("recent_hook_errors", True, "no errors logged")
    # Show the last entry (truncated) and count. Not a hard fail: this is
    # informational diagnostic output, not a reason to refuse the install.
    last = recent[-1]
    if len(last) > 80:
        last = last[:77] + "..."
    return CheckResult(
        "recent_hook_errors",
        True,
        f"{len(recent)} recent; last: {last}",
    )


# ----------------------------------------------------------------------
# Aggregator
# ----------------------------------------------------------------------
def collect_checks() -> list[CheckResult]:
    """Run all 7 checks and return them in canonical order."""
    return [
        _check_python_version(),
        _check_cyrus_on_path(),
        _check_cyrus_home_writable(),
        _check_settings_hook_registered(),
        _check_mcp_canary(),
        _check_kill_switch(),
        _check_recent_hook_errors(),
    ]


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="cyrus doctor",
        description="Run 7 diagnostic checks for a Cyrus install",
    )
    parser.add_argument(
        "--json",
        dest="json_mode",
        action="store_true",
        help="Emit machine-readable JSON to stdout",
    )
    args = parser.parse_args(argv or [])

    checks = collect_checks()
    all_ok = all(c.ok for c in checks)

    if args.json_mode:
        payload = {
            "checks": [asdict(c) for c in checks],
            "all_ok": all_ok,
        }
        sys.stdout.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
        try:
            sys.stdout.flush()
        except (ValueError, OSError):
            pass
        return 0 if all_ok else 1

    for c in checks:
        tag = "[OK]" if c.ok else "[FAIL]"
        sys.stdout.write(f"{tag} {c.name}: {c.detail}\n")
    sys.stdout.write("\n")
    if all_ok:
        sys.stdout.write("All checks passed. Cyrus is ready to use.\n")
    else:
        sys.stdout.write("One or more checks failed. See above.\n")
    try:
        sys.stdout.flush()
    except (ValueError, OSError):
        pass
    return 0 if all_ok else 1
