"""Placeholder test to validate CI pipeline."""

import re
import unittest


class TestPlaceholder(unittest.TestCase):
    """Placeholder test suite -- replaced in Phase 1."""

    def test_placeholder(self):
        """Verify test infrastructure works."""
        self.assertTrue(True)

    def test_import_cyrus(self):
        """Verify the cyrus package is importable and advertises a semver version."""
        import cyrus
        self.assertIsInstance(cyrus.__version__, str)
        self.assertRegex(cyrus.__version__, r"^\d+\.\d+\.\d+")


if __name__ == "__main__":
    unittest.main()
