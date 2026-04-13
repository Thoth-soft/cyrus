"""Tests for sekha.rules public API: load_rules, evaluate, test_rule, clear_cache.

Plan 03-01 Task 3 — RED stage. Task 2 delivered a Rule dataclass stub only;
this module imports names (load_rules, evaluate, test_rule, clear_cache) that
do not yet exist. Task 4's GREEN implementation makes these tests pass.

Coverage map (RULES-01..08):
- RULES-01 / RULES-02: TestLoading — valid rules load, invalid rules are loudly
  skipped (never silenced) with stderr naming each defective file.
- RULES-03: TestWildcardAndScoping — matches=[*] fires for any tool; Edit-only
  rules don't fire on Bash.
- RULES-04: TestAnchoring — anchored=true vs anchored=false semantics on real
  tool_input flattening.
- RULES-05: TestPrecedence — block > warn; priority ties broken by filename
  order; tie log to stderr lists both rule names.
- RULES-06: TestCache — second load_rules is a cache hit; mtime bump
  invalidates; clear_cache forces re-parse.
- RULES-07: TestDryRun — test_rule returns a structured dict; FileNotFoundError
  on missing rule name.
- RULES-08: TestPause — SEKHA_PAUSE env var (single and CSV) suppresses rules.

Test isolation:
- Every TestCase clears sekha.rules._CACHE in setUp + save/restore SEKHA_PAUSE.
- Fixtures live in tests/fixtures/rules/ (committed alongside this file).
- test_rule touches ~/.sekha/rules/ via sekha.paths.category_dir — we override
  SEKHA_HOME to a tempdir for those tests and copy fixtures in.
"""
from __future__ import annotations

import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path

from sekha.rules import (
    Rule,
    clear_cache,
    evaluate,
    load_rules,
    test_rule,
)

FIXTURES = Path(__file__).parent / "fixtures" / "rules"


class _RulesTestBase(unittest.TestCase):
    """Mixin-ish base: clears cache + snapshots SEKHA_PAUSE per test."""

    def setUp(self) -> None:
        clear_cache()
        self._saved_pause = os.environ.pop("SEKHA_PAUSE", None)

    def tearDown(self) -> None:
        if self._saved_pause is not None:
            os.environ["SEKHA_PAUSE"] = self._saved_pause
        else:
            os.environ.pop("SEKHA_PAUSE", None)
        clear_cache()


class TestLoading(_RulesTestBase):
    """RULES-01, RULES-02: frontmatter parse + strict error handling."""

    def test_load_rules_for_bash_returns_rule_instances(self):
        rules = load_rules(FIXTURES, "PreToolUse", "Bash")
        self.assertTrue(len(rules) >= 7)
        for r in rules:
            self.assertIsInstance(r, Rule)

    def test_load_rules_excludes_rules_not_matching_tool(self):
        # Edit-only: only rules with Edit in matches (or wildcard) show up.
        rules = load_rules(FIXTURES, "PreToolUse", "Edit")
        names = {r.name for r in rules}
        # warn-no-tests matches [Edit, Write]; warn-todo-comments is wildcard
        self.assertIn("warn-no-tests", names)
        self.assertIn("warn-todo-comments", names)
        # block-rm-rf is Bash-only — must NOT appear
        self.assertNotIn("block-rm-rf", names)

    def test_invalid_rules_are_skipped(self):
        rules = load_rules(FIXTURES, "PreToolUse", "Bash")
        names = {r.name for r in rules}
        self.assertNotIn("invalid-missing-severity", names)
        self.assertNotIn("invalid-bad-regex", names)
        self.assertNotIn("invalid-bad-severity", names)

    def test_invalid_rules_logged_loudly_to_stderr(self):
        # sekha.logutil attaches a StreamHandler bound to sys.stderr at logger
        # configure time — contextlib.redirect_stderr rebinds sys.stderr for
        # the caller but does not reach back through the handler reference.
        # assertLogs is the idiomatic capture for logger.error()/warning() in
        # unittest; it also happens to match the stderr delivery path because
        # the handler is the only path out and it's formatted the same.
        with self.assertLogs("sekha.rules", level="ERROR") as cm:
            load_rules(FIXTURES, "PreToolUse", "Bash")
        joined = "\n".join(cm.output)
        # Each of the three defective files must appear by name
        self.assertIn("invalid-missing-severity", joined)
        self.assertIn("invalid-bad-regex", joined)
        self.assertIn("invalid-bad-severity", joined)

    def test_no_matching_trigger_returns_empty(self):
        rules = load_rules(FIXTURES, "PostToolUse", "Bash")
        self.assertEqual(rules, [])

    def test_missing_dir_returns_empty(self):
        rules = load_rules(FIXTURES.parent / "does-not-exist", "PreToolUse", "Bash")
        self.assertEqual(rules, [])


