---
phase: 06-cli-install
plan: 02
subsystem: infra
tags: [github-actions, ci, install-smoke, cli, cross-platform]

# Dependency graph
requires:
  - phase: 06-cli-install
    provides: "sekha init + sekha doctor --json CLI entry points (Plan 06-01)"
provides:
  - "install-test CI job: fresh-VM end-to-end install smoke on ubuntu/macos/windows"
  - "HARD RELEASE GATE (CLI-08) continuously verified on every push/PR"
  - "Idempotency smoke test for sekha init in CI"
affects: [07-docs-release, future PyPI publish plans]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "shell: bash on every CI step for uniform Win/macOS/Linux semantics"
    - "Heredoc-embedded Python assertion scripts (stdlib-only) for JSON validation in CI"
    - "set -euo pipefail in multi-line bash blocks to catch silent failures"

key-files:
  created: []
  modified:
    - ".github/workflows/ci.yml"

key-decisions:
  - "Python 3.11 only for install-test (the test job already covers 3×3 matrix; install-smoke needs one Python per OS to prove CLI-08)"
  - "No needs: clause on install-test — runs in parallel with unit-test job"
  - "fail-fast: false so a single OS failure doesn't mask the others"
  - "6 required doctor checks enforced in CI: python_version, sekha_on_path, sekha_home_writable, settings_hook_registered, mcp_canary, kill_switch (recent_hook_errors is informational)"

patterns-established:
  - "CI assertion pattern: emit JSON from CLI, parse with inline heredoc Python, fail with readable message listing unmet checks"
  - "Idempotency verification pattern: run command twice, then assert disk state has exactly one entry"

requirements-completed: [CLI-08]

# Metrics
duration: 2min 25s
completed: 2026-04-13
---

# Phase 6 Plan 02: Fresh-VM Install Test CI Job Summary

**install-test GitHub Actions job on 3-OS matrix running `pip install -e . && sekha init && sekha doctor --json` end-to-end, enforcing 6 required doctor checks plus hook idempotency — the HARD RELEASE GATE for CLI-08 is now continuously verified.**

## Performance

- **Duration:** 2min 25s
- **Started:** 2026-04-13T01:40:51Z
- **Completed:** 2026-04-13T01:43:16Z
- **Tasks:** 1
- **Files modified:** 1

## Accomplishments
- Added `install-test` job to `.github/workflows/ci.yml` with 3-OS matrix (ubuntu-latest, macos-latest, windows-latest) on Python 3.11
- Job runs `pip install -e . → sekha init → sekha doctor --json` end-to-end and asserts 6 required doctor checks pass
- Idempotency smoke: second `sekha init` asserts exactly one `sekha hook run` entry in `~/.claude/settings.json`
- CI green on all 3 install-test cells and all 9 unit-test cells on first push — CLI-08 release gate verified

## Task Commits

Each task was committed atomically:

1. **Task 1: Add install-test CI job to ci.yml** — `fd07d3f` (ci)

**Plan metadata:** to be added after SUMMARY is written (docs: complete plan)

_Note: Single-task plan, no TDD pairing — the CI job's automated verify (YAML structure) runs locally, then the actual green status is verified on GitHub Actions._

## Files Created/Modified
- `.github/workflows/ci.yml` — Added new `install-test` job (78 insertions). Existing `test` job unchanged.

## Decisions Made
- **Python 3.11 only for install-test:** The `test` job already runs 3×3 (3 OSes × 3 Python versions) for unit tests. The install-smoke exists to prove the CLI-08 release gate; one Python version per OS is sufficient and cuts CI minutes.
- **`shell: bash` on every step:** Windows runners ship Git Bash, so bash gives uniform semantics (`$HOME`, `ls`, `cat`) across all 3 OSes and avoids PowerShell/cmd escaping.
- **`fail-fast: false`:** Mirrors the existing `test` job policy — one OS failure shouldn't mask the others when triaging.
- **No `needs:` clause:** install-test is independent of the unit-test job; running them in parallel keeps end-to-end wall time unchanged.
- **Assertion via inline Python heredoc:** `python - <<'PY' ... PY` keeps the CI file self-contained (no extra scratch scripts) and mirrors Sekha's stdlib-only discipline.
- **`set -euo pipefail` in multi-line blocks:** Prevents silent failures from masking doctor-check failures.

## Deviations from Plan

None — plan executed exactly as written. The full YAML block from the plan's Task 1 was appended verbatim.

## Issues Encountered

- **Local verify missing PyYAML:** The plan's automated verify step uses `import yaml`, but PyYAML isn't a project dep (Sekha is stdlib-only). Resolved by installing PyYAML into the dev Python via `python -m pip install pyyaml`. This is a local-only dev tool — not committed, not a project dep. The CI itself does not depend on PyYAML at all.

## User Setup Required

None — no external service configuration required. CI picks up the new job automatically via `on: push` / `on: pull_request`.

## Next Phase Readiness

- **CLI-08 HARD RELEASE GATE satisfied:** Every push/PR now runs `pip install -e . && sekha init && sekha doctor --json` on ubuntu/macos/windows with Python 3.11. Install regressions will be caught at PR time, not at release time.
- **Phase 6 complete:** All CLI requirements (CLI-01..08) shipped. Ready for Phase 7 (docs & release prep).
- **Known follow-up (not a blocker):** Once v0.1.0 ships to PyPI (Phase 7+), a tag-gated second install-smoke job can switch from `pip install -e .` to `pip install sekha==<version>` to prove PyPI install path (not just editable-install path).
- **CI observation:** GitHub emitted a Node.js 20 deprecation warning for `actions/checkout@v4` and `actions/setup-python@v5` — forced upgrade to Node.js 24 on 2026-06-02. Non-blocking; address in a follow-up chore plan when the actions publish Node 24-compatible versions.

## Self-Check: PASSED

- `.github/workflows/ci.yml` exists with new `install-test` job (verified via YAML parse: job present, matrix correct, sekha init + doctor steps present)
- `.planning/phases/06-cli-install/06-02-SUMMARY.md` exists
- Commit `fd07d3f` exists in git log
- CI run 24321798671 completed: all 3 install-test cells green, all 9 unit-test cells green

---
*Phase: 06-cli-install*
*Completed: 2026-04-13*
