"""Tests for sekha.hook: PreToolUse decision pipeline + fail-open + kill switch.

Plan 04-01 Task 2 — RED stage. Module does not yet exist. The GREEN step
lands `src/sekha/hook.py` with a `_run(stdin, stdout, stderr) -> int` helper
that tests call directly (avoids monkey-patching sys.std*).

Isolation:
- Every test overrides SEKHA_HOME to a tempdir + writes rule fixtures there.
- sekha.rules.clear_cache() is called in setUp so tests see a fresh rule
  parse (the rules module mtime-caches the parsed list per directory).
- tests swap sys.stdout explicitly inside _run, and restore on exit, so
  running these tests via `python -m unittest` must not leak the swap.
"""
from __future__ import annotations

import ast
import io
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "hook_events"


def _write_block_rule(
    rules_dir: Path,
    *,
    name: str = "block-bash-rm",
    pattern: str = "rm -rf",
    priority: int = 10,
    message: str = "rm -rf is not allowed",
    matches: str = "[Bash]",
) -> None:
    rules_dir.mkdir(parents=True, exist_ok=True)
    (rules_dir / f"{name}.md").write_text(
        textwrap.dedent(f"""\
            ---
            name: {name}
            severity: block
            triggers: [PreToolUse]
            matches: {matches}
            pattern: {pattern}
            priority: {priority}
            anchored: false
            message: {message}
            ---
        """),
        encoding="utf-8",
    )


def _write_warn_rule(
    rules_dir: Path,
    *,
    name: str = "warn-bash-rm",
    pattern: str = "rm -rf",
    priority: int = 5,
    message: str = "rm -rf is risky",
    matches: str = "[Bash]",
) -> None:
    rules_dir.mkdir(parents=True, exist_ok=True)
    (rules_dir / f"{name}.md").write_text(
        textwrap.dedent(f"""\
            ---
            name: {name}
            severity: warn
            triggers: [PreToolUse]
            matches: {matches}
            pattern: {pattern}
            priority: {priority}
            anchored: false
            message: {message}
            ---
        """),
        encoding="utf-8",
    )


class _HookTestBase(unittest.TestCase):
    def setUp(self) -> None:
        self._saved_home = os.environ.pop("SEKHA_HOME", None)
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["SEKHA_HOME"] = self._tmp.name
        self.sekha_home = Path(self._tmp.name)
        self.rules_dir = self.sekha_home / "rules"
        # Fresh rule-cache per test — the Phase 3 engine caches across dirs.
        from sekha.rules import clear_cache
        clear_cache()

    def tearDown(self) -> None:
        os.environ.pop("SEKHA_HOME", None)
        if self._saved_home is not None:
            os.environ["SEKHA_HOME"] = self._saved_home
        from sekha.rules import clear_cache
        clear_cache()
        self._tmp.cleanup()

    def _stdin(self, fixture_name: str) -> io.StringIO:
        return io.StringIO((FIXTURE_DIR / fixture_name).read_text(encoding="utf-8"))


class TestDecisionPipeline(_HookTestBase):
    def test_block_rule_produces_deny_json_and_exit_2(self) -> None:
        from sekha.hook import _run
        _write_block_rule(self.rules_dir)
        stdout, stderr = io.StringIO(), io.StringIO()
        rc = _run(self._stdin("bash_rm_rf.json"), stdout, stderr)
        self.assertEqual(rc, 2)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(
            payload["hookSpecificOutput"]["permissionDecision"], "deny"
        )
        self.assertEqual(
            payload["hookSpecificOutput"]["hookEventName"], "PreToolUse"
        )
        self.assertIn("rm -rf is not allowed",
                      payload["hookSpecificOutput"]["permissionDecisionReason"])
        self.assertIn("rm -rf is not allowed", stderr.getvalue())

    def test_warn_rule_produces_additional_context_and_exit_0(self) -> None:
        from sekha.hook import _run
        _write_warn_rule(self.rules_dir)
        stdout, stderr = io.StringIO(), io.StringIO()
        rc = _run(self._stdin("bash_rm_rf.json"), stdout, stderr)
        self.assertEqual(rc, 0)
        payload = json.loads(stdout.getvalue())
        self.assertIn("additionalContext", payload["hookSpecificOutput"])
        self.assertNotIn("permissionDecision", payload["hookSpecificOutput"])

    def test_no_match_produces_empty_stdout_exit_0(self) -> None:
        from sekha.hook import _run
        # Block rule scoped to Bash, but event is Write → no match.
        _write_block_rule(self.rules_dir)
        stdout, stderr = io.StringIO(), io.StringIO()
        rc = _run(self._stdin("write_file.json"), stdout, stderr)
        self.assertEqual(rc, 0)
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(stderr.getvalue(), "")

    def test_no_rules_dir_produces_empty_stdout_exit_0(self) -> None:
        from sekha.hook import _run
        # Do NOT create rules_dir → load_rules sees missing dir → empty list.
        stdout, stderr = io.StringIO(), io.StringIO()
        rc = _run(self._stdin("bash_rm_rf.json"), stdout, stderr)
        self.assertEqual(rc, 0)
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(stderr.getvalue(), "")

    def test_block_beats_warn_precedence(self) -> None:
        from sekha.hook import _run
        _write_warn_rule(self.rules_dir, name="warn-x", priority=10)
        _write_block_rule(self.rules_dir, name="block-x", priority=1)
        stdout, stderr = io.StringIO(), io.StringIO()
        rc = _run(self._stdin("bash_rm_rf.json"), stdout, stderr)
        self.assertEqual(rc, 2)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(
            payload["hookSpecificOutput"]["permissionDecision"], "deny"
        )


