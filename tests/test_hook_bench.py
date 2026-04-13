"""Hook latency benchmark for Sekha.

Gated by SEKHA_BENCH env var so fast CI stays fast. To run:
    SEKHA_BENCH=1 python -m unittest tests.test_hook_bench -v

Asserts p50 <= 50ms and p95 <= 150ms across 100 real-subprocess runs of
`python -m sekha.cli hook run`. Covers HOOK-08.

Platform-aware default p95: looser on Windows where Python cold-start
alone is 100-250ms. Override via SEKHA_HOOK_P95_MS for tighter CI
enforcement on a Linux runner. Mirrors the Phase 2 search bench pattern
(see tests/test_search_bench.py for the precedent).

The bench intentionally subprocesses `-m sekha.cli` rather than timing
in-process: in-process would hide exactly the Python interpreter launch
cost Claude Code pays on every tool invocation.
"""
# Requirement coverage:
#   HOOK-08: p50<=50ms / p95<=150ms cold-start budget, CI-gated
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

_BENCH_ENABLED = bool(os.environ.get("SEKHA_BENCH"))
_RUNS = 100
_REPO_ROOT = Path(__file__).resolve().parent.parent
_FIXTURES_RULES = _REPO_ROOT / "tests" / "fixtures" / "bench_rules"
_FIXTURES_EVENT = _REPO_ROOT / "tests" / "fixtures" / "hook_events" / "bash_rm_rf.json"

# Default budgets per HOOK-08. Override for per-platform relaxation or
# tighter CI enforcement. Win32 gets a looser p95 because Python cold
# start alone is 100-250ms on Windows — same precedent as Phase 2 search.
_P50_BUDGET_MS = float(os.environ.get("SEKHA_HOOK_P50_MS", "50"))
_P95_BUDGET_MS = float(
    os.environ.get(
        "SEKHA_HOOK_P95_MS",
        "300" if sys.platform == "win32" else "150",
    )
)


@unittest.skipUnless(_BENCH_ENABLED, "Set SEKHA_BENCH=1 to run benchmark")
class HookLatencyBenchmark(unittest.TestCase):
    def test_p50_and_p95_within_budget(self):
        self.assertTrue(_FIXTURES_RULES.exists(), f"missing {_FIXTURES_RULES}")
        self.assertTrue(_FIXTURES_EVENT.exists(), f"missing {_FIXTURES_EVENT}")

        event_bytes = _FIXTURES_EVENT.read_bytes()

        with tempfile.TemporaryDirectory() as tmp:
            tmp_home = Path(tmp)
            rules_dir = tmp_home / "rules"
            rules_dir.mkdir()
            for f in _FIXTURES_RULES.glob("*.md"):
                shutil.copy(f, rules_dir / f.name)
            env = {**os.environ, "SEKHA_HOME": str(tmp_home)}

            # Warm-up — excluded from the sample so first-run FS cache
            # miss doesn't contaminate p50.
            subprocess.run(
                [sys.executable, "-m", "sekha.cli", "hook", "run"],
                input=event_bytes,
                env=env,
                capture_output=True,
                timeout=10,
            )

            samples: list[float] = []
            for _ in range(_RUNS):
                t0 = time.perf_counter()
                subprocess.run(
                    [sys.executable, "-m", "sekha.cli", "hook", "run"],
                    input=event_bytes,
                    env=env,
                    capture_output=True,
                    timeout=10,
                )
                samples.append((time.perf_counter() - t0) * 1000.0)

        samples.sort()
        p50 = samples[_RUNS // 2]
        p95 = samples[int(_RUNS * 0.95) - 1]
        p99 = samples[int(_RUNS * 0.99) - 1]
        sys.stderr.write(
            f"\nHOOK BENCH: p50={p50:.1f}ms p95={p95:.1f}ms p99={p99:.1f}ms "
            f"(budgets p50<={_P50_BUDGET_MS:.0f}ms p95<={_P95_BUDGET_MS:.0f}ms)\n"
        )
        self.assertLessEqual(
            p50, _P50_BUDGET_MS, f"p50 {p50:.1f}ms > {_P50_BUDGET_MS}ms"
        )
        self.assertLessEqual(
            p95, _P95_BUDGET_MS, f"p95 {p95:.1f}ms > {_P95_BUDGET_MS}ms"
        )


if __name__ == "__main__":
    unittest.main()
