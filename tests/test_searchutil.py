"""Tests for sekha._searchutil: scoring helpers, snippet extraction, ReDoS guard.

Task 1 of Plan 02-01 — RED stage. These tests MUST fail initially because
sekha._searchutil does not exist yet. Task 2 implements the module.

Covers:
- is_literal_query: metachar detection
- recency_decay: exp(-age/30), clamped for future timestamps
- filename_bonus: 2.0 on slug hit, 1.0 else
- extract_snippet: matched line + context, 120-char truncation
- scan_file_with_timeout: literal vs regex path, ReDoS watchdog
"""

import math
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

from sekha import _searchutil  # noqa: F401 — import must succeed post-RED


class TestIsLiteralQuery(unittest.TestCase):
    def test_plain_word_is_literal(self):
        self.assertTrue(_searchutil.is_literal_query("hello"))

    def test_spaces_are_literal(self):
        self.assertTrue(_searchutil.is_literal_query("hello world"))

    def test_empty_is_literal(self):
        self.assertTrue(_searchutil.is_literal_query(""))

    def test_dot_is_regex(self):
        self.assertFalse(_searchutil.is_literal_query("file.md"))

    def test_plus_is_regex(self):
        self.assertFalse(_searchutil.is_literal_query("a+b"))

    def test_parens_are_regex(self):
        self.assertFalse(_searchutil.is_literal_query("(group)"))

    def test_brackets_are_regex(self):
        self.assertFalse(_searchutil.is_literal_query("[abc]"))

    def test_caret_is_regex(self):
        self.assertFalse(_searchutil.is_literal_query("^start"))

    def test_dollar_is_regex(self):
        self.assertFalse(_searchutil.is_literal_query("end$"))

    def test_star_is_regex(self):
        self.assertFalse(_searchutil.is_literal_query("a*"))

    def test_question_mark_is_regex(self):
        self.assertFalse(_searchutil.is_literal_query("a?"))

    def test_backslash_is_regex(self):
        self.assertFalse(_searchutil.is_literal_query("a\\b"))

    def test_pipe_is_regex(self):
        self.assertFalse(_searchutil.is_literal_query("a|b"))

    def test_braces_are_regex(self):
        self.assertFalse(_searchutil.is_literal_query("a{2}"))


class TestRecencyDecay(unittest.TestCase):
    def test_zero_age_is_one(self):
        self.assertEqual(_searchutil.recency_decay(0.0), 1.0)

    def test_thirty_days_is_exp_minus_one(self):
        self.assertAlmostEqual(
            _searchutil.recency_decay(30.0), math.exp(-1.0), places=6
        )

    def test_ninety_days_is_exp_minus_three(self):
        self.assertAlmostEqual(
            _searchutil.recency_decay(90.0), math.exp(-3.0), places=6
        )

    def test_monotone_decreasing(self):
        a = _searchutil.recency_decay(10.0)
        b = _searchutil.recency_decay(50.0)
        c = _searchutil.recency_decay(200.0)
        self.assertGreater(a, b)
        self.assertGreater(b, c)

    def test_future_dated_clamped_to_one(self):
        # Negative age_days (mtime skew / future file) must not exceed fresh
        self.assertEqual(_searchutil.recency_decay(-5.0), 1.0)


class TestFilenameBonus(unittest.TestCase):
    def test_substring_in_slug_returns_two(self):
        p = Path("2026-04-11_abcd1234_jwt-refactor.md")
        self.assertEqual(_searchutil.filename_bonus("jwt", p), 2.0)

    def test_case_insensitive(self):
        p = Path("2026-04-11_abcd1234_jwt-refactor.md")
        self.assertEqual(_searchutil.filename_bonus("JWT", p), 2.0)

    def test_no_match_returns_one(self):
        p = Path("2026-04-11_abcd1234_unrelated.md")
        self.assertEqual(_searchutil.filename_bonus("auth", p), 1.0)

    def test_empty_query_returns_one(self):
        p = Path("2026-04-11_abcd1234_whatever.md")
        self.assertEqual(_searchutil.filename_bonus("", p), 1.0)


