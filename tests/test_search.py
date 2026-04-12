"""Integration tests for cyrus.search public API.

Task 3 of Plan 02-01 — RED stage. These tests MUST fail initially because
cyrus.search does not exist yet. Task 4 implements the module.

Coverage:
- TestSearchBasics: empty query, result shape, ranking, limits, metadata
- TestSearchFilters: category, since, tags (AND logic)
- TestSearchScoring: tf, recency, filename_bonus ranking contracts
- TestSearchReDoS: catastrophic patterns do not hang end-to-end
- TestSearchSnippetExtraction: context lines and long-line truncation
"""

import os
import shutil
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cyrus.search import SearchResult, search
from cyrus.storage import atomic_write, dump_frontmatter, save_memory


class _CyrusHomeIsolation(unittest.TestCase):
    """Mixin that isolates CYRUS_HOME to a fresh tempdir per test."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="cyrus-search-")
        self._saved = os.environ.get("CYRUS_HOME")
        os.environ["CYRUS_HOME"] = self._tmp

    def tearDown(self):
        if self._saved is None:
            os.environ.pop("CYRUS_HOME", None)
        else:
            os.environ["CYRUS_HOME"] = self._saved
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _write_raw(
        self,
        category: str,
        filename: str,
        metadata: dict,
        body: str,
    ) -> Path:
        """Write a memory file directly, bypassing save_memory so tests can
        force specific `updated` timestamps for the since-filter tests."""
        p = Path(self._tmp) / category / filename
        p.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(p, dump_frontmatter(metadata, body))
        return p


class TestSearchBasics(_CyrusHomeIsolation):
    def setUp(self):
        super().setUp()
        # Seed a handful of files so ranking has something to chew on.
        save_memory("sessions", "jwt token refresh flow", title="JWT note")
        save_memory("decisions", "chose jwt over opaque tokens", title="Auth decision")
        save_memory("projects", "the quick brown fox jumps", title="Misc")
        save_memory("rules", "do not log secrets", title="Rule secrets")
        save_memory("preferences", "prefers dark mode the", title="Pref UI")
        save_memory("sessions", "hello world here is the", title="Greeting")
        save_memory("sessions", "jwt jwt jwt jwt the", title="Heavy jwt")
        save_memory("decisions", "nothing relevant here", title="Empty")

    def test_empty_query_returns_empty_list(self):
        self.assertEqual(search(""), [])

    def test_returns_list_of_searchresult(self):
        results = search("jwt")
        self.assertTrue(all(isinstance(r, SearchResult) for r in results))
        self.assertGreater(len(results), 0)

    def test_results_ranked_descending(self):
        results = search("jwt")
        scores = [r.score for r in results]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_limit_respected(self):
        results = search("the", limit=3)
        self.assertLessEqual(len(results), 3)

    def test_default_limit_is_10(self):
        results = search("the")
        self.assertLessEqual(len(results), 10)

    def test_no_matches_returns_empty(self):
        self.assertEqual(search("zzzzz-does-not-exist-anywhere"), [])

    def test_snippet_contains_match(self):
        results = search("jwt")
        self.assertGreater(len(results), 0)
        for r in results:
            # Snippet is non-empty and contains the match (case-insensitive)
            self.assertTrue(r.snippet)
            self.assertIn("jwt", r.snippet.lower())

    def test_metadata_is_parsed_frontmatter(self):
        results = search("jwt")
        self.assertGreater(len(results), 0)
        for r in results:
            self.assertIn("id", r.metadata)
            self.assertIn("category", r.metadata)
            self.assertIn("created", r.metadata)
            self.assertIn("updated", r.metadata)
            self.assertIn("tags", r.metadata)

    def test_path_points_to_real_file(self):
        results = search("jwt")
        for r in results:
            self.assertTrue(r.path.exists(), f"{r.path} does not exist")


class TestSearchFilters(_CyrusHomeIsolation):
    def setUp(self):
        super().setUp()
        save_memory("sessions", "cyrus memory session", title="Sess a")
        save_memory("decisions", "cyrus auth decision", title="Dec a")
        save_memory("rules", "cyrus rule here", title="Rule a")

    def test_category_filter_restricts_scan(self):
        results = search("cyrus", category="rules")
        self.assertGreater(len(results), 0)
        rules_root = (Path(self._tmp) / "rules").resolve()
        for r in results:
            self.assertTrue(
                r.path.resolve().is_relative_to(rules_root),
                f"{r.path.resolve()} not under {rules_root}",
            )

    def test_category_invalid_raises(self):
        with self.assertRaises(ValueError):
            search("cyrus", category="bogus")

    def test_category_none_searches_all(self):
        results = search("cyrus")
        categories = {r.metadata.get("category") for r in results}
        self.assertGreaterEqual(len(categories), 2)

    def test_since_filter(self):
        # Wipe seeded files so we control timestamps exactly
        shutil.rmtree(self._tmp, ignore_errors=True)
        Path(self._tmp).mkdir(parents=True, exist_ok=True)
        old_meta = {
            "id": "old00000",
            "category": "sessions",
            "created": "2024-01-01T00:00:00+00:00",
            "updated": "2024-01-01T00:00:00+00:00",
            "tags": [],
        }
        new_meta = {
            "id": "new00000",
            "category": "sessions",
            "created": "2026-04-11T00:00:00+00:00",
            "updated": "2026-04-11T00:00:00+00:00",
            "tags": [],
        }
        self._write_raw(
            "sessions", "2024-01-01_old00000_old.md", old_meta, "cyrus old note"
        )
        self._write_raw(
            "sessions", "2026-04-11_new00000_new.md", new_meta, "cyrus new note"
        )
        cutoff = datetime(2026, 1, 1, tzinfo=timezone.utc)
        results = search("cyrus", since=cutoff)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].metadata["id"], "new00000")

    def test_tags_filter_and_logic(self):
        # All three files contain a common query word "shared", but tags
        # differ. Only file with BOTH auth AND jwt tags should match.
        shutil.rmtree(self._tmp, ignore_errors=True)
        Path(self._tmp).mkdir(parents=True, exist_ok=True)
        base = {
            "category": "sessions",
            "created": "2026-04-11T00:00:00+00:00",
            "updated": "2026-04-11T00:00:00+00:00",
        }
        self._write_raw(
            "sessions",
            "2026-04-11_aaaa0001_a.md",
            {**base, "id": "aaaa0001", "tags": ["auth", "jwt"]},
            "shared content A",
        )
        self._write_raw(
            "sessions",
            "2026-04-11_bbbb0002_b.md",
            {**base, "id": "bbbb0002", "tags": ["auth"]},
            "shared content B",
        )
        self._write_raw(
            "sessions",
            "2026-04-11_cccc0003_c.md",
            {**base, "id": "cccc0003", "tags": ["jwt"]},
            "shared content C",
        )
        results = search("shared", tags=["auth", "jwt"])
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].metadata["id"], "aaaa0001")

    def test_tags_no_match_returns_empty(self):
        results = search("cyrus", tags=["nonexistent-tag-xyz"])
        self.assertEqual(results, [])


class TestSearchScoring(_CyrusHomeIsolation):
    def test_filename_bonus_ranks_higher(self):
        # Two files with the same body; only one has 'jwt' in filename
        base = {
            "category": "sessions",
            "created": "2026-04-11T00:00:00+00:00",
            "updated": "2026-04-11T00:00:00+00:00",
            "tags": [],
        }
        self._write_raw(
            "sessions",
            "2026-04-11_aaaa0001_jwt-file.md",
            {**base, "id": "aaaa0001"},
            "contains jwt once",
        )
        self._write_raw(
            "sessions",
            "2026-04-11_bbbb0002_other-file.md",
            {**base, "id": "bbbb0002"},
            "contains jwt once",
        )
        results = search("jwt")
        self.assertGreaterEqual(len(results), 2)
        # The filename-hit file must rank first
        self.assertEqual(results[0].metadata["id"], "aaaa0001")

    def test_tf_ranks_higher(self):
        base = {
            "category": "sessions",
            "created": "2026-04-11T00:00:00+00:00",
            "updated": "2026-04-11T00:00:00+00:00",
            "tags": [],
        }
        # Neither filename contains 'jwt' — avoid filename_bonus interference
        self._write_raw(
            "sessions",
            "2026-04-11_aaaa0001_alpha.md",
            {**base, "id": "aaaa0001"},
            "jwt jwt jwt jwt jwt",
        )
        self._write_raw(
            "sessions",
            "2026-04-11_bbbb0002_beta.md",
            {**base, "id": "bbbb0002"},
            "jwt once",
        )
        results = search("jwt")
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0].metadata["id"], "aaaa0001")

    def test_recency_ranks_higher(self):
        # Same body, same filename shape, only 'updated' differs
        now = datetime.now(timezone.utc)
        old = (now - timedelta(days=90)).isoformat(timespec="seconds")
        fresh = now.isoformat(timespec="seconds")
        self._write_raw(
            "sessions",
            "2026-04-11_aaaa0001_alpha.md",
            {
                "id": "aaaa0001",
                "category": "sessions",
                "created": fresh,
                "updated": fresh,
                "tags": [],
            },
            "same body content jwt",
        )
        self._write_raw(
            "sessions",
            "2024-01-01_bbbb0002_beta.md",
            {
                "id": "bbbb0002",
                "category": "sessions",
                "created": old,
                "updated": old,
                "tags": [],
            },
            "same body content jwt",
        )
        results = search("jwt")
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0].metadata["id"], "aaaa0001")


class TestSearchReDoS(_CyrusHomeIsolation):
    def test_catastrophic_pattern_does_not_hang(self):
        # 30 a's + X is the classic catastrophic fixture for (a+)+b
        save_memory("sessions", ("a" * 30) + "X", title="Evil")
        t0 = time.monotonic()
        results = search("(a+)+b")
        elapsed = time.monotonic() - t0
        self.assertLess(
            elapsed, 2.0,
            f"search hung on catastrophic pattern: {elapsed:.3f}s",
        )
        # Return value may be empty or partial — we only assert completion
        self.assertIsInstance(results, list)

    def test_literal_query_with_regex_chars_is_safe(self):
        # "file.md" contains '.' which makes it a regex, but the pattern
        # is benign and must terminate promptly.
        save_memory("sessions", "see file.md here", title="Docs")
        t0 = time.monotonic()
        results = search("file.md")
        elapsed = time.monotonic() - t0
        self.assertLess(elapsed, 2.0)
        self.assertIsInstance(results, list)


class TestSearchSnippetExtraction(_CyrusHomeIsolation):
    def test_snippet_has_context(self):
        body = "line1\nMATCHTARGET in the middle\nline3"
        self._write_raw(
            "sessions",
            "2026-04-11_aaaa0001_snip.md",
            {
                "id": "aaaa0001",
                "category": "sessions",
                "created": "2026-04-11T00:00:00+00:00",
                "updated": "2026-04-11T00:00:00+00:00",
                "tags": [],
            },
            body,
        )
        results = search("matchtarget")
        self.assertEqual(len(results), 1)
        snippet = results[0].snippet
        self.assertIn("line1", snippet)
        self.assertIn("MATCHTARGET", snippet)
        self.assertIn("line3", snippet)

    def test_long_line_truncated(self):
        long_line = ("z" * 200) + " match here"
        self._write_raw(
            "sessions",
            "2026-04-11_aaaa0001_long.md",
            {
                "id": "aaaa0001",
                "category": "sessions",
                "created": "2026-04-11T00:00:00+00:00",
                "updated": "2026-04-11T00:00:00+00:00",
                "tags": [],
            },
            long_line,
        )
        results = search("match")
        self.assertEqual(len(results), 1)
        # The matched line must be truncated with '...' within 120 chars
        for line in results[0].snippet.split("\n"):
            self.assertLessEqual(len(line), 120)
        self.assertIn("...", results[0].snippet)


if __name__ == "__main__":
    unittest.main()