class TestWildcardAndScoping(_RulesTestBase):
    """RULES-03: wildcard * in matches."""

    def test_wildcard_rule_fires_for_any_tool(self):
        for tool in ("Bash", "Edit", "Read", "Grep"):
            rules = load_rules(FIXTURES, "PreToolUse", tool)
            names = {r.name for r in rules}
            self.assertIn("warn-todo-comments", names, f"wildcard missing for {tool}")

    def test_explicit_tool_list_excludes_other_tools(self):
        rules = load_rules(FIXTURES, "PreToolUse", "Read")
        names = {r.name for r in rules}
        # warn-no-tests is [Edit, Write] — not Read
        self.assertNotIn("warn-no-tests", names)


class TestAnchoring(_RulesTestBase):
    """RULES-04: anchored-by-default regex, opt-out via anchored: false."""

    def test_unanchored_fixture_matches_substring(self):
        # block-rm-rf is anchored: false with pattern 'rm\s+-rf'
        rules = load_rules(FIXTURES, "PreToolUse", "Bash")
        rule = next(r for r in rules if r.name == "block-rm-rf")
        winner = evaluate([rule], {"command": "rm -rf /tmp/x"})
        self.assertIsNotNone(winner)
        self.assertEqual(winner.name, "block-rm-rf")

    def test_anchored_by_default_refuses_substring(self):
        # Build a Rule with default anchoring (anchored=True implicit) via a
        # tempdir — the fixtures are all anchored: false for substring work.
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "exact.md"
            p.write_text(
                "---\n"
                "severity: block\n"
                "triggers: [PreToolUse]\n"
                "matches: [Bash]\n"
                "pattern: 'rm -rf'\n"
                "priority: 10\n"
                "---\n"
                "Only exact match.\n",
                encoding="utf-8",
            )
            rules = load_rules(Path(td), "PreToolUse", "Bash")
            self.assertEqual(len(rules), 1)
            # Flattened JSON is '{"command": "sudo rm -rf /"}' which contains
            # '"sudo rm -rf /"' — anchored ^rm -rf$ won't match that substring.
            winner = evaluate(rules, {"command": "sudo rm -rf /"})
            self.assertIsNone(winner)


class TestPrecedence(_RulesTestBase):
    """RULES-05: block > warn, priority, first-match ties + stderr tie log."""

    def _make_rule(
        self,
        name: str,
        severity: str,
        priority: int,
        pattern: str = ".*",
        anchored: bool = False,
    ) -> Rule:
        import re as _re
        return Rule(
            name=name,
            severity=severity,
            triggers=("PreToolUse",),
            matches=("Bash",),
            pattern=_re.compile(pattern, _re.IGNORECASE),
            priority=priority,
            message=f"msg for {name}",
            raw_pattern=pattern,
            anchored=anchored,
        )

    def test_block_beats_warn_regardless_of_priority(self):
        block_lo = self._make_rule("block-lo", "block", priority=1)
        warn_hi = self._make_rule("warn-hi", "warn", priority=100)
        winner = evaluate([warn_hi, block_lo], {"command": "anything"})
        self.assertEqual(winner.name, "block-lo")

    def test_higher_priority_wins_within_same_severity(self):
        a = self._make_rule("a-block", "block", priority=5)
        b = self._make_rule("b-block", "block", priority=10)
        winner = evaluate([a, b], {"command": "anything"})
        self.assertEqual(winner.name, "b-block")

    def test_tie_breaks_by_first_in_list_and_logs_both_names(self):
        a = self._make_rule("alpha-block", "block", priority=10)
        b = self._make_rule("beta-block", "block", priority=10)
        # assertLogs captures the logger's formatted output, which is what
        # sekha.logutil sends to stderr — same bytes, different capture path.
        with self.assertLogs("sekha.rules", level="WARNING") as cm:
            # Pass alpha first — load_rules returns filename-sorted so alpha wins
            winner = evaluate([a, b], {"command": "anything"})
        self.assertEqual(winner.name, "alpha-block")
        joined = "\n".join(cm.output).lower()
        self.assertIn("alpha-block", joined)
        self.assertIn("beta-block", joined)
        self.assertIn("tie", joined)

    def test_no_match_returns_none(self):
        rule = self._make_rule("nomatch", "block", priority=10, pattern="xyzzy", anchored=True)
        self.assertIsNone(evaluate([rule], {"command": "ls"}))

    def test_empty_rules_returns_none(self):
        self.assertIsNone(evaluate([], {"command": "anything"}))

    def test_full_flow_rm_rf_blocks(self):
        rules = load_rules(FIXTURES, "PreToolUse", "Bash")
        winner = evaluate(rules, {"command": "rm -rf /"})
        self.assertIsNotNone(winner)
        self.assertEqual(winner.name, "block-rm-rf")


