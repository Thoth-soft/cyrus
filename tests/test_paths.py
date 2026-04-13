"""Tests for sekha.paths: home-directory resolution and category taxonomy."""

import os
import tempfile
import unittest
from pathlib import Path

from sekha.paths import CATEGORIES, category_dir, sekha_home


class TestSekhaHome(unittest.TestCase):
    def setUp(self) -> None:
        # Save and clear SEKHA_HOME so default-path tests are isolated
        self._saved = os.environ.pop("SEKHA_HOME", None)

    def tearDown(self) -> None:
        os.environ.pop("SEKHA_HOME", None)
        if self._saved is not None:
            os.environ["SEKHA_HOME"] = self._saved

    def test_default_is_home_dot_sekha(self) -> None:
        result = sekha_home()
        self.assertEqual(result, (Path.home() / ".sekha").resolve())
        self.assertIsInstance(result, Path)

    def test_env_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["SEKHA_HOME"] = tmp
            self.assertEqual(sekha_home(), Path(tmp).resolve())

    def test_env_read_every_call(self) -> None:
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            os.environ["SEKHA_HOME"] = a
            first = sekha_home()
            os.environ["SEKHA_HOME"] = b
            second = sekha_home()
            self.assertNotEqual(first, second)

    def test_returns_path_instance(self) -> None:
        result = sekha_home()
        self.assertIsInstance(result, Path)
        self.assertNotIsInstance(result, str)

    def test_does_not_create_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "does-not-exist-yet"
            os.environ["SEKHA_HOME"] = str(target)
            _ = sekha_home()
            self.assertFalse(target.exists())

    def test_as_posix_uses_forward_slashes(self) -> None:
        # Cross-platform sanity — callers rely on as_posix() for JSON serialization
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["SEKHA_HOME"] = tmp
            posix = sekha_home().as_posix()
            self.assertNotIn("\\", posix)


class TestCategories(unittest.TestCase):
    def setUp(self) -> None:
        self._saved = os.environ.pop("SEKHA_HOME", None)

    def tearDown(self) -> None:
        os.environ.pop("SEKHA_HOME", None)
        if self._saved is not None:
            os.environ["SEKHA_HOME"] = self._saved

    def test_exact_five_categories_in_order(self) -> None:
        self.assertEqual(
            CATEGORIES,
            ("sessions", "decisions", "preferences", "projects", "rules"),
        )
        self.assertIsInstance(CATEGORIES, tuple)

    def test_category_dir_valid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["SEKHA_HOME"] = tmp
            self.assertEqual(category_dir("rules"), Path(tmp).resolve() / "rules")

    def test_category_dir_invalid_raises(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            category_dir("garbage")
        # Error message must list all valid categories for debuggability
        for cat in ("sessions", "decisions", "preferences", "projects", "rules"):
            self.assertIn(cat, str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
