"""Tests for `sekha add-rule` (CLI-04).

Plan 06-01 Task 4 -- RED stage. Subcommand is not yet registered on cli.py.

Every test isolates SEKHA_HOME via a tempdir so rule file writes never
touch the developer's real ~/.sekha/rules/.
"""
from __future__ import annotations

import io
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock


class AddRuleTestBase(unittest.TestCase):
    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)
        self.sekha_dir = self.tmp / "sekha"
        self.sekha_dir.mkdir(parents=True, exist_ok=True)
        self._env_patch = mock.patch.dict(
            os.environ, {"SEKHA_HOME": str(self.sekha_dir)}
        )
        self._env_patch.start()

    def tearDown(self) -> None:
        self._env_patch.stop()
        self._td.cleanup()

    def _call(self, *args: str) -> tuple[int, str, str]:
        """Invoke `sekha.cli.main(['add-rule', *args])` with captured streams."""
        from sekha.cli import main
        stdout = io.StringIO()
        stderr = io.StringIO()
        try:
            with redirect_stdout(stdout), redirect_stderr(stderr):
                rc = main(["add-rule", *args])
        except SystemExit as exc:
            rc = int(exc.code) if exc.code is not None else 0
        return rc, stdout.getvalue(), stderr.getvalue()

    @property
    def rules_dir(self) -> Path:
        return self.sekha_dir / "rules"


class TestValidRule(AddRuleTestBase):
    def test_creates_file_with_frontmatter(self) -> None:
        rc, _, _ = self._call(
            "--name", "demo",
            "--severity", "block",
            "--matches", "Bash",
            "--pattern", "rm -rf",
            "--message", "nope",
        )
        self.assertEqual(rc, 0)
        path = self.rules_dir / "demo.md"
        self.assertTrue(path.exists())
        text = path.read_text(encoding="utf-8")
        self.assertIn("severity: block", text)
        # Matches is a list
        self.assertIn("Bash", text)
        self.assertIn("pattern:", text)

    def test_parseable_via_existing_loader(self) -> None:
        self._call(
            "--name", "demo2",
            "--severity", "block",
            "--matches", "Bash",
            "--pattern", "rm -rf",
            "--message", "nope",
        )
        from sekha._rulesutil import _parse_rule_file
        path = self.rules_dir / "demo2.md"
        rule = _parse_rule_file(path)
        self.assertEqual(rule.severity, "block")
        self.assertIn("Bash", rule.matches)
        self.assertEqual(rule.raw_pattern, "rm -rf")

    def test_default_triggers_and_priority(self) -> None:
        self._call(
            "--name", "demo3",
            "--severity", "warn",
            "--matches", "Bash",
            "--pattern", "git commit",
            "--message", "m",
        )
        text = (self.rules_dir / "demo3.md").read_text(encoding="utf-8")
        self.assertIn("PreToolUse", text)
        self.assertIn("priority: 50", text)


class TestInvalidRegex(AddRuleTestBase):
    def test_invalid_regex_rejected(self) -> None:
        rc, _, err = self._call(
            "--name", "badregex",
            "--severity", "block",
            "--matches", "Bash",
            "--pattern", "[unclosed",
            "--message", "m",
        )
        self.assertNotEqual(rc, 0)
        # Stderr mentions regex or compile or pattern.
        combined = err.lower()
        self.assertTrue(
            "regex" in combined or "compile" in combined or "pattern" in combined,
            f"expected regex error on stderr, got: {err!r}",
        )
        # No file written.
        self.assertFalse((self.rules_dir / "badregex.md").exists())


class TestInvalidSeverity(AddRuleTestBase):
    def test_panic_severity_rejected(self) -> None:
        # argparse choices enforcement -> SystemExit 2.
        rc, _, _ = self._call(
            "--name", "demo",
            "--severity", "panic",
            "--matches", "Bash",
            "--pattern", "x",
            "--message", "m",
        )
        self.assertNotEqual(rc, 0)


class TestNameCollision(AddRuleTestBase):
    def test_collision_rejected(self) -> None:
        self.rules_dir.mkdir(parents=True, exist_ok=True)
        existing = self.rules_dir / "demo.md"
        existing.write_text("original", encoding="utf-8")
        rc, _, err = self._call(
            "--name", "demo",
            "--severity", "warn",
            "--matches", "Bash",
            "--pattern", "x",
            "--message", "m",
        )
        self.assertNotEqual(rc, 0)
        self.assertIn("exist", err.lower())
        # Original untouched.
        self.assertEqual(existing.read_text(encoding="utf-8"), "original")


class TestNameSlug(AddRuleTestBase):
    def test_invalid_name_rejected(self) -> None:
        rc, _, err = self._call(
            "--name", "bad name!",
            "--severity", "warn",
            "--matches", "Bash",
            "--pattern", "x",
            "--message", "m",
        )
        self.assertNotEqual(rc, 0)
        # Stderr should mention naming rules (lowercase, hyphens, chars).
        self.assertTrue(
            "name" in err.lower() or "char" in err.lower() or "alnum" in err.lower(),
            f"expected naming-rule stderr, got: {err!r}",
        )


if __name__ == "__main__":
    unittest.main()
