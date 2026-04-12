"""Deterministic seeded markdown-corpus generator for Cyrus search benchmarks.

Given a fixed seed and count, produces byte-identical file trees across runs.
Consumed by tests/test_search_bench.py. Also runnable as a script for manual
corpus generation and inspection.
"""
from __future__ import annotations

import argparse
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cyrus.paths import CATEGORIES
from cyrus.storage import atomic_write, dump_frontmatter

# Fixed vocabulary so queries hit a predictable distribution.
_VOCAB = (
    "auth", "jwt", "refactor", "database", "migration", "schema",
    "hook", "mcp", "server", "client", "stdio", "protocol", "rules",
    "cyrus", "memory", "search", "storage", "index", "benchmark",
    "python", "stdlib", "pathlib", "regex", "frontmatter", "markdown",
    "windows", "linux", "macos", "encoding", "unicode", "atomic",
    "concurrent", "filelock", "msvcrt", "fcntl", "ci", "test",
    "session", "decision", "preference", "project", "rule", "config",
    "the", "a", "to", "of", "and", "in", "for", "on", "with", "is",
)
_TAGS = ("auth", "jwt", "hook", "mcp", "storage", "search", "rules", "ci", "perf", "docs")


def _hex_id(rng: random.Random) -> str:
    return "".join(rng.choice("0123456789abcdef") for _ in range(8))


def _slug(rng: random.Random) -> str:
    words = [rng.choice(_VOCAB) for _ in range(rng.randint(2, 5))]
    return "-".join(words)


def _body(rng: random.Random, min_lines: int = 5, max_lines: int = 30) -> str:
    n = rng.randint(min_lines, max_lines)
    lines = []
    for _ in range(n):
        wcount = rng.randint(4, 14)
        lines.append(" ".join(rng.choice(_VOCAB) for _ in range(wcount)))
    return "\n".join(lines) + "\n"


def generate_corpus(out_dir: Path, *, count: int, seed: int) -> int:
    """Generate `count` deterministic markdown files under out_dir/<category>/.

    Returns the number of files actually written. Idempotent: if a file
    with the exact expected path already exists, skip it (trusting the
    deterministic seed to guarantee content stability).

    Determinism guarantees:
      - Same (seed, count) -> same set of filenames (order-independent)
      - Same (seed, count) -> same file contents byte-for-byte

    Uses a seeded random.Random instance only — never `random` module state.
    """
    out_dir = Path(out_dir)
    rng = random.Random(seed)
    # Base date for the "created" spread: a fixed epoch so tests are
    # reproducible regardless of wall clock.
    base_date = datetime(2026, 1, 1, tzinfo=timezone.utc)

    written = 0
    for _ in range(count):
        category = CATEGORIES[rng.randrange(len(CATEGORIES))]
        age_days = rng.randrange(0, 180)
        when = base_date - timedelta(days=age_days)
        date_str = when.strftime("%Y-%m-%d")
        id_hex = _hex_id(rng)
        slug = _slug(rng)
        fname = f"{date_str}_{id_hex}_{slug}.md"
        path = out_dir / category / fname
        path.parent.mkdir(parents=True, exist_ok=True)

        # Consume RNG for tags/body unconditionally so the RNG stream is
        # identical whether we skip writing or not. This keeps generation
        # deterministic across re-runs of a partially-populated corpus.
        tags = rng.sample(_TAGS, k=rng.randint(0, 3))
        metadata = {
            "id": id_hex,
            "category": category,
            "created": when.isoformat(timespec="seconds"),
            "updated": when.isoformat(timespec="seconds"),
            "tags": list(tags),
        }
        body = _body(rng)

        if path.exists():
            # Idempotent: trust the filename (seed is deterministic).
            continue

        document = dump_frontmatter(metadata, body)
        atomic_write(path, document)
        written += 1
    return written


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate a deterministic Cyrus markdown corpus."
    )
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--count", type=int, default=10_000)
    parser.add_argument("--seed", type=int, default=0xC0FFEE)
    args = parser.parse_args(argv)
    n = generate_corpus(args.out, count=args.count, seed=args.seed)
    # stderr only — stdout is reserved for protocol output elsewhere in Cyrus
    print(f"wrote {n} files under {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
