"""Tests for sekha.tools: 6 MCP tool handlers delegating to storage/search/rules.

RED stage for Plan 05-01 Task 3. Every test stages its own SEKHA_HOME
tempdir so no two tests collide on disk. Handlers are asserted at the
dict-shape level — the underlying storage/search/rules behavior already
has its own dedicated test modules; we don't duplicate that coverage,
we just verify the thin delegation works.
"""
from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path

from sekha.storage import parse_frontmatter


class _TempHomeMixin:
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="sekha-tools-test-")
        self._saved = os.environ.get("SEKHA_HOME")
        os.environ["SEKHA_HOME"] = self._tmp

    def tearDown(self):
        if self._saved is None:
            os.environ.pop("SEKHA_HOME", None)
        else:
            os.environ["SEKHA_HOME"] = self._saved
        shutil.rmtree(self._tmp, ignore_errors=True)


# --------------------------------------------------------------------------
# sekha_save (MCP-04)
# --------------------------------------------------------------------------
class TestSekhaSave(_TempHomeMixin, unittest.TestCase):
    def test_save_returns_path_and_id(self):
        from sekha.tools import sekha_save
        result = sekha_save(category="decisions", content="Use Python 3.11")
        self.assertIn("path", result)
        self.assertIn("id", result)
        self.assertTrue(result["path"].endswith(".md"))
        # id is 8-char hex (blake2b digest_size=4 -> 8 hex chars)
        self.assertEqual(len(result["id"]), 8)
        self.assertTrue(all(c in "0123456789abcdef" for c in result["id"]))
        # File exists under decisions/
        p = Path(result["path"])
        self.assertTrue(p.exists())
        self.assertEqual(p.parent.name, "decisions")

    def test_save_honours_tags_and_source(self):
        from sekha.tools import sekha_save
        result = sekha_save(
            category="sessions",
            content="note body",
            tags=["alpha", "beta"],
            source="unit-test",
        )
        text = Path(result["path"]).read_text(encoding="utf-8")
        metadata, body = parse_frontmatter(text)
        self.assertEqual(metadata.get("tags"), ["alpha", "beta"])
        self.assertEqual(metadata.get("source"), "unit-test")
        self.assertIn("note body", body)

    def test_save_rejects_invalid_category(self):
        from sekha.tools import sekha_save
        with self.assertRaises(ValueError):
            sekha_save(category="bogus", content="x")


# --------------------------------------------------------------------------
# sekha_search (MCP-05)
# --------------------------------------------------------------------------
class TestSekhaSearch(_TempHomeMixin, unittest.TestCase):
    def _save(self, category, content, **kw):
        from sekha.tools import sekha_save
        return sekha_save(category=category, content=content, **kw)

    def test_search_returns_results_shape(self):
        from sekha.tools import sekha_search
        self._save("decisions", "alpha beta gamma")
        self._save("sessions", "alpha only")
        out = sekha_search(query="alpha")
        self.assertIn("results", out)
        self.assertGreaterEqual(len(out["results"]), 2)
        for r in out["results"]:
            self.assertEqual(
                set(r.keys()), {"path", "score", "snippet", "metadata"}
            )

    def test_search_honours_category_filter(self):
        from sekha.tools import sekha_search
        self._save("decisions", "needle in decisions")
        self._save("sessions", "needle in sessions")
        out = sekha_search(query="needle", category="decisions")
        self.assertEqual(len(out["results"]), 1)
        self.assertIn("decisions", out["results"][0]["path"])

    def test_search_limit_default_is_10(self):
        from sekha.tools import sekha_search
        for i in range(12):
            self._save("sessions", f"foo number {i}", tags=[f"t{i}"])
        out = sekha_search(query="foo")
        self.assertLessEqual(len(out["results"]), 10)


# --------------------------------------------------------------------------
# sekha_list (MCP-06)
# --------------------------------------------------------------------------
class TestSekhaList(_TempHomeMixin, unittest.TestCase):
    def _save(self, category, content):
        from sekha.tools import sekha_save
        return sekha_save(category=category, content=content)

    def test_list_returns_metadata_no_body(self):
        from sekha.tools import sekha_list
        self._save("sessions", "one")
        self._save("decisions", "two")
        self._save("sessions", "three")
        out = sekha_list()
        self.assertIn("memories", out)
        self.assertGreaterEqual(len(out["memories"]), 3)
        for m in out["memories"]:
            for k in ("path", "category", "created", "updated", "tags", "id"):
                self.assertIn(k, m)
            self.assertNotIn("content", m)
            self.assertNotIn("body", m)

    def test_list_category_filter(self):
        from sekha.tools import sekha_list
        self._save("sessions", "a")
        self._save("decisions", "b")
        out = sekha_list(category="decisions")
        self.assertGreaterEqual(len(out["memories"]), 1)
        for m in out["memories"]:
            self.assertIn("decisions", m["path"])

    def test_list_limit(self):
        from sekha.tools import sekha_list
        for i in range(5):
            self._save("sessions", f"entry-{i}")
        out = sekha_list(limit=2)
        self.assertLessEqual(len(out["memories"]), 2)


