"""Stderr-only structured logger for Sekha.

stdout is reserved for the future MCP server protocol stream (newline-delimited
JSON-RPC). Every log record in every Sekha module MUST go to stderr. This module
is the single sanctioned path to a logger — never call logging.basicConfig() or
attach a handler by hand elsewhere in the codebase.

Design:
- Idempotent per-logger configuration: calling get_logger("foo") twice returns
  the same Logger with exactly one StreamHandler. We tag the logger with
  `_sekha_configured` so re-configuration is a no-op.
- Explicit StreamHandler(sys.stderr) — never rely on logging defaults.
- propagate=False so the root logger never double-emits if something else in
  the process calls logging.basicConfig() (e.g. third-party test harness).
- ISO-8601 UTC timestamps with seconds precision (+00:00 offset form), parseable
  by every language's datetime library.
- SEKHA_LOG_LEVEL env var selects level; unknown values fall back to INFO
  rather than raising (loud config errors break tools invoked with odd envs).
"""

import logging
import os
import sys
from datetime import datetime, timezone

_ENV_LEVEL = "SEKHA_LOG_LEVEL"
_DEFAULT_LEVEL = logging.INFO
_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


class _IsoUtcFormatter(logging.Formatter):
    """Formatter that emits ISO-8601 UTC timestamps with seconds precision."""

    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:  # noqa: ARG002
        return datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(
            timespec="seconds"
        )


def _resolve_level() -> int:
    raw = os.environ.get(_ENV_LEVEL, "").upper().strip()
    if not raw:
        return _DEFAULT_LEVEL
    level = logging.getLevelName(raw)
    # logging.getLevelName returns int for valid level names, str for unknown.
    if isinstance(level, int):
        return level
    return _DEFAULT_LEVEL


def get_logger(name: str) -> logging.Logger:
    """Return a stderr-only Logger with ISO-timestamped format.

    Idempotent: repeated calls with the same name return the same Logger
    without stacking duplicate handlers. The level is re-resolved from the
    SEKHA_LOG_LEVEL env var on every call so tests can change it dynamically.
    """
    logger = logging.getLogger(name)
    if not getattr(logger, "_sekha_configured", False):
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(_IsoUtcFormatter(_FORMAT))
        logger.addHandler(handler)
        logger.propagate = False
        logger._sekha_configured = True  # type: ignore[attr-defined]
    logger.setLevel(_resolve_level())
    return logger
