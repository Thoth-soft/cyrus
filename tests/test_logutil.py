"""Tests for sekha.logutil: stderr-only logger with ISO timestamp format."""

import io
import logging
import os
import sys
import unittest
from unittest import mock

from sekha.logutil import get_logger


class TestGetLogger(unittest.TestCase):
    def setUp(self) -> None:
        # Use a unique name per test to avoid cross-test handler leakage
        self.name = f"sekha.test.{self._testMethodName}"
        self._saved_env = os.environ.pop("SEKHA_LOG_LEVEL", None)

    def tearDown(self) -> None:
        # Clean up the logger we created so the process-wide registry stays sane
        logger = logging.getLogger(self.name)
        logger.handlers.clear()
        if hasattr(logger, "_sekha_configured"):
            delattr(logger, "_sekha_configured")
        os.environ.pop("SEKHA_LOG_LEVEL", None)
        if self._saved_env is not None:
            os.environ["SEKHA_LOG_LEVEL"] = self._saved_env

    def test_returns_logger(self) -> None:
        self.assertIsInstance(get_logger(self.name), logging.Logger)

    def test_idempotent_no_duplicate_handlers(self) -> None:
        a = get_logger(self.name)
        b = get_logger(self.name)
        self.assertIs(a, b)
        self.assertEqual(len(a.handlers), 1)

    def test_handler_targets_stderr(self) -> None:
        logger = get_logger(self.name)
        for h in logger.handlers:
            self.assertIsInstance(h, logging.StreamHandler)
            self.assertIs(h.stream, sys.stderr)
            self.assertIsNot(h.stream, sys.stdout)

    def test_format_iso_timestamp(self) -> None:
        buf = io.StringIO()
        with mock.patch("sys.stderr", buf):
            # Re-create logger so its handler binds to the patched stderr
            logger = logging.getLogger(self.name)
            logger.handlers.clear()
            if hasattr(logger, "_sekha_configured"):
                delattr(logger, "_sekha_configured")
            logger = get_logger(self.name)
            logger.info("hello")
        out = buf.getvalue().strip()
        pattern = (
            r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+00:00 "
            r"INFO sekha\.test\.test_format_iso_timestamp: hello$"
        )
        self.assertRegex(out, pattern)

    def test_propagate_false(self) -> None:
        self.assertFalse(get_logger(self.name).propagate)

    def test_default_level_info(self) -> None:
        self.assertEqual(get_logger(self.name).level, logging.INFO)

    def test_env_level_debug(self) -> None:
        os.environ["SEKHA_LOG_LEVEL"] = "DEBUG"
        self.assertEqual(get_logger(self.name).level, logging.DEBUG)

    def test_env_level_invalid_falls_back_to_info(self) -> None:
        os.environ["SEKHA_LOG_LEVEL"] = "NOT_A_REAL_LEVEL"
        self.assertEqual(get_logger(self.name).level, logging.INFO)


if __name__ == "__main__":
    unittest.main()