# --------------------------------------------------------------------------
# sekha_delete (MCP-07)
# --------------------------------------------------------------------------
class TestSekhaDelete(_TempHomeMixin, unittest.TestCase):
    def test_delete_removes_file(self):
        from sekha.tools import sekha_delete, sekha_save
        saved = sekha_save(category="sessions", content="doomed")
        out = sekha_delete(path=saved["path"])
        self.assertTrue(out["success"])
        self.assertFalse(Path(saved["path"]).exists())

    def test_delete_missing_returns_failure(self):
        from sekha.tools import sekha_delete
        fake = str(Path(self._tmp) / "sessions" / "nope.md")
        out = sekha_delete(path=fake)
        self.assertFalse(out["success"])
        self.assertIn("error", out)

    def test_delete_rejects_path_outside_sekha_home(self):
        from sekha.tools import sekha_delete
        # Create a real file outside SEKHA_HOME to prove we don't touch it.
        with tempfile.NamedTemporaryFile(
            delete=False, suffix=".md"
        ) as f:
            f.write(b"outside")
            outside = f.name
        try:
            out = sekha_delete(path=outside)
            self.assertFalse(out["success"])
            self.assertIn("error", out)
            # The outside file must still exist.
            self.assertTrue(Path(outside).exists())
        finally:
            try:
                os.unlink(outside)
            except OSError:
                pass


# --------------------------------------------------------------------------
# sekha_status (MCP-08)
# --------------------------------------------------------------------------
class TestSekhaStatus(_TempHomeMixin, unittest.TestCase):
    def test_status_shape(self):
        from sekha.tools import sekha_save, sekha_status
        sekha_save(category="decisions", content="one")
        sekha_save(category="decisions", content="two")
        out = sekha_status()
        for k in ("total", "by_category", "rules_count", "recent", "hook_errors"):
            self.assertIn(k, out)
        self.assertIsInstance(out["by_category"], dict)
        self.assertGreaterEqual(out["by_category"]["decisions"], 2)
        self.assertGreaterEqual(out["total"], 2)

    def test_status_reads_hook_errors_log(self):
        from sekha.tools import sekha_status
        log = Path(self._tmp) / "hook-errors.log"
        log.write_text("line-1\nline-2\nline-3\n", encoding="utf-8")
        out = sekha_status()
        self.assertEqual(out["hook_errors"], 3)


# --------------------------------------------------------------------------
# sekha_add_rule (MCP-09)
# --------------------------------------------------------------------------
class TestSekhaAddRule(_TempHomeMixin, unittest.TestCase):
    def test_add_rule_writes_file(self):
        from sekha.tools import sekha_add_rule
        out = sekha_add_rule(
            name="no-foo",
            severity="block",
            matches=["Bash"],
            pattern="foo",
            message="no foo allowed",
        )
        rule_path = Path(out["path"])
        self.assertTrue(rule_path.exists())
        self.assertEqual(rule_path.parent.name, "rules")
        meta, _body = parse_frontmatter(
            rule_path.read_text(encoding="utf-8")
        )
        self.assertEqual(meta["name"], "no-foo")
        self.assertEqual(meta["severity"], "block")
        self.assertEqual(meta["matches"], ["Bash"])
        self.assertEqual(meta["pattern"], "foo")
        self.assertEqual(meta["message"], "no foo allowed")
        self.assertEqual(meta["priority"], 50)
        self.assertEqual(meta["triggers"], ["PreToolUse"])

    def test_add_rule_validates_regex_before_write(self):
        from sekha.tools import sekha_add_rule
        rules_dir = Path(self._tmp) / "rules"
        rule_path = rules_dir / "bad.md"
        with self.assertRaises(Exception) as ctx:
            sekha_add_rule(
                name="bad",
                severity="block",
                matches=["*"],
                pattern="[",  # unclosed character class
                message="x",
            )
        # Any exception type is acceptable (re.error is a subclass of
        # Exception); the MCP-09 hard requirement is that the rule file
        # does NOT exist after the failure.
        del ctx  # ensure at least one assert above
        self.assertFalse(rule_path.exists())

    def test_add_rule_rejects_bad_severity(self):
        from sekha.tools import sekha_add_rule
        with self.assertRaises(ValueError):
            sekha_add_rule(
                name="kab",
                severity="kablooey",
                matches=["*"],
                pattern="foo",
                message="x",
            )


# --------------------------------------------------------------------------
# HANDLERS registry
# --------------------------------------------------------------------------
class TestHandlers(unittest.TestCase):
    def test_handlers_dict_covers_all_six(self):
        from sekha.tools import HANDLERS
        expected = {
            "sekha_save", "sekha_search", "sekha_list",
            "sekha_delete", "sekha_status", "sekha_add_rule",
        }
        self.assertEqual(set(HANDLERS.keys()), expected)
        for name, fn in HANDLERS.items():
            self.assertTrue(callable(fn), f"{name} is not callable")


if __name__ == "__main__":
    unittest.main()
