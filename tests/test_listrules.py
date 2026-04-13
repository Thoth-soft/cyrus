"""Tests for `cyrus list-rules` (CLI-05).

Plan 06-01 Task 4 -- RED stage. Subcommand not yet wired.

Broken rules (missing severity, unparseable regex, etc.) are flagged with
STATUS=BROKEN rather than crashing the command -- the whole point of
list-rules is to surface the mess so the user can fix it.
"""
from __future__ import annotations

import io
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock


class ListRulesTestBase(unittest.TestCase):
    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)
        self.cyrus_dir = self.tmp / "cyrus"
        self.rules_dir = self.cyrus_dir / "rules"
        self.rules_dir.mkdir(parents=True, exist_ok=True)
        self._env_patch = mock.patch.dict(
            os.environ, {"CYRUS_HOME": str(self.cyrus_dir)}
        )
        self._env_patch.start()

    def tearDown(self) -> None:
        self._env_patch.stop()
        self._td.cleanup()

    def _call(self) -> tuple[int, str, str]:
        from cyrus.cli import main
        stdout = io.StringIO()
        stderr = io.StringIO()
        try:
            with redirect_stdout(stdout), redirect_stderr(stderr):
                rc = main(["list-rules"])
        except SystemExit as exc:
            rc = int(exc.code) if exc.code is not None else 0
        return rc, stdout.getvalue(), stderr.getvalue()

    def _write_valid_rule(self, name: str, severity: str = "block") -> None:
        from cyrus.storage import dump_frontmatter
        meta = {
            "severity": severity,
            "triggers": ["PreToolUse"],
            "matches": ["Bash"],
            "pattern": "rm -rf",
            "priority": 50,
            "message": "nope",
            "anchored": False,
        }
        (self.rules_dir / f"{name}.md").write_text(
            dump_frontmatter(meta, ""), encoding="utf-8"
        )


class TestEmptyDir(ListRulesTestBase):
    def test_empty_dir_prints_header(self) -> None:
        rc, out, _ = self._call()
        self.assertEqual(rc, 0)
        self.assertIn("NAME", out)
        self.assertIn("SEVERITY", out)


class TestValidRules(ListRulesTestBase):
    def test_valid_rules_listed(self) -> None:
        self._write_valid_rule("alpha", "block")
        self._write_valid_rule("bravo", "warn")
        rc, out, _ = self._call()
        self.assertEqual(rc, 0)
        self.assertIn("alpha", out)
        self.assertIn("bravo", out)
        self.assertIn("block", out)
        self.assertIn("warn", out)
        self.assertIn("OK", out)

    def test_output_is_ascii_only(self) -> None:
        self._write_valid_rule("alpha", "block")
        _, out, _ = self._call()
        out.encode("ascii")  # must not raise


class TestBrokenRule(ListRulesTestBase):
    def test_missing_severity_flagged_broken(self) -> None:
        # Intentionally malformed: missing severity
        text = (
            "---\n"
            "triggers: [PreToolUse]\n"
            "matches: [Bash]\n"
            "pattern: rm\n"
            "---\n"
        )
        (self.rules_dir / "oops.md").write_text(text, encoding="utf-8")
        rc, out, _ = self._call()
        self.assertEqual(rc, 0)  # broken rules don't fail the command
        self.assertIn("oops", out)
        self.assertIn("BROKEN", out)

    def test_mix_of_valid_and_broken(self) -> None:
        self._write_valid_rule("good")
        (self.rules_dir / "bad.md").write_text(
            "---\nfoo: bar\n---\n", encoding="utf-8"
        )
        rc, out, _ = self._call()
        self.assertEqual(rc, 0)
        self.assertIn("good", out)
        self.assertIn("OK", out)
        self.assertIn("bad", out)
        self.assertIn("BROKEN", out)


if __name__ == "__main__":
    unittest.main()
