"""Tests for sekha.storage: atomic writes, filelock, slugify, make_memory_path.

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
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from sekha.storage import (
    FilelockTimeout,
    atomic_write,
    dump_frontmatter,
    filelock,
    make_memory_path,
    parse_frontmatter,
    save_memory,
    slugify,
)


class _TempHomeMixin:
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="sekha-test-")
        self._saved = os.environ.get("SEKHA_HOME")
        os.environ["SEKHA_HOME"] = self._tmp

    def tearDown(self):
        if self._saved is None:
            os.environ.pop("SEKHA_HOME", None)
        else:
            os.environ["SEKHA_HOME"] = self._saved
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
        with mock.patch("sekha.storage.os.replace", side_effect=OSError("boom")):
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
        import sekha.storage as s
        if sys.platform == "win32":
            self.assertTrue(hasattr(s, "msvcrt") or "msvcrt" in sys.modules)
        else:
            self.assertTrue(hasattr(s, "fcntl") or "fcntl" in sys.modules)


class TestParseFrontmatter(unittest.TestCase):
    def test_no_frontmatter(self):
        meta, body = parse_frontmatter("no fm here\nbody")
        self.assertEqual(meta, {})
        self.assertEqual(body, "no fm here\nbody")

    def test_basic(self):
        text = "---\nid: abc\ncategory: sessions\n---\nbody here"
        meta, body = parse_frontmatter(text)
        self.assertEqual(meta, {"id": "abc", "category": "sessions"})
        self.assertEqual(body, "body here")

    def test_integer(self):
        meta, _ = parse_frontmatter("---\ncount: 42\n---\n")
        self.assertEqual(meta, {"count": 42})

    def test_booleans(self):
        meta, _ = parse_frontmatter("---\na: true\nb: false\n---\n")
        self.assertEqual(meta, {"a": True, "b": False})

    def test_flow_list(self):
        meta, _ = parse_frontmatter("---\ntags: [alpha, beta, gamma]\n---\n")
        self.assertEqual(meta, {"tags": ["alpha", "beta", "gamma"]})

    def test_iso_timestamp_preserved_as_string(self):
        ts = "2026-04-13T10:00:00+00:00"
        meta, _ = parse_frontmatter(f"---\ncreated: {ts}\n---\n")
        self.assertEqual(meta["created"], ts)
        self.assertIsInstance(meta["created"], str)

    def test_unclosed_raises(self):
        with self.assertRaises(ValueError):
            parse_frontmatter("---\nid: abc\nno closing delim\n")

    def test_crlf(self):
        text = "---\r\nid: abc\r\n---\r\nbody"
        meta, body = parse_frontmatter(text)
        self.assertEqual(meta, {"id": "abc"})
        self.assertEqual(body, "body")

    def test_empty_body(self):
        meta, body = parse_frontmatter("---\nid: abc\n---\n")
        self.assertEqual(meta, {"id": "abc"})
        self.assertEqual(body, "")

    def test_quoted_string_with_colon(self):
        meta, _ = parse_frontmatter('---\nurl: "https://example.com:8080"\n---\n')
        self.assertEqual(meta, {"url": "https://example.com:8080"})


class TestDumpFrontmatter(unittest.TestCase):
    def test_keys_sorted(self):
        out = dump_frontmatter({"b": 1, "a": 2}, "body")
        lines = out.split("\n")
        self.assertEqual(lines[0], "---")
        self.assertTrue(lines[1].startswith("a:"))
        self.assertTrue(lines[2].startswith("b:"))
        self.assertEqual(lines[3], "---")

    def test_delimiters(self):
        out = dump_frontmatter({"x": 1}, "body")
        self.assertTrue(out.startswith("---\n"))
        self.assertIn("\n---\n", out)

    def test_list_flow_style(self):
        out = dump_frontmatter({"tags": ["a", "b"]}, "")
        self.assertIn("tags: [a, b]", out)

    def test_nested_raises(self):
        with self.assertRaises(ValueError):
            dump_frontmatter({"nested": {"a": 1}}, "body")

    def test_round_trip(self):
        m = {"id": "abc", "category": "sessions", "tags": ["x", "y"], "count": 3, "active": True}
        body = "hello world"
        out = dump_frontmatter(m, body)
        m2, body2 = parse_frontmatter(out)
        self.assertEqual(m2, m)
        self.assertEqual(body2, body)


class TestSaveMemory(_TempHomeMixin, unittest.TestCase):
    def test_creates_file(self):
        p = save_memory("sessions", "hello world", title="My Note")
        self.assertTrue(p.exists())
        self.assertEqual(p.parent.name, "sessions")
        self.assertIn("_my-note.md", p.name)

    def test_frontmatter_fields(self):
        p = save_memory("decisions", "body text", title="X", tags=["a"], source="cli")
        meta, body = parse_frontmatter(p.read_text(encoding="utf-8"))
        self.assertEqual(meta["category"], "decisions")
        self.assertIn("id", meta)
        self.assertIn("created", meta)
        self.assertIn("updated", meta)
        self.assertEqual(meta["tags"], ["a"])
        self.assertEqual(meta["source"], "cli")
        self.assertEqual(body, "body text")

    def test_invalid_category(self):
        with self.assertRaises(ValueError):
            save_memory("garbage", "x")

    def test_sekha_home_respected(self):
        p = save_memory("rules", "content", title="Rule X")
        # Compare resolved paths: macOS resolves /var -> /private/var, and
        # Windows may normalize casing or short-name forms, so raw string
        # startswith() is unreliable. .resolve() both sides and compare.
        resolved_tmp = Path(self._tmp).resolve()
        self.assertTrue(
            p.resolve().is_relative_to(resolved_tmp),
            f"{p.resolve()} not under {resolved_tmp}",
        )


class TestConcurrentWrites(_TempHomeMixin, unittest.TestCase):
    """STORE-07: 100 parallel writes produce zero corruption."""

    def test_100_parallel_save_memory(self):
        n = 100

        def worker(i: int) -> Path:
            return save_memory("sessions", f"content-{i}", title=f"Note {i}")

        with ThreadPoolExecutor(max_workers=20) as ex:
            paths = list(ex.map(worker, range(n)))

        # All paths unique
        self.assertEqual(len(set(paths)), n)
        # All files exist and parse
        for p in paths:
            self.assertTrue(p.exists())
            meta, body = parse_frontmatter(p.read_text(encoding="utf-8"))
            self.assertEqual(meta["category"], "sessions")
            self.assertTrue(body.startswith("content-"))

    def test_100_parallel_same_file(self):
        # All writers race on ONE target path — final file must be exactly
        # one writer's content, never interleaved.
        target = Path(self._tmp) / "shared.md"
        expected_bodies = {f"writer-{i}-payload-{'x' * 100}" for i in range(100)}

        def worker(i: int) -> None:
            payload = f"writer-{i}-payload-{'x' * 100}"
            with filelock(target, timeout=10.0):
                atomic_write(target, payload)

        with ThreadPoolExecutor(max_workers=20) as ex:
            futures = [ex.submit(worker, i) for i in range(100)]
            for f in as_completed(futures):
                f.result()  # surface any exception

        final = target.read_text(encoding="utf-8")
        # Final content MUST match exactly one of the 100 expected payloads —
        # no interleaving, no partial bytes.
        self.assertIn(final, expected_bodies)


if __name__ == "__main__":
    unittest.main()
