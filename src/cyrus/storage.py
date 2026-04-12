"""Cyrus storage primitives: atomic writes, filelock, frontmatter, save_memory.

Stdlib only. Consumed by every higher-level Cyrus module (search, rules, hook,
server). The entire correctness story for on-disk memory hinges on the three
primitives here — atomic_write, filelock, and the hand-rolled YAML-subset
frontmatter parser/dumper — so every change here demands the full test suite.

Design notes:
- atomic_write writes to a sibling temp file, fsyncs, then os.replace onto the
  target. Temp must live in the SAME directory so os.replace is atomic even on
  exotic filesystems (cross-device rename would fall back to copy + unlink,
  which is NOT atomic).
- filelock picks fcntl.flock on POSIX and msvcrt.locking on Windows at IMPORT
  time, never runtime. A missing lock file is created on demand. Lock files
  are intentionally never deleted — races on cleanup are harmful and the
  footprint is trivial.
- Frontmatter parser accepts a hand-picked YAML subset: scalar strings/ints/
  bools, ISO-8601 timestamps as strings, flat flow-lists. Anything nested is
  rejected loudly. Emitted output sorts keys for stable diffs.
- save_memory is the single public write API — it composes make_memory_path,
  dump_frontmatter, filelock, and atomic_write so callers never have to hand-
  assemble the dance.
"""
from __future__ import annotations

import contextlib
import hashlib
import os
import re
import sys
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from cyrus.logutil import get_logger
from cyrus.paths import CATEGORIES, category_dir, cyrus_home  # noqa: F401 — cyrus_home re-used by downstream modules

_log = get_logger(__name__)

# --------------------------------------------------------------------------
# Platform-specific filelock primitive — resolved at import time
# --------------------------------------------------------------------------
if sys.platform == "win32":
    import msvcrt

    def _try_lock(fd: int) -> bool:
        try:
            # Lock a single byte at position 0 — the file always has >=1 byte
            # thanks to filelock() priming it, so this is safe on Windows.
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)  # type: ignore[attr-defined]
            return True
        except OSError:
            return False

    def _unlock(fd: int) -> None:
        try:
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)  # type: ignore[attr-defined]
        except OSError:
            pass
else:
    import fcntl

    def _try_lock(fd: int) -> bool:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except BlockingIOError:
            return False

    def _unlock(fd: int) -> None:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            pass


class FilelockTimeout(TimeoutError):
    """Raised when filelock() cannot acquire within the timeout window."""


@contextlib.contextmanager
def filelock(path: Path, *, timeout: float = 5.0) -> Iterator[None]:
    """Cross-process exclusive lock using <path>.lock sibling.

    Polls with exponential backoff when the lock is held. Guarantees release
    on exception. Raises FilelockTimeout after `timeout` seconds — never
    deadlocks.
    """
    path = Path(path)
    lock_path = path.with_name(path.name + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    # Open read+write, create if missing. Do NOT truncate — other holders'
    # priming byte stays intact.
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        # Ensure >= 1 byte exists so msvcrt.locking(fd, LK_NBLCK, 1) is valid
        if os.fstat(fd).st_size == 0:
            os.write(fd, b"\0")
        os.lseek(fd, 0, os.SEEK_SET)
    except OSError:
        os.close(fd)
        raise

    deadline = time.monotonic() + timeout
    backoff = 0.005
    acquired = False
    try:
        while True:
            if _try_lock(fd):
                acquired = True
                break
            if time.monotonic() >= deadline:
                raise FilelockTimeout(
                    f"filelock({path}) timed out after {timeout}s"
                )
            time.sleep(backoff)
            backoff = min(backoff * 1.5, 0.1)
        yield
    finally:
        if acquired:
            _unlock(fd)
        os.close(fd)


# --------------------------------------------------------------------------
# Atomic write
# --------------------------------------------------------------------------
def atomic_write(path: Path, content: str, *, encoding: str = "utf-8") -> None:
    """Write content to path atomically via fsync + os.replace.

    The temp file lives in the SAME directory as `path` so os.replace is
    guaranteed atomic. On any exception the destination is left unchanged and
    the temp file is best-effort unlinked.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(
        f"{path.name}.tmp.{os.getpid()}.{time.monotonic_ns()}"
    )
    try:
        data = content.encode(encoding)
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
        try:
            os.write(fd, data)
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(tmp, path)
    except BaseException:
        # Best-effort cleanup — file may already have been moved/removed
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass
        raise


# --------------------------------------------------------------------------
# Filename helpers
# --------------------------------------------------------------------------
_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(text: str, *, max_len: int = 40) -> str:
    """Lowercase, hyphenate, ASCII-only, strip to max_len chars.

    Empty/fully-stripped input returns 'untitled'. Accented characters are
    folded via NFKD normalization then ASCII-encoded with errors='ignore'.
    Path separators and all non-alnum runs collapse to a single hyphen.
    """
    normalized = unicodedata.normalize("NFKD", text)
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii").lower()
    collapsed = _SLUG_RE.sub("-", ascii_only).strip("-")
    if not collapsed:
        return "untitled"
    if len(collapsed) > max_len:
        collapsed = collapsed[:max_len].rstrip("-") or "untitled"
    return collapsed


def make_memory_path(
    category: str,
    title: str,
    *,
    when: datetime | None = None,
    seed: bytes | None = None,
) -> Path:
    """Build cyrus_home()/<category>/YYYY-MM-DD_<8hex>_<slug>.md.

    The id is blake2b(seed or (title|iso-timestamp), digest_size=4).hexdigest(),
    yielding exactly 8 hex chars. Does NOT create the file or parent directory.
    Raises ValueError if category is not one of CATEGORIES.
    """
    if category not in CATEGORIES:
        raise ValueError(
            f"Unknown category {category!r}. Valid: {CATEGORIES}"
        )
    if when is None:
        when = datetime.now(timezone.utc)
    date_part = when.strftime("%Y-%m-%d")
    slug = slugify(title)
    seed_bytes = (
        seed
        if seed is not None
        else f"{title}|{when.isoformat()}".encode("utf-8")
    )
    id_hex = hashlib.blake2b(seed_bytes, digest_size=4).hexdigest()
    return category_dir(category) / f"{date_part}_{id_hex}_{slug}.md"
