"""Path resolution for Sekha. Honors SEKHA_HOME env var; uses pathlib.Path only.

This module is intentionally tiny and has zero internal dependencies. Every
downstream Sekha module (storage, search, server, hook) calls sekha_home() to
locate the on-disk memory tree, so changing the contract here breaks everything.

Design:
- SEKHA_HOME env var wins if set (resolved + expanduser-d).
- Otherwise default to ~/.sekha/.
- NEVER cache: tests and embedded uses override the env mid-process.
- Returned paths are always absolute (.resolve()) so callers never see relative
  paths that would break when the process cwd changes.
- The 5-category taxonomy (sessions, decisions, preferences, projects, rules)
  is fixed — the storage layer enforces no other top-level folders exist.
"""

import os
from pathlib import Path
from typing import Final

CATEGORIES: Final[tuple[str, ...]] = (
    "sessions",
    "decisions",
    "preferences",
    "projects",
    "rules",
)

_DEFAULT_DIRNAME = ".sekha"
_ENV_VAR = "SEKHA_HOME"


def sekha_home() -> Path:
    """Return the resolved absolute Path to the Sekha home directory.

    Honors the SEKHA_HOME env var; if unset, defaults to Path.home() / ".sekha".
    Reads the env var on every call (no caching) so tests can override per-test.
    Does NOT create the directory — callers are responsible for mkdir.
    """
    override = os.environ.get(_ENV_VAR)
    if override:
        return Path(override).expanduser().resolve()
    return (Path.home() / _DEFAULT_DIRNAME).resolve()


def category_dir(category: str) -> Path:
    """Return sekha_home() / <category>.

    Raises ValueError with the list of valid categories if the argument is not
    one of the fixed 5-tuple CATEGORIES.
    """
    if category not in CATEGORIES:
        raise ValueError(
            f"Unknown category {category!r}. Valid categories: {CATEGORIES}"
        )
    return sekha_home() / category