class TestExtractSnippet(unittest.TestCase):
    def test_match_in_middle_includes_context(self):
        body = "line0\nline1\nMATCH here\nline3\nline4"
        snippet = _searchutil.extract_snippet(body, "MATCH")
        # Must include the line above, the match, and the line below
        self.assertIn("line1", snippet)
        self.assertIn("MATCH here", snippet)
        self.assertIn("line3", snippet)
        # Joined with newlines
        self.assertEqual(snippet, "line1\nMATCH here\nline3")

    def test_match_on_first_line_no_above(self):
        body = "FIRST match\nline1\nline2"
        snippet = _searchutil.extract_snippet(body, "FIRST")
        self.assertEqual(snippet, "FIRST match\nline1")

    def test_match_on_last_line_no_below(self):
        body = "line0\nline1\nLAST match"
        snippet = _searchutil.extract_snippet(body, "LAST")
        self.assertEqual(snippet, "line1\nLAST match")

    def test_no_match_returns_empty(self):
        body = "line0\nline1\nline2"
        self.assertEqual(_searchutil.extract_snippet(body, "nope"), "")

    def test_case_insensitive_match(self):
        body = "some JWT token here"
        snippet = _searchutil.extract_snippet(body, "jwt")
        self.assertIn("JWT", snippet)

    def test_long_line_truncated(self):
        long_line = "x" * 200
        body = f"prior\n{long_line} match here\nnext"
        snippet = _searchutil.extract_snippet(body, "match")
        # Find the matched (middle) line in the snippet; it must be truncated
        lines = snippet.split("\n")
        middle = next(ln for ln in lines if "match" in ln.lower() or "..." in ln)
        self.assertLessEqual(len(middle), 120)
        self.assertTrue(middle.endswith("..."))

    def test_empty_query_returns_empty(self):
        body = "anything here"
        self.assertEqual(_searchutil.extract_snippet(body, ""), "")

    def test_empty_body_returns_empty(self):
        self.assertEqual(_searchutil.extract_snippet("", "anything"), "")


class TestScanFileWithTimeout(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="sekha-searchutil-")

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _write(self, name: str, content: str) -> Path:
        p = Path(self._tmp) / name
        p.write_text(content, encoding="utf-8")
        return p

    def test_literal_match_counted(self):
        p = self._write("a.md", "hello world, hello again")
        count, timed_out = _searchutil.scan_file_with_timeout(
            p, "hello", is_literal=True
        )
        self.assertGreaterEqual(count, 2)
        self.assertFalse(timed_out)

    def test_literal_case_insensitive(self):
        p = self._write("a.md", "Hello World")
        count, timed_out = _searchutil.scan_file_with_timeout(
            p, "hello", is_literal=True
        )
        self.assertEqual(count, 1)
        self.assertFalse(timed_out)

    def test_regex_match_counted(self):
        p = self._write("a.md", "hello world")
        count, timed_out = _searchutil.scan_file_with_timeout(
            p, "h.llo", is_literal=False
        )
        self.assertGreaterEqual(count, 1)
        self.assertFalse(timed_out)

    def test_catastrophic_pattern_times_out(self):
        # (a+)+b against 30 a's + X triggers exponential backtracking on
        # CPython's re engine. Watchdog must kill this under 0.5s wall clock.
        adversarial = ("a" * 30) + "X"
        p = self._write("evil.md", adversarial)
        t0 = time.monotonic()
        count, timed_out = _searchutil.scan_file_with_timeout(
            p, "(a+)+b", timeout=0.1, is_literal=False
        )
        elapsed = time.monotonic() - t0
        self.assertLess(elapsed, 0.5, f"watchdog did not kill within 0.5s: {elapsed:.3f}s")
        self.assertTrue(timed_out)
        self.assertEqual(count, 0)

    def test_nonexistent_file_returns_zero(self):
        p = Path(self._tmp) / "does-not-exist.md"
        count, timed_out = _searchutil.scan_file_with_timeout(
            p, "hello", is_literal=True
        )
        self.assertEqual(count, 0)
        self.assertFalse(timed_out)


if __name__ == "__main__":
    unittest.main()
