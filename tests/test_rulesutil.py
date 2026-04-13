"""Tests for cyrus._rulesutil: anchoring, flatten, compile, parse, cache-key.

Plan 03-01 Task 1 — RED stage. The helpers under test do not yet exist; this
module's import will fail with ModuleNotFoundError until Task 2 lands
`src/cyrus/_rulesutil.py` alongside the Rule dataclass stub in
`src/cyrus/rules.py`.

Design notes:
- Tests exercise only the private helper surface. Public-API tests live in
  tests/test_rules.py (Plan 03-01 Task 3).
- Rule fixtures are written inline via tempfile.TemporaryDirectory rather than
  reused from tests/fixtures/rules/ — those fixtures are reserved for the
  public-API test suite.
- `_parse_rule_file` returns a `Rule` — we verify fields not by equality on the
  compiled pattern (re.Pattern objects don't compare by equality reliably) but
  by checking raw_pattern and re-running the pattern.
"""
from __future__ import annotations

import os
import re
import tempfile
import time
import unittest
from pathlib import Path

from cyrus._rulesutil import (
    _anchor_pattern,
    _compile_rule_pattern,
    _dir_cache_key,
    _flatten_tool_input,
    _parse_rule_file,
)
from cyrus.rules import Rule


class TestAnchorPattern(unittest.TestCase):
    def test_anchored_wraps_bare_pattern(self):
        self.assertEqual(_anchor_pattern("foo", anchored=True), "^foo$")

    def test_unanchored_returns_pattern_verbatim(self):
        self.assertEqual(_anchor_pattern("foo", anchored=False), "foo")

    def test_anchored_is_idempotent_for_already_anchored(self):
        # Do not double-anchor if user already wrote ^...$
        self.assertEqual(_anchor_pattern("^foo$", anchored=True), "^foo$")

    def test_anchored_idempotent_with_only_start(self):
        self.assertEqual(_anchor_pattern("^foo", anchored=True), "^foo$")

    def test_anchored_idempotent_with_only_end(self):
        self.assertEqual(_anchor_pattern("foo$", anchored=True), "^foo$")


class TestFlattenToolInput(unittest.TestCase):
    def test_empty_dict(self):
        self.assertEqual(_flatten_tool_input({}), "{}")

    def test_flat_dict_is_deterministic(self):
        # sort_keys means the output is stable regardless of insertion order
        a = _flatten_tool_input({"command": "rm -rf /", "cwd": "/"})
        b = _flatten_tool_input({"cwd": "/", "command": "rm -rf /"})
        self.assertEqual(a, b)

    def test_flat_dict_contains_values(self):
        out = _flatten_tool_input({"command": "rm -rf /", "cwd": "/tmp"})
        self.assertIn("rm -rf /", out)
        self.assertIn("/tmp", out)

    def test_nested_values_are_serialized(self):
        out = _flatten_tool_input({"nested": {"a": 1, "cmd": "drop table"}})
        self.assertIn("drop table", out)
        self.assertIn("1", out)

    def test_list_values_are_serialized(self):
        out = _flatten_tool_input({"argv": ["rm", "-rf", "/"]})
        self.assertIn("rm", out)
        self.assertIn("-rf", out)


class TestCompileRulePattern(unittest.TestCase):
    def test_compiles_to_re_pattern(self):
        pat = _compile_rule_pattern(r"rm\s+-rf", anchored=False)
        self.assertIsInstance(pat, re.Pattern)

    def test_anchored_semantics_enforced(self):
        pat = _compile_rule_pattern("rm -rf", anchored=True)
        self.assertIsNone(pat.search("sudo rm -rf /"))
        self.assertIsNotNone(pat.search("rm -rf"))

    def test_unanchored_allows_substring(self):
        pat = _compile_rule_pattern(r"rm\s+-rf", anchored=False)
        self.assertIsNotNone(pat.search("sudo rm -rf /"))

    def test_case_insensitive(self):
        pat = _compile_rule_pattern(r"rm\s+-rf", anchored=False)
        self.assertIsNotNone(pat.search("RM -RF /tmp"))

    def test_invalid_regex_raises_re_error(self):
        with self.assertRaises(re.error):
            _compile_rule_pattern("[unclosed", anchored=True)


