"""Tests for sekha.cli: argparse router for `sekha hook run|bench|enable|disable`.

Plan 04-01 Task 3 — RED stage. Module does not yet exist. GREEN step lands
`src/sekha/cli.py` satisfying the existing `[project.scripts] sekha = sekha.cli:main`
console script entry point.

`main(argv)` accepts an explicit argv list so tests never mutate sys.argv.
Subcommand modules (sekha.hook) are lazy-imported inside main() so the CLI
startup cost stays low for Phase 6 subcommands (doctor, init, add-rule) that
don't need hook imports.
"""
from __future__ import annotations

import importlib.metadata
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock


class TestNoArgs(unittest.TestCase):
    def test_no_args_prints_usage_and_exits_nonzero(self) -> None:
        from sekha.cli import main
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            with self.assertRaises(SystemExit) as ctx:
                main([])
        # argparse exits 2 on missing required subcommand
        self.assertNotEqual(ctx.exception.code, 0)
        self.assertIn("usage", stderr.getvalue().lower())


class TestHookSubcommand(unittest.TestCase):
    def test_hook_with_no_sub_prints_usage(self) -> None:
        from sekha.cli import main
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            with self.assertRaises(SystemExit) as ctx:
                main(["hook"])
        self.assertNotEqual(ctx.exception.code, 0)
        combined = stderr.getvalue().lower()
        self.assertTrue(
            "usage" in combined or "required" in combined,
            f"expected usage message, got: {combined!r}",
        )

    def test_hook_run_dispatches_to_hook_main(self) -> None:
        from sekha import cli
        sentinel = mock.Mock(return_value=0)
        with mock.patch("sekha.hook.main", sentinel):
            rc = cli.main(["hook", "run"])
        self.assertEqual(rc, 0)
        sentinel.assert_called_once()

    def test_hook_enable_dispatches_to_hook_enable(self) -> None:
        from sekha import cli
        sentinel = mock.Mock(return_value=0)
        with mock.patch("sekha.hook.enable", sentinel):
            rc = cli.main(["hook", "enable"])
        self.assertEqual(rc, 0)
        sentinel.assert_called_once()

    def test_hook_disable_dispatches_to_hook_disable(self) -> None:
        from sekha import cli
        sentinel = mock.Mock(return_value=0)
        with mock.patch("sekha.hook.disable", sentinel):
            rc = cli.main(["hook", "disable"])
        self.assertEqual(rc, 0)
        sentinel.assert_called_once()

    def test_hook_bench_registered_as_placeholder(self) -> None:
        """`sekha hook bench --help` must exit 0 and mention 'bench'.
        Running `sekha hook bench` (no --help) before plan 04-02 returns
        a friendly "not yet implemented" message on stderr and a non-zero
        exit code, not a traceback.
        """
        from sekha.cli import main
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            with self.assertRaises(SystemExit) as ctx:
                main(["hook", "bench", "--help"])
        self.assertEqual(ctx.exception.code, 0)
        self.assertIn("bench", stdout.getvalue().lower())

    def test_hook_bench_without_impl_returns_friendly_error(self) -> None:
        from sekha import cli
        stderr = io.StringIO()
        # Simulate sekha.hook lacking bench by patching ImportError.
        original_hook = sys.modules.get("sekha.hook")
        try:
            import sekha.hook as hook_mod
            # Remove bench attr if it exists to simulate pre-04-02 state.
            had_bench = hasattr(hook_mod, "bench")
            saved = getattr(hook_mod, "bench", None)
            if had_bench:
                delattr(hook_mod, "bench")
            try:
                with redirect_stderr(stderr):
                    rc = cli.main(["hook", "bench"])
                self.assertNotEqual(rc, 0)
                self.assertIn("not yet implemented", stderr.getvalue().lower())
            finally:
                if had_bench:
                    hook_mod.bench = saved  # type: ignore[attr-defined]
        finally:
            # Do not unload sekha.hook — other tests rely on it.
            sys.modules["sekha.hook"] = original_hook  # type: ignore[assignment]


class TestConsoleScript(unittest.TestCase):
    def test_console_script_entry_resolves(self) -> None:
        """The `sekha` entry point in pyproject.toml must resolve to sekha.cli:main."""
        eps = importlib.metadata.entry_points()
        # Python 3.11+: entry_points() returns an EntryPoints object with select().
        scripts = eps.select(group="console_scripts")
        matches = [ep for ep in scripts if ep.name == "sekha"]
        self.assertTrue(matches, "no `sekha` console script entry point found")
        ep = matches[0]
        self.assertEqual(ep.value, "sekha.cli:main",
                         f"expected sekha.cli:main, got {ep.value}")


class TestArgvParam(unittest.TestCase):
    def test_main_accepts_argv_param_for_testing(self) -> None:
        """`main(argv=...)` must not mutate sys.argv and must dispatch."""
        from sekha import cli
        sentinel = mock.Mock(return_value=0)
        original_argv = list(sys.argv)
        with mock.patch("sekha.hook.main", sentinel):
            rc = cli.main(argv=["hook", "run"])
        self.assertEqual(rc, 0)
        self.assertEqual(sys.argv, original_argv, "sys.argv must not be mutated")
        sentinel.assert_called_once()


class TestSubprocessRoundTrip(unittest.TestCase):
    def test_subprocess_sekha_hook_run_round_trip(self) -> None:
        """End-to-end: invoke `python -m sekha.cli hook run` with a benign
        PreToolUse event on stdin and an empty SEKHA_HOME. Expect exit 0
        and empty stdout (no rules → allow).
        """
        with tempfile.TemporaryDirectory() as tmp:
            env = os.environ.copy()
            env["SEKHA_HOME"] = tmp
            payload = json.dumps({
                "session_id": "t",
                "transcript_path": "/tmp/t",
                "cwd": ".",
                "permission_mode": "default",
                "hook_event_name": "PreToolUse",
                "tool_name": "Bash",
                "tool_input": {"command": "ls -la"},
                "tool_use_id": "1",
            })
            r = subprocess.run(
                [sys.executable, "-m", "sekha.cli", "hook", "run"],
                input=payload, capture_output=True, text=True,
                env=env, timeout=30,
            )
            self.assertEqual(r.returncode, 0,
                             f"stderr={r.stderr!r} stdout={r.stdout!r}")
            self.assertEqual(r.stdout, "",
                             f"stdout must be empty (allow), got: {r.stdout!r}")


if __name__ == "__main__":
    unittest.main()
