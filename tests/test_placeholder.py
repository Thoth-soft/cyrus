"""Placeholder test to validate CI pipeline."""

import re
import unittest


class TestPlaceholder(unittest.TestCase):
    """Placeholder test suite -- replaced in Phase 1."""

    def test_placeholder(self):
        """Verify test infrastructure works."""
        self.assertTrue(True)

    def test_import_sekha(self):
        """Verify the sekha package is importable and advertises a semver version."""
        import sekha
        self.assertIsInstance(sekha.__version__, str)
        self.assertRegex(sekha.__version__, r"^\d+\.\d+\.\d+")


if __name__ == "__main__":
    unittest.main()