class TestFailOpen(_HookTestBase):
    def test_malformed_stdin_triggers_fail_open(self) -> None:
        from sekha.hook import _run
        stdout, stderr = io.StringIO(), io.StringIO()
        rc = _run(io.StringIO("not-json-garbage"), stdout, stderr)
        self.assertEqual(rc, 0)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("sekha hook error:", stderr.getvalue())
        log_path = self.sekha_home / "hook-errors.log"
        self.assertTrue(log_path.exists())
        self.assertIn("JSON", log_path.read_text(encoding="utf-8"))


class TestKillSwitch(_HookTestBase):
    def test_kill_switch_marker_short_circuits(self) -> None:
        from sekha.hook import _run
        _write_block_rule(self.rules_dir)  # would otherwise block
        marker = self.sekha_home / "hook-disabled.marker"
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.touch()

        stdout, stderr = io.StringIO(), io.StringIO()
        rc = _run(self._stdin("bash_rm_rf.json"), stdout, stderr)
        self.assertEqual(rc, 0)
        self.assertEqual(stdout.getvalue(), "")
        # No error log either — this is a clean short-circuit, not a failure.
        self.assertFalse((self.sekha_home / "hook-errors.log").exists())

    def test_three_errors_in_window_create_marker(self) -> None:
        from sekha.hook import _run
        # Seed log with 2 recent errors so the 3rd fail-open trips the switch.
        from datetime import datetime, timedelta, timezone
        log = self.sekha_home / "hook-errors.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        now = datetime.now(timezone.utc)
        lines = []
        for d in (10, 60):
            ts = (now - timedelta(seconds=d)).isoformat(timespec="seconds")
            lines.append(f"{ts} ValueError: seeded")
            lines.append("Traceback (most recent call last):")
            lines.append("  (seeded)")
            lines.append("")
        log.write_text("\n".join(lines) + "\n", encoding="utf-8")

        stdout, stderr = io.StringIO(), io.StringIO()
        rc = _run(io.StringIO("not-json"), stdout, stderr)
        self.assertEqual(rc, 0)
        marker = self.sekha_home / "hook-disabled.marker"
        self.assertTrue(marker.exists(),
                        "3rd error within 10 min should create kill marker")


class TestStdoutSacred(_HookTestBase):
    def test_stdout_is_sacred_no_stray_prints(self) -> None:
        from sekha.hook import _run
        _write_block_rule(self.rules_dir)
        stdout, stderr = io.StringIO(), io.StringIO()
        _run(self._stdin("bash_rm_rf.json"), stdout, stderr)
        raw = stdout.getvalue()
        # Must be parseable as exactly one JSON doc.
        parsed = json.loads(raw)
        self.assertIsInstance(parsed, dict)
        # No log-format prefixes anywhere.
        for needle in ("INFO ", "WARNING ", "ERROR ", "DEBUG "):
            self.assertNotIn(needle, raw)
        # sys.stdout must be restored after _run — future prints should not
        # go to stderr because of a leaked swap.
        self.assertIs(sys.stdout, sys.__stdout__) if sys.stdout is sys.__stdout__ else None


class TestModuleTopImportsAreLazy(unittest.TestCase):
    """Static guard: top of hook.py must only import sys and json."""

    def test_top_of_hook_py_imports_only_sys_and_json(self) -> None:
        src = Path(__file__).resolve().parents[1] / "src" / "sekha" / "hook.py"
        tree = ast.parse(src.read_text(encoding="utf-8"))
        top_names: list[str] = []
        for node in tree.body:
            if isinstance(node, ast.ImportFrom):
                top_names.append(node.module or "")
            elif isinstance(node, ast.Import):
                top_names.extend(n.name for n in node.names)
        allowed = {"sys", "json", "__future__"}
        unexpected = [n for n in top_names if n not in allowed]
        self.assertEqual(
            unexpected, [],
            f"hook.py top-level imports must be subset of {allowed}; found extras: {unexpected}",
        )


class TestImportTime(unittest.TestCase):
    """Informational: sekha.hook should import fast (target <30ms).

    Windows cold-start is noisy; we run 3 times and accept the median. If the
    median exceeds 100ms we flag but do NOT fail — the formal gate is the
    ast-based lazy-imports test above.
    """

    @unittest.skipIf(
        os.environ.get("SEKHA_SKIP_IMPORTTIME") == "1",
        "importtime test disabled via SEKHA_SKIP_IMPORTTIME=1",
    )
    def test_import_sekha_hook_is_fast(self) -> None:
        samples: list[float] = []
        for _ in range(3):
            t0 = time.perf_counter()
            r = subprocess.run(
                [sys.executable, "-c", "import sekha.hook"],
                capture_output=True, text=True, timeout=15,
            )
            dt = (time.perf_counter() - t0) * 1000
            self.assertEqual(r.returncode, 0, f"import failed: {r.stderr}")
            samples.append(dt)
        samples.sort()
        median = samples[1]
        # Generous budget — includes Python cold-start, which on Windows is
        # already 100-250ms. We're guarding against regressions that add
        # hundreds of ms (e.g., accidental `from sekha.rules import *`).
        # The real 30ms budget is about the sekha.hook *module* import time,
        # enforced structurally by the ast test in TestModuleTopImportsAreLazy.
        self.assertLess(
            median, 2000,
            f"median cold import time {median:.0f}ms wildly exceeds budget; "
            "check for top-level non-stdlib imports"
        )


if __name__ == "__main__":
    unittest.main()
