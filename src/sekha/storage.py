"""Sekha storage primitives: atomic writes, filelock, frontmatter, save_memory.

Stdlib only. Consumed by every higher-level Sekha module (search, rules, hook,
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

from sekha.logutil import get_logger
from sekha.paths import CATEGORIES, category_dir, sekha_home  # noqa: F401 — sekha_home re-used by downstream modules

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
    """Build sekha_home()/<category>/YYYY-MM-DD_<8hex>_<slug>.md.

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


# --------------------------------------------------------------------------
# Frontmatter — hand-rolled YAML subset
# --------------------------------------------------------------------------
_FM_DELIM = "---"


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Parse YAML-subset frontmatter. Returns (metadata, body).

    Supported value types: str, int, bool, ISO-8601 date/datetime (kept as str),
    flat flow-list ([a, b, c]). No nesting, no anchors, no block scalars.
    Tolerates CRLF line endings. Returns ({}, text) when no leading '---'.
    Raises ValueError on unclosed blocks or malformed key:value lines.
    """
    # Normalize CRLF to LF for parsing only — body is recomputed from norm
    # so the returned body is LF-terminated too. Callers that need CRLF
    # must re-encode themselves.
    norm = text.replace("\r\n", "\n").replace("\r", "\n")
    if not norm.startswith(_FM_DELIM + "\n") and norm.strip() != _FM_DELIM:
        return ({}, text)
    lines = norm.split("\n")
    if not lines or lines[0] != _FM_DELIM:
        return ({}, text)
    try:
        end_idx = next(
            i for i in range(1, len(lines)) if lines[i] == _FM_DELIM
        )
    except StopIteration:
        raise ValueError("Unclosed frontmatter: missing closing '---'")

    meta: dict[str, Any] = {}
    for raw in lines[1:end_idx]:
        line = raw.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            raise ValueError(f"Malformed frontmatter line: {raw!r}")
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if not key:
            raise ValueError(f"Empty key in frontmatter line: {raw!r}")
        meta[key] = _parse_value(value)

    # Body = everything after the closing delimiter line. We join with \n;
    # if the original text had a trailing \n after the closing delimiter,
    # the split produced a final "" element which rejoins cleanly.
    body_lines = lines[end_idx + 1:]
    body = "\n".join(body_lines)
    # Common case: "---\nkey: v\n---\nbody" → body_lines = ["body"]. Fine.
    # Edge case: "---\nkey: v\n---\n" → body_lines = [""] → body = "".
    return (meta, body)


def _parse_value(v: str) -> Any:
    if not v:
        return ""
    # Quoted string — strip outer quotes, no escape handling beyond verbatim
    if (v.startswith('"') and v.endswith('"')) or (
        v.startswith("'") and v.endswith("'")
    ):
        return v[1:-1]
    # Flow list: [a, b, c] — supports empty list [] and nested-quoted items
    if v.startswith("[") and v.endswith("]"):
        inner = v[1:-1].strip()
        if not inner:
            return []
        return [_parse_value(item.strip()) for item in inner.split(",")]
    if v == "true":
        return True
    if v == "false":
        return False
    if re.fullmatch(r"-?\d+", v):
        return int(v)
    # Otherwise keep as string — includes ISO timestamps, bare words, etc.
    return v


def dump_frontmatter(metadata: dict[str, Any], body: str) -> str:
    """Serialize metadata + body to '---\\n<sorted kv>\\n---\\n<body>'.

    Keys emitted alphabetically for deterministic diffs. Flat lists render
    as flow style. Strings requiring quoting (contain ':' or start with a
    structural char) are double-quoted. Nested dicts/lists raise ValueError.
    """
    lines = [_FM_DELIM]
    for key in sorted(metadata.keys()):
        lines.append(f"{key}: {_dump_value(metadata[key])}")
    lines.append(_FM_DELIM)
    return "\n".join(lines) + "\n" + body


_QUOTE_TRIGGER_CHARS = ("[", "{", "-", "#", "&", "*", "!", "|", ">", "'", '"')


def _dump_value(v: Any) -> str:
    # bool MUST be checked before int — bool is a subclass of int in Python
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, list):
        for item in v:
            if isinstance(item, (list, dict)):
                raise ValueError(
                    "Nested collections are not supported in frontmatter"
                )
        return "[" + ", ".join(_dump_value(item) for item in v) + "]"
    if isinstance(v, dict):
        raise ValueError("Nested dicts are not supported in frontmatter")
    if isinstance(v, str):
        if ":" in v or (v and v.startswith(_QUOTE_TRIGGER_CHARS)):
            escaped = v.replace('"', '\\"')
            return f'"{escaped}"'
        return v
    if v is None:
        return '""'
    raise ValueError(
        f"Unserializable frontmatter value type: {type(v).__name__}"
    )


# --------------------------------------------------------------------------
# High-level save_memory
# --------------------------------------------------------------------------
def save_memory(
    category: str,
    content: str,
    *,
    title: str | None = None,
    tags: list[str] | None = None,
    source: str | None = None,
    extra_metadata: dict[str, Any] | None = None,
) -> Path:
    """Create a memory file under sekha_home()/<category>/.

    Composes make_memory_path + dump_frontmatter + filelock + atomic_write.
    Builds default frontmatter: id (from filename hash), category, created
    and updated (ISO-UTC, seconds precision), tags (defaults to []), and an
    optional source. extra_metadata is merged in but cannot override core
    fields. Returns the final Path. Raises ValueError if category invalid.
    """
    if category not in CATEGORIES:
        raise ValueError(
            f"Unknown category {category!r}. Valid: {CATEGORIES}"
        )
    when = datetime.now(timezone.utc)
    effective_title = title or (
        content.splitlines()[0][:80] if content.strip() else "untitled"
    )
    path = make_memory_path(category, effective_title, when=when)
    # Re-extract id from filename so frontmatter and filename stay in sync.
    id_hex = path.stem.split("_", 2)[1]
    metadata: dict[str, Any] = {
        "id": id_hex,
        "category": category,
        "created": when.isoformat(timespec="seconds"),
        "updated": when.isoformat(timespec="seconds"),
        "tags": list(tags) if tags else [],
    }
    if source is not None:
        metadata["source"] = source
    if extra_metadata:
        for k, v in extra_metadata.items():
            if k in metadata:
                continue  # Core fields are not overridable
            metadata[k] = v
    document = dump_frontmatter(metadata, content)
    path.parent.mkdir(parents=True, exist_ok=True)
    with filelock(path, timeout=5.0):
        atomic_write(path, document)
    _log.info("saved memory %s", path.as_posix())
    return path