class TestParseRuleFile(unittest.TestCase):
    def _write(self, dir_: Path, name: str, content: str) -> Path:
        p = dir_ / name
        p.write_text(content, encoding="utf-8")
        return p

    def test_valid_rule_parses_to_rule_instance(self):
        with tempfile.TemporaryDirectory() as td:
            p = self._write(
                Path(td),
                "block-rm.md",
                "---\n"
                "severity: block\n"
                "triggers: [PreToolUse]\n"
                "matches: [Bash]\n"
                "pattern: 'rm\\s+-rf'\n"
                "priority: 50\n"
                "anchored: false\n"
                "---\n"
                "Do not run rm -rf.\n",
            )
            rule = _parse_rule_file(p)
        self.assertIsInstance(rule, Rule)
        self.assertEqual(rule.name, "block-rm")
        self.assertEqual(rule.severity, "block")
        self.assertEqual(rule.priority, 50)
        self.assertFalse(rule.anchored)
        self.assertIn("PreToolUse", rule.triggers)
        self.assertIn("Bash", rule.matches)
        # Compiled pattern honors anchored=false
        self.assertIsNotNone(rule.pattern.search("sudo rm -rf /"))

    def test_missing_severity_raises_value_error(self):
        with tempfile.TemporaryDirectory() as td:
            p = self._write(
                Path(td),
                "bad.md",
                "---\n"
                "triggers: [PreToolUse]\n"
                "matches: [Bash]\n"
                "pattern: 'foo'\n"
                "---\n"
                "body\n",
            )
            with self.assertRaises(ValueError) as ctx:
                _parse_rule_file(p)
            self.assertIn("severity", str(ctx.exception))

    def test_missing_pattern_raises_value_error(self):
        with tempfile.TemporaryDirectory() as td:
            p = self._write(
                Path(td),
                "bad.md",
                "---\n"
                "severity: block\n"
                "triggers: [PreToolUse]\n"
                "matches: [Bash]\n"
                "---\n"
                "body\n",
            )
            with self.assertRaises(ValueError) as ctx:
                _parse_rule_file(p)
            self.assertIn("pattern", str(ctx.exception))

    def test_bad_severity_value_raises_value_error(self):
        with tempfile.TemporaryDirectory() as td:
            p = self._write(
                Path(td),
                "bad.md",
                "---\n"
                "severity: sometimes\n"
                "triggers: [PreToolUse]\n"
                "matches: [Bash]\n"
                "pattern: 'foo'\n"
                "---\n"
                "body\n",
            )
            with self.assertRaises(ValueError) as ctx:
                _parse_rule_file(p)
            self.assertIn("severity", str(ctx.exception))

    def test_broken_regex_raises_value_error(self):
        with tempfile.TemporaryDirectory() as td:
            p = self._write(
                Path(td),
                "bad.md",
                "---\n"
                "severity: block\n"
                "triggers: [PreToolUse]\n"
                "matches: [Bash]\n"
                "pattern: '[unclosed'\n"
                "---\n"
                "body\n",
            )
            with self.assertRaises(ValueError) as ctx:
                _parse_rule_file(p)
            msg = str(ctx.exception).lower()
            self.assertTrue("pattern" in msg or "regex" in msg)

    def test_defaults_when_optional_fields_missing(self):
        with tempfile.TemporaryDirectory() as td:
            p = self._write(
                Path(td),
                "default.md",
                "---\n"
                "severity: warn\n"
                "triggers: [PreToolUse]\n"
                "matches: [Bash]\n"
                "pattern: 'foo'\n"
                "---\n"
                "Default rule body.\n",
            )
            rule = _parse_rule_file(p)
        self.assertEqual(rule.priority, 0)
        self.assertTrue(rule.anchored)
        self.assertIn("Default rule body", rule.message)


class TestDirCacheKey(unittest.TestCase):
    def test_empty_dir_returns_zero_tuple(self):
        with tempfile.TemporaryDirectory() as td:
            key = _dir_cache_key(Path(td))
        self.assertEqual(key, (0, 0.0))

    def test_missing_dir_returns_zero_tuple(self):
        # Non-existent dir — must not raise
        key = _dir_cache_key(Path(tempfile.gettempdir()) / "cyrus-nope-xyz-12345")
        self.assertEqual(key, (0, 0.0))

    def test_key_changes_when_file_added(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            (d / "a.md").write_text("x")
            k1 = _dir_cache_key(d)
            # New file → both count and mtime change
            time.sleep(0.02)
            (d / "b.md").write_text("y")
            k2 = _dir_cache_key(d)
            self.assertNotEqual(k1, k2)
            self.assertEqual(k2[0], 2)

    def test_key_changes_when_mtime_bumped(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            p = d / "a.md"
            p.write_text("x")
            k1 = _dir_cache_key(d)
            future = time.time() + 120.0
            os.utime(p, (future, future))
            k2 = _dir_cache_key(d)
            self.assertNotEqual(k1, k2)


if __name__ == "__main__":
    unittest.main()