class TestCache(_RulesTestBase):
    """RULES-06: compile cache hit/miss/invalidation."""

    def test_second_call_hits_cache(self):
        # Snapshot the internal cache state by poking the module
        import sekha.rules as rules_mod

        clear_cache()
        self.assertEqual(len(rules_mod._CACHE), 0)
        load_rules(FIXTURES, "PreToolUse", "Bash")
        self.assertEqual(len(rules_mod._CACHE), 1)
        key_before = next(iter(rules_mod._CACHE.values()))
        load_rules(FIXTURES, "PreToolUse", "Edit")
        key_after = next(iter(rules_mod._CACHE.values()))
        # Same tuple object: second call didn't re-parse (object identity ok
        # because we keep the same cache entry intact).
        self.assertIs(key_before[1], key_after[1])

    def test_mtime_bump_invalidates_cache(self):
        with tempfile.TemporaryDirectory() as td:
            src = FIXTURES / "block-rm-rf.md"
            dst = Path(td) / "block-rm-rf.md"
            dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
            clear_cache()
            first = load_rules(Path(td), "PreToolUse", "Bash")
            self.assertEqual(len(first), 1)
            future = time.time() + 300.0
            os.utime(dst, (future, future))
            import sekha.rules as rules_mod
            first_list_id = id(list(rules_mod._CACHE.values())[0][1])
            second = load_rules(Path(td), "PreToolUse", "Bash")
            second_list_id = id(list(rules_mod._CACHE.values())[0][1])
            self.assertNotEqual(first_list_id, second_list_id,
                                "cache should have re-parsed after mtime bump")
            self.assertEqual(len(second), 1)

    def test_clear_cache_forces_reparse(self):
        import sekha.rules as rules_mod
        load_rules(FIXTURES, "PreToolUse", "Bash")
        self.assertGreaterEqual(len(rules_mod._CACHE), 1)
        clear_cache()
        self.assertEqual(len(rules_mod._CACHE), 0)


class TestPause(_RulesTestBase):
    """RULES-08: SEKHA_PAUSE env var suppresses named rules."""

    def test_single_rule_pause(self):
        os.environ["SEKHA_PAUSE"] = "block-rm-rf"
        rules = load_rules(FIXTURES, "PreToolUse", "Bash")
        names = {r.name for r in rules}
        self.assertNotIn("block-rm-rf", names)
        # Other rules still load
        self.assertIn("block-sudo", names)

    def test_csv_pause(self):
        os.environ["SEKHA_PAUSE"] = "block-rm-rf,warn-git-reset"
        rules = load_rules(FIXTURES, "PreToolUse", "Bash")
        names = {r.name for r in rules}
        self.assertNotIn("block-rm-rf", names)
        self.assertNotIn("warn-git-reset", names)

    def test_pause_whitespace_tolerated(self):
        os.environ["SEKHA_PAUSE"] = "  block-rm-rf , block-sudo  "
        rules = load_rules(FIXTURES, "PreToolUse", "Bash")
        names = {r.name for r in rules}
        self.assertNotIn("block-rm-rf", names)
        self.assertNotIn("block-sudo", names)

    def test_unsetting_pause_restores_rules(self):
        os.environ["SEKHA_PAUSE"] = "block-rm-rf"
        rules_paused = load_rules(FIXTURES, "PreToolUse", "Bash")
        names_paused = {r.name for r in rules_paused}
        self.assertNotIn("block-rm-rf", names_paused)
        os.environ.pop("SEKHA_PAUSE", None)
        # _paused_names reads env every call → no clear_cache needed since the
        # pause filter is applied per-call post-cache.
        rules_live = load_rules(FIXTURES, "PreToolUse", "Bash")
        names_live = {r.name for r in rules_live}
        self.assertIn("block-rm-rf", names_live)


class TestDryRun(_RulesTestBase):
    """RULES-07: test_rule() dry-run."""

    def setUp(self):
        super().setUp()
        self._tmp = tempfile.mkdtemp(prefix="sekha-rules-dryrun-")
        self._saved_home = os.environ.get("SEKHA_HOME")
        os.environ["SEKHA_HOME"] = self._tmp
        rules_dir = Path(self._tmp) / "rules"
        rules_dir.mkdir(parents=True, exist_ok=True)
        # Copy the block-rm-rf fixture so test_rule can find it by name
        shutil.copy2(FIXTURES / "block-rm-rf.md", rules_dir / "block-rm-rf.md")

    def tearDown(self):
        if self._saved_home is not None:
            os.environ["SEKHA_HOME"] = self._saved_home
        else:
            os.environ.pop("SEKHA_HOME", None)
        shutil.rmtree(self._tmp, ignore_errors=True)
        super().tearDown()

    def test_matching_input_returns_matched_true(self):
        result = test_rule("block-rm-rf", "Bash", {"command": "rm -rf /"})
        self.assertTrue(result["matched"])
        self.assertEqual(result["severity"], "block")
        self.assertEqual(result["rule"], "block-rm-rf")
        self.assertIn("rm -rf", result["message"])

    def test_non_matching_input_returns_matched_false(self):
        result = test_rule("block-rm-rf", "Bash", {"command": "ls"})
        self.assertFalse(result["matched"])
        self.assertEqual(result["severity"], "block")

    def test_wrong_tool_returns_matched_false(self):
        # Rule matches [Bash] only; Edit should not match even if pattern does
        result = test_rule("block-rm-rf", "Edit", {"content": "rm -rf /"})
        self.assertFalse(result["matched"])

    def test_missing_rule_raises_file_not_found(self):
        with self.assertRaises(FileNotFoundError):
            test_rule("does-not-exist", "Bash", {"command": "rm -rf /"})


if __name__ == "__main__":
    unittest.main()
