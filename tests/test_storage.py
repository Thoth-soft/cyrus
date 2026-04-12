"""Tests for cyrus.storage: atomic writes, filelock, slugify, make_memory_path.

Task 1 of Plan 01-02 — RED stage covers the primitives. Frontmatter and
save_memory + the 100-parallel-write stress test arrive in Task 2.
"""

import os
import re
import sys
import tempfile
import threading
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from cyrus.storage import (
    FilelockTimeout,
    atomic_write,
    filelock,
    make_memory_path,
    slugify,
)


class _TempHomeMixin:
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="cyrus-test-")
        self._saved = os.environ.get("CYRUS_HOME")
        os.environ["CYRUS_HOME"] = self._tmp

    def tearDown(self):
        if self._saved is None:
            os.environ.pop("CYRUS_HOME", None)
        else:
            os.environ["CYRUS_HOME"] = self._saved
        # Best-effort cleanup; Windows may hold lock files briefly
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)


class TestSlugify(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(slugify("Refactor Auth Flow"), "refactor-auth-flow")

    def test_collapses_whitespace_and_punctuation(self):
        self.assertEqual(slugify("  Multiple   Spaces!!! "), "multiple-spaces")

    def test_empty_returns_untitled(self):
        self.assertEqual(slugify(""), "untitled")

    def test_no_alnum_returns_untitled(self):
        self.assertEqual(slugify("---!!!"), "untitled")

    def test_truncates_to_max_len(self):
        self.assertEqual(len(slugify("a" * 100, max_len=40)), 40)

    def test_ascii_fold(self):
        self.assertEqual(slugify("café résumé"), "cafe-resume")

    def test_path_separators_neutralized(self):
        self.assertEqual(slugify("foo/bar\\baz"), "foo-bar-baz")


class TestMakeMemoryPath(_TempHomeMixin, unittest.TestCase):
    FILENAME_RE = re.compile(
        r"^\d{4}-\d{2}-\d{2}_[0-9a-f]{8}_[a-z0-9][a-z0-9-]*\.md$"
    )

    def test_shape(self):
        when = datetime(2026, 4, 13, 10, 0, 0, tzinfo=timezone.utc)
        p = make_memory_path("sessions", "My Note", when=when, seed=b"fixed")
        self.assertEqual(p.parent.name, "sessions")
        self.assertTrue(self.FILENAME_RE.match(p.name), f"bad filename: {p.name}")
        self.assertIn("2026-04-13_", p.name)
        self.assertTrue(p.name.endswith("_my-note.md"))

    def test_deterministic_with_seed(self):
        when = datetime(2026, 4, 13, tzinfo=timezone.utc)
        a = make_memory_path("sessions", "x", when=when, seed=b"same")
        b = make_memory_path("sessions", "x", when=when, seed=b"same")
        self.assertEqual(a, b)

    def test_different_seeds_differ(self):
        when = datetime(2026, 4, 13, tzinfo=timezone.utc)
        a = make_memory_path("sessions", "x", when=when, seed=b"one")
        b = make_memory_path("sessions", "x", when=when, seed=b"two")
        self.assertNotEqual(a, b)

    def test_invalid_category_raises(self):
        with self.assertRaises(ValueError):
            make_memory_path("garbage", "x")


class TestAtomicWrite(_TempHomeMixin, unittest.TestCase):
    def test_writes_content(self):
        p = Path(self._tmp) / "a.txt"
        atomic_write(p, "hello\n")
        self.assertEqual(p.read_text(encoding="utf-8"), "hello\n")

    def test_overwrites(self):
        p = Path(self._tmp) / "a.txt"
        atomic_write(p, "one")
        atomic_write(p, "two")
        self.assertEqual(p.read_text(encoding="utf-8"), "two")

    def test_creates_parent(self):
        p = Path(self._tmp) / "deep" / "nested" / "a.txt"
        atomic_write(p, "ok")
        self.assertTrue(p.exists())

    def test_no_leftover_tmp_files(self):
        p = Path(self._tmp) / "a.txt"
        atomic_write(p, "ok")
        leftovers = [q for q in p.parent.iterdir() if ".tmp." in q.name]
        self.assertEqual(leftovers, [])

    def test_failure_does_not_corrupt_destination(self):
        p = Path(self._tmp) / "a.txt"
        atomic_write(p, "original")
        with mock.patch("cyrus.storage.os.replace", side_effect=OSError("boom")):
            with self.assertRaises(OSError):
                atomic_write(p, "NEW")
        # Original content preserved
        self.assertEqual(p.read_text(encoding="utf-8"), "original")


class TestFilelock(_TempHomeMixin, unittest.TestCase):
    def test_acquire_release(self):
        p = Path(self._tmp) / "target"
        with filelock(p, timeout=1.0):
            pass  # should not raise

    def test_independent_paths(self):
        a = Path(self._tmp) / "a"
        b = Path(self._tmp) / "b"
        with filelock(a, timeout=1.0):
            with filelock(b, timeout=1.0):
                pass

    def test_contention_serializes(self):
        p = Path(self._tmp) / "contend"
        events: list[str] = []
        started = threading.Event()

        def holder():
            with filelock(p, timeout=2.0):
                started.set()
                events.append("hold-start")
                time.sleep(0.2)
                events.append("hold-end")

        t = threading.Thread(target=holder)
        t.start()
        started.wait(timeout=2.0)
        # Second acquire should block until holder releases
        with filelock(p, timeout=2.0):
            events.append("second-acquired")
        t.join(timeout=2.0)
        # hold-end must precede second-acquired
        self.assertEqual(events, ["hold-start", "hold-end", "second-acquired"])

    def test_timeout(self):
        p = Path(self._tmp) / "timeout"
        started = threading.Event()
        hold = threading.Event()

        def holder():
            with filelock(p, timeout=2.0):
                started.set()
                hold.wait(timeout=2.0)

        t = threading.Thread(target=holder)
        t.start()
        try:
            started.wait(timeout=2.0)
            with self.assertRaises(FilelockTimeout):
                with filelock(p, timeout=0.3):
                    self.fail("should not acquire")
        finally:
            hold.set()
            t.join(timeout=2.0)

    def test_exception_releases_lock(self):
        p = Path(self._tmp) / "exc"
        with self.assertRaises(RuntimeError):
            with filelock(p, timeout=1.0):
                raise RuntimeError("boom")
        # Should be immediately re-acquirable
        with filelock(p, timeout=0.5):
            pass

    def test_platform_primitive_selected(self):
        # Sanity check: the correct module is imported based on platform
        import cyrus.storage as s
        if sys.platform == "win32":
            self.assertTrue(hasattr(s, "msvcrt") or "msvcrt" in sys.modules)
        else:
            self.assertTrue(hasattr(s, "fcntl") or "fcntl" in sys.modules)


if __name__ == "__main__":
    unittest.main()
