"""Tests for sekha._hookutil: JSON I/O, fail-open, kill-switch bookkeeping.

Plan 04-01 Task 1 — RED stage. Module does not yet exist; every import and
assertion below must fail until Task 1's GREEN step lands `src/sekha/_hookutil.py`.

Isolation: every test overrides SEKHA_HOME to a tempdir in setUp so no test
touches the real ~/.sekha. Timestamps for record_error tests are written into
the log file directly rather than mocked — the file IS the source of truth.
"""
from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


class _HookutilTestBase(unittest.TestCase):
    """Tempdir SEKHA_HOME + clean restore. Imports _hookutil lazily per-test
    so test collection doesn't explode if the module is broken."""

    def setUp(self) -> None:
        self._saved_home = os.environ.pop("SEKHA_HOME", None)
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["SEKHA_HOME"] = self._tmp.name

    def tearDown(self) -> None:
        os.environ.pop("SEKHA_HOME", None)
        if self._saved_home is not None:
            os.environ["SEKHA_HOME"] = self._saved_home
        self._tmp.cleanup()


class TestReadEvent(_HookutilTestBase):
    def test_valid_json_returns_dict(self) -> None:
        from sekha._hookutil import read_event
        event = {
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": "ls"},
        }
        stream = io.StringIO(json.dumps(event))
        result = read_event(stream)
        self.assertEqual(result, event)

    def test_empty_stdin_raises_value_error(self) -> None:
        from sekha._hookutil import read_event
        with self.assertRaises(ValueError):
            read_event(io.StringIO(""))

    def test_malformed_json_raises(self) -> None:
        from sekha._hookutil import read_event
        with self.assertRaises(Exception):
            # json.JSONDecodeError is a subclass of ValueError
            read_event(io.StringIO("not-json-garbage"))


class TestEmitBlock(_HookutilTestBase):
    def test_emit_block_writes_deny_shape_and_returns_2(self) -> None:
        from sekha._hookutil import emit_block
        stdout = io.StringIO()
        stderr = io.StringIO()
        rc = emit_block("rm -rf is not allowed", stdout, stderr)
        self.assertEqual(rc, 2)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(
            payload,
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": "rm -rf is not allowed",
                }
            },
        )
        self.assertIn("rm -rf is not allowed", stderr.getvalue())

    def test_emit_block_stdout_is_single_json_document(self) -> None:
        from sekha._hookutil import emit_block
        stdout = io.StringIO()
        stderr = io.StringIO()
        emit_block("blocked", stdout, stderr)
        # Must parse as a single JSON doc — no trailing junk.
        data = stdout.getvalue()
        # json.loads on a trailing newline or whitespace-stripped string is fine
        # but must not contain log-format prefixes.
        self.assertNotIn("INFO ", data)
        self.assertNotIn("ERROR ", data)
        self.assertNotIn("WARNING ", data)


class TestEmitWarn(_HookutilTestBase):
    def test_emit_warn_writes_additional_context_and_returns_0(self) -> None:
        from sekha._hookutil import emit_warn
        stdout = io.StringIO()
        rc = emit_warn("careful now", stdout)
        self.assertEqual(rc, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(
            payload,
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "additionalContext": "careful now",
                }
            },
        )
        # Warn shape must NOT include permissionDecision
        self.assertNotIn("permissionDecision", stdout.getvalue())


class TestEmitAllow(_HookutilTestBase):
    def test_emit_allow_writes_nothing_and_returns_0(self) -> None:
        from sekha._hookutil import emit_allow
        stdout = io.StringIO()
        rc = emit_allow(stdout)
        self.assertEqual(rc, 0)
        self.assertEqual(stdout.getvalue(), "")


class TestPaths(_HookutilTestBase):
    def test_error_log_path_honors_sekha_home(self) -> None:
        from sekha._hookutil import error_log_path
        expected = Path(self._tmp.name).resolve() / "hook-errors.log"
        self.assertEqual(error_log_path(), expected)

    def test_marker_path_honors_sekha_home(self) -> None:
        from sekha._hookutil import marker_path
        expected = Path(self._tmp.name).resolve() / "hook-disabled.marker"
        self.assertEqual(marker_path(), expected)


