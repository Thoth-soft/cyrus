"""Tests for `sekha init` (sekha._init.run).

Plan 06-01 Task 2 — RED stage. Module `sekha._init` does not yet exist.

Covers CLI-01 (fresh install effects) and CLI-02 (idempotency).

Isolation pattern: each test uses a tempdir for BOTH SEKHA_HOME and a
patched Path.home so `~/.claude/settings.json` is written into the
tempdir rather than the real user home. This is non-negotiable -- without
it the suite would scribble on the developer's live settings.
"""
from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock


def _count_sekha_hook_commands(settings: dict) -> int:
    """Count every entry where command == 'sekha hook run' anywhere under hooks.PreToolUse."""
    total = 0
    pretool = (settings.get("hooks") or {}).get("PreToolUse") or []
    for entry in pretool:
        for h in entry.get("hooks") or []:
            if h.get("command") == "sekha hook run":
                total += 1
    return total


class InitTestBase(unittest.TestCase):
    """Shared scaffolding: tempdir for SEKHA_HOME + patched Path.home."""

    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)
        self.fake_home = self.tmp / "home"
        self.sekha_dir = self.tmp / "sekha"
        self.fake_home.mkdir(parents=True, exist_ok=True)

        self._env_patch = mock.patch.dict(
            os.environ, {"SEKHA_HOME": str(self.sekha_dir)}
        )
        self._home_patch = mock.patch(
            "pathlib.Path.home", return_value=self.fake_home
        )
        self._env_patch.start()
        self._home_patch.start()

    def tearDown(self) -> None:
        self._home_patch.stop()
        self._env_patch.stop()
        self._td.cleanup()

    def _run_init(self, argv: list[str] | None = None) -> tuple[int, str, str]:
        from sekha._init import run
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            rc = run(argv or [])
        return rc, stdout.getvalue(), stderr.getvalue()


class TestFreshInstall(InitTestBase):
    def test_creates_directory_tree(self) -> None:
        rc, _, _ = self._run_init()
        self.assertEqual(rc, 0)
        from sekha.paths import CATEGORIES
        for cat in CATEGORIES:
            self.assertTrue(
                (self.sekha_dir / cat).is_dir(),
                f"{cat} directory missing",
            )

    def test_creates_config_json(self) -> None:
        self._run_init()
        config_path = self.sekha_dir / "config.json"
        self.assertTrue(config_path.exists())
        data = json.loads(config_path.read_text(encoding="utf-8"))
        self.assertIn("version", data)
        self.assertIn("hook_enabled", data)
        self.assertIn("hook_budget_ms", data)

    def test_merges_hook_into_settings_json(self) -> None:
        self._run_init()
        settings_path = self.fake_home / ".claude" / "settings.json"
        self.assertTrue(settings_path.exists())
        data = json.loads(settings_path.read_text(encoding="utf-8"))
        self.assertEqual(_count_sekha_hook_commands(data), 1)

    def test_prints_claude_mcp_add_hint_to_stdout(self) -> None:
        _, out, _ = self._run_init()
        self.assertIn("claude mcp add sekha -- sekha serve", out)

    def test_progress_goes_to_stderr(self) -> None:
        _, out, err = self._run_init()
        # Status lines like "[OK] created ..." belong on stderr.
        self.assertIn("[OK]", err)


class TestIdempotent(InitTestBase):
    def test_second_run_no_duplicates(self) -> None:
        rc1, _, _ = self._run_init()
        rc2, _, _ = self._run_init()
        self.assertEqual(rc1, 0)
        self.assertEqual(rc2, 0)
        settings_path = self.fake_home / ".claude" / "settings.json"
        data = json.loads(settings_path.read_text(encoding="utf-8"))
        self.assertEqual(
            _count_sekha_hook_commands(data),
            1,
            "second init must not duplicate the sekha hook entry",
        )

    def test_config_unchanged_second_run(self) -> None:
        self._run_init()
        config_path = self.sekha_dir / "config.json"
        first = config_path.read_bytes()
        self._run_init()
        second = config_path.read_bytes()
        self.assertEqual(first, second)


class TestBackupOnPreexistingSettings(InitTestBase):
    def test_backup_created_and_user_entries_preserved(self) -> None:
        settings_path = self.fake_home / ".claude" / "settings.json"
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        original = {
            "hooks": {
                "PreToolUse": [
                    {
                        "matcher": "Edit",
                        "hooks": [
                            {"type": "command", "command": "user-linter"}
                        ],
                    }
                ]
            }
        }
        settings_path.write_text(
            json.dumps(original), encoding="utf-8"
        )

        rc, _, _ = self._run_init()
        self.assertEqual(rc, 0)

        # Backup file exists with original content.
        baks = list((self.fake_home / ".claude").glob("settings.json.bak.*"))
        self.assertEqual(len(baks), 1, f"expected 1 backup, got {baks}")
        self.assertEqual(
            json.loads(baks[0].read_text(encoding="utf-8")), original
        )

        # New settings.json contains BOTH user-linter and sekha hook.
        merged = json.loads(settings_path.read_text(encoding="utf-8"))
        commands: list[str] = []
        for entry in merged["hooks"]["PreToolUse"]:
            for h in entry.get("hooks", []):
                commands.append(h.get("command", ""))
        self.assertIn("user-linter", commands)
        self.assertIn("sekha hook run", commands)


class TestHandlesMissingClaudeDir(InitTestBase):
    def test_creates_settings_when_claude_dir_missing(self) -> None:
        claude_dir = self.fake_home / ".claude"
        self.assertFalse(claude_dir.exists())
        rc, _, _ = self._run_init()
        self.assertEqual(rc, 0)
        settings_path = claude_dir / "settings.json"
        self.assertTrue(settings_path.exists())
        data = json.loads(settings_path.read_text(encoding="utf-8"))
        self.assertEqual(_count_sekha_hook_commands(data), 1)
        # No backup file -- nothing to back up.
        baks = list(claude_dir.glob("settings.json.bak.*"))
        self.assertEqual(baks, [])


class TestExistingSekhaDataPreserved(InitTestBase):
    def test_rule_file_unchanged(self) -> None:
        rules_dir = self.sekha_dir / "rules"
        rules_dir.mkdir(parents=True, exist_ok=True)
        rule_path = rules_dir / "my-rule.md"
        payload = b"preexisting rule payload"
        rule_path.write_bytes(payload)
        self._run_init()
        self.assertEqual(rule_path.read_bytes(), payload)


class TestCliIntegration(InitTestBase):
    def test_cli_main_init_dispatches(self) -> None:
        from sekha.cli import main
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            rc = main(["init"])
        self.assertEqual(rc, 0)
        # Same filesystem effects as direct _init.run([])
        for cat in ("sessions", "decisions", "preferences", "projects", "rules"):
            self.assertTrue((self.sekha_dir / cat).is_dir())
        settings_path = self.fake_home / ".claude" / "settings.json"
        data = json.loads(settings_path.read_text(encoding="utf-8"))
        self.assertEqual(_count_sekha_hook_commands(data), 1)


if __name__ == "__main__":
    unittest.main()