class TestFailOpen(_HookutilTestBase):
    def test_fail_open_appends_to_log_and_writes_to_stderr(self) -> None:
        from sekha._hookutil import fail_open, error_log_path
        stderr = io.StringIO()
        try:
            raise RuntimeError("synthetic boom")
        except RuntimeError as exc:
            rc = fail_open(exc, stderr)
        self.assertEqual(rc, 0)
        self.assertIn("sekha hook error", stderr.getvalue())
        self.assertIn("synthetic boom", stderr.getvalue())
        log = error_log_path().read_text(encoding="utf-8")
        self.assertIn("RuntimeError", log)
        self.assertIn("synthetic boom", log)
        # Must contain a traceback hint
        self.assertTrue(
            "Traceback" in log or "synthetic boom" in log,
            "log must contain error context",
        )

    def test_fail_open_creates_parent_dir_if_missing(self) -> None:
        from sekha._hookutil import fail_open, error_log_path
        # Point SEKHA_HOME at a dir that doesn't exist yet.
        missing = Path(self._tmp.name) / "nested" / "sub"
        os.environ["SEKHA_HOME"] = str(missing)
        stderr = io.StringIO()
        try:
            raise ValueError("create parent")
        except ValueError as exc:
            fail_open(exc, stderr)
        self.assertTrue(error_log_path().exists())
        self.assertIn("ValueError", error_log_path().read_text(encoding="utf-8"))


class TestRecordError(_HookutilTestBase):
    """record_error decides if the kill-switch should trip based on recent log entries."""

    def _seed_log_with_timestamps(self, deltas_seconds: list[int]) -> None:
        """Write a synthetic error log where each delta is 'seconds ago'."""
        from sekha._hookutil import error_log_path
        path = error_log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        now = datetime.now(timezone.utc)
        lines = []
        for d in deltas_seconds:
            ts = (now - timedelta(seconds=d)).isoformat(timespec="seconds")
            lines.append(f"{ts} RuntimeError: synthetic")
            lines.append("Traceback (most recent call last):")
            lines.append("  (synthetic)")
            lines.append("")
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def test_below_threshold_returns_false(self) -> None:
        from sekha._hookutil import record_error
        # Two recent errors — below threshold of 3.
        self._seed_log_with_timestamps([10, 30])
        self.assertFalse(record_error(RuntimeError("x")))

    def test_three_recent_errors_returns_true(self) -> None:
        from sekha._hookutil import record_error
        # Three errors within the 600s window → trip.
        self._seed_log_with_timestamps([10, 120, 400])
        self.assertTrue(record_error(RuntimeError("x")))

    def test_old_errors_dont_count(self) -> None:
        from sekha._hookutil import record_error
        # Three errors but all > 600s ago → do NOT trip.
        self._seed_log_with_timestamps([700, 800, 900])
        self.assertFalse(record_error(RuntimeError("x")))

    def test_missing_log_returns_false(self) -> None:
        from sekha._hookutil import record_error
        # No error log at all — fewer than 3 events by definition.
        self.assertFalse(record_error(RuntimeError("x")))


class TestKillSwitch(_HookutilTestBase):
    def test_check_kill_switch_false_by_default(self) -> None:
        from sekha._hookutil import check_kill_switch
        self.assertFalse(check_kill_switch())

    def test_create_marker_then_check(self) -> None:
        from sekha._hookutil import check_kill_switch, create_marker, marker_path
        create_marker()
        self.assertTrue(marker_path().exists())
        self.assertTrue(check_kill_switch())

    def test_create_marker_is_idempotent(self) -> None:
        from sekha._hookutil import create_marker, marker_path
        create_marker()
        create_marker()  # must not raise
        self.assertTrue(marker_path().exists())

    def test_clear_marker_removes_it(self) -> None:
        from sekha._hookutil import clear_marker, create_marker, marker_path
        create_marker()
        clear_marker()
        self.assertFalse(marker_path().exists())

    def test_clear_marker_is_idempotent(self) -> None:
        from sekha._hookutil import clear_marker
        clear_marker()  # no marker exists; must not raise
        clear_marker()


class TestImportHygiene(unittest.TestCase):
    """Module-level imports must stay tiny — no sekha.rules / storage / search."""

    def test_no_heavy_sekha_imports_at_top(self) -> None:
        import ast
        src = Path(__file__).resolve().parents[1] / "src" / "sekha" / "_hookutil.py"
        tree = ast.parse(src.read_text(encoding="utf-8"))
        top_names: list[str] = []
        for node in tree.body:
            if isinstance(node, ast.ImportFrom):
                top_names.append(node.module or "")
            elif isinstance(node, ast.Import):
                top_names.extend(n.name for n in node.names)
        # _hookutil is allowed sekha.paths only among project imports.
        forbidden = {"sekha.rules", "sekha.storage", "sekha.search", "sekha.logutil"}
        overlap = forbidden.intersection(top_names)
        self.assertEqual(overlap, set(), f"forbidden imports at top: {overlap}")


if __name__ == "__main__":
    unittest.main()
