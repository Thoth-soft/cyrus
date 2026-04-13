---
phase: 07-polish-docs-release
plan: 01
subsystem: docs-release
tags: [docs, release, v0.1.0, pypi, github-release]
requirements_closed: [DOCS-01, DOCS-02, DOCS-03, DOCS-04, DOCS-05, DOCS-06]
requirements_deferred: [DOCS-07]
dependency_graph:
  requires: []
  provides:
    - "Real README.md with install flow, features, threat model, cross-client table"
    - "CHANGELOG.md with 0.1.0 entry (Keep a Changelog format)"
    - "examples/rules/ with 4 copy-paste-ready rules"
    - "docs/release.md runbook for PyPI publish"
    - "v0.1.0 git tag + GitHub release (live at https://github.com/Thoth-soft/sekha/releases/tag/v0.1.0)"
  affects:
    - "pyproject.toml (version: 0.0.0 -> 0.1.0)"
    - "src/sekha/__init__.py (__version__: 0.0.0 -> 0.1.0)"
    - "CONTRIBUTING.md (em-dash -> ASCII '--' fix)"
    - "tests/test_placeholder.py (unpin hardcoded 0.0.0 version assertion)"
tech_stack:
  added: []
  patterns:
    - "Keep a Changelog 1.1.0 format for release notes"
    - "gh release create + awk-extracted CHANGELOG section for tag body"
    - "ASCII-only policy enforced across all docs (cp1252-safe)"
key_files:
  created:
    - "CHANGELOG.md"
    - "examples/rules/block-rm-rf.md"
    - "examples/rules/block-force-push-main.md"
    - "examples/rules/block-drop-table.md"
    - "examples/rules/warn-no-tests-before-commit.md"
    - "docs/release.md"
  modified:
    - "README.md"
    - "CONTRIBUTING.md"
    - "pyproject.toml"
    - "src/sekha/__init__.py"
    - "tests/test_placeholder.py"
decisions:
  - "ASCII-only README/CHANGELOG: Yes/No in cross-client table instead of Unicode checkmarks (CONTEXT used U+2713/U+2717 but project policy forbids)"
  - "Benchmark numbers live in CHANGELOG, not README body (keep README pitch-focused)"
  - "Example rules place commentary in HTML comments AFTER the rule body so frontmatter parser (RULES-02) gets the opening --- on line 1"
  - "warn-no-tests-before-commit scoped to Bash + 'git\\s+commit' pattern; originally matched Edit/Write [.*] in fixtures -- tightened for examples/ to avoid triggering on every file edit"
  - "Retagged v0.1.0 to the test-fix commit (841621d) after CI exposed a stale 0.0.0 pin in test_placeholder.py. Release was under ten minutes old and never public-linked beyond the GitHub releases page, so force-retag was low-risk"
metrics:
  duration_seconds: 369
  duration_human: "~6 minutes"
  tasks_completed: 7
  files_created: 6
  files_modified: 5
  commits: 7
  completed: 2026-04-13
---

# Phase 7 Plan 01: Polish, Docs, and v0.1.0 Release Summary

Shipped v0.1.0 of Sekha: rewrote the README with the real pitch and threat
model, added a Keep-a-Changelog `CHANGELOG.md`, published 4 copy-paste example
rules, wrote the release runbook at `docs/release.md`, spot-checked
`CONTRIBUTING.md`, bumped the package to 0.1.0, and cut the
[v0.1.0 GitHub release](https://github.com/Thoth-soft/sekha/releases/tag/v0.1.0).
PyPI upload remains a user-initiated step documented in `docs/release.md`.

## What Shipped

### README.md (Task 1 -- DOCS-01, DOCS-02)

Replaced the 13-line Phase 0 skeleton with a full README: Why Sekha, Install,
Features, How It Works, Example Rules, Threat Model, Cross-Client Support,
Docs, Contributing, License. Threat Model opens verbatim with
"Sekha is a consistency enforcer, not a security sandbox." Cross-client
support table uses ASCII `Yes`/`No` instead of Unicode checkmarks (project
ASCII-only policy overrides the CONTEXT.md template). Links to `examples/rules/`,
`docs/hook-integration-test.md`, `CHANGELOG.md`, and `CONTRIBUTING.md` all
live.

- Commit: `6e7380e docs(07-01): rewrite README with v0.1.0 content`

### CHANGELOG.md (Task 2 -- DOCS-05)

New file at repo root in Keep a Changelog 1.1.0 format. `[0.1.0]` section has
Added / Performance / Quality subsections with the benchmark numbers, test
count (337+), 9-cell CI matrix, fresh-VM install gate, and zero-dependencies
claim. Tag URL footnote links the section to the GitHub release.

- Commit: `137336e docs(07-01): add CHANGELOG.md with 0.1.0 release notes`

### examples/rules/ (Task 3 -- DOCS-03)

Four copy-paste-ready rule files, all parse cleanly under
`sekha.rules.load_rules` in my verification run (4 rules loaded for Bash tool
target, ASCII-only, frontmatter on line 1 per RULES-02):

| File                              | Severity | Pattern                                              | Priority |
|-----------------------------------|----------|------------------------------------------------------|----------|
| `block-rm-rf.md`                  | block    | `rm\s+-rf\s+(/\|\*\|~\|\.)`                          | 100      |
| `block-force-push-main.md`        | block    | `git\s+push.*(--force\|-f).*\b(main\|master)\b`      | 90       |
| `block-drop-table.md`             | block    | `DROP\s+TABLE`                                       | 90       |
| `warn-no-tests-before-commit.md`  | warn     | `git\s+commit`                                       | 20       |

Each file ends with an HTML-comment commentary block explaining use case,
known escapes, and how to tighten/loosen.

- Commit: `2f534e5 docs(07-01): ship 4 example rules under examples/rules/`

### docs/release.md (Task 4)

New release runbook covering pre-flight checklist, tag + `gh release create`
(three options including `--generate-notes`), `python -m build`, `twine
check` + `twine upload` with `$PYPI_TOKEN`, artifact attachment via
`gh release upload`, post-release version bump, and troubleshooting for
common `twine`/`gh` errors.

- Commit: `f664bd5 docs(07-01): add release runbook with PyPI publish steps`

### CONTRIBUTING.md (Task 5 -- DOCS-04)

Spot-checked -- dev setup, test invocation, and PR guidelines all present.
Found three em-dashes (U+2014) violating project ASCII-only rule; replaced
with `--`. No structural changes.

- Commit: `b40cf0c docs(07-01): enforce ASCII-only in CONTRIBUTING.md`

### Release Prep (Task 7 -- DOCS-06)

Version bumped in both locations:

- `pyproject.toml` line 7: `0.0.0 -> 0.1.0`
- `src/sekha/__init__.py`: `__version__ = "0.1.0"`

Pushed main, tagged `v0.1.0`, created GitHub release with notes extracted
from the CHANGELOG `[0.1.0]` section via `awk`. Live URL:
<https://github.com/Thoth-soft/sekha/releases/tag/v0.1.0>.

- Commits: `9b12aa4 chore(release): bump version to 0.1.0`, `841621d fix(07-01): unpin placeholder test from 0.0.0 version` (retag target)

## Requirements Status

| Req      | Status      | Note                                                                 |
|----------|-------------|----------------------------------------------------------------------|
| DOCS-01  | Closed      | README has install + features + cross-client + examples link        |
| DOCS-02  | Closed      | Threat Model section with verbatim opener                            |
| DOCS-03  | Closed      | 4 rules parse cleanly under `sekha.rules`                            |
| DOCS-04  | Closed      | CONTRIBUTING.md carried forward from Phase 0 (ASCII fix only)        |
| DOCS-05  | Closed      | CHANGELOG.md with Keep-a-Changelog formatted `[0.1.0]` section       |
| DOCS-06  | Closed      | `v0.1.0` tag pushed to origin, GitHub release published with notes  |
| DOCS-07  | User action | Documented in `docs/release.md`; user runs `twine upload` when ready |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] CONTRIBUTING.md contained three em-dash (U+2014) characters**

- **Found during:** Task 5 verification (`all(ord(ch)<128 for ch in c)` failed)
- **Issue:** Phase 0 scaffolding file shipped with em-dashes in the Pull Requests section, violating project ASCII-only policy.
- **Fix:** Replaced each `--` (em-dash) with `--` (ASCII hyphen-hyphen).
- **Files modified:** `CONTRIBUTING.md`
- **Commit:** `b40cf0c`

**2. [Rule 1 - Bug] `test_placeholder.test_import_sekha` hardcoded `__version__ == "0.0.0"`**

- **Found during:** Post-release verification (`python -m unittest discover -s tests`) on the version-bump commit.
- **Issue:** Phase 0 placeholder test coupled itself to the pre-release version string; asserted equality to `"0.0.0"` which broke the moment we bumped to `0.1.0`. GitHub Actions CI confirmed the failure on commit `9b12aa4`.
- **Fix:** Rewrote the test to assert `sekha.__version__` is a string matching the semver shape `r"^\d+\.\d+\.\d+"` so future bumps do not regress. Also replaced a U+2014 em-dash in the test docstring with `--`.
- **Files modified:** `tests/test_placeholder.py`
- **Commit:** `841621d`
- **Follow-up:** Moved the `v0.1.0` tag from the broken `9b12aa4` commit to the fixed `841621d` commit (delete + recreate tag, both local and on origin; re-published the GitHub release out of the draft state it entered after the tag delete). CI on `841621d` came back green. Release was minutes old and never promoted externally, so the force-retag was low-risk.

**3. [Rule 2 - Missing Critical Functionality] `src/sekha/__init__.py` `__version__` bump**

- **Found during:** Plan prep (critical-rules block in prompt mentioned it; plan only mentioned `pyproject.toml`).
- **Issue:** Two sources of truth for version must stay in sync or `sekha.__version__` drifts from the PyPI wheel.
- **Fix:** Bumped both in the release-prep commit.
- **Files modified:** `src/sekha/__init__.py`
- **Commit:** `9b12aa4`

### Auth Gates

None. `gh` and `git push` were already authenticated on this machine.

### Checkpoint Auto-Approvals

Task 6 (human-verify) was auto-approved per user's standing permission:
"do all the work and I will review at the end." All artifacts from Tasks 1-5
passed automated verification before proceeding to Task 7.

## Verification Results

- `grep -c '^## ' README.md`: 10 sections (required 8+)
- README ASCII-only assertion: pass
- `python -m unittest discover -s tests`: 337 passed, 3 skipped, 0 failed (after `841621d`)
- `sekha.rules.load_rules('examples/rules', 'PreToolUse', 'Bash')`: 4 rules loaded, no parse errors
- `grep 'version = "0.1.0"' pyproject.toml`: match
- `grep '__version__ = "0.1.0"' src/sekha/__init__.py`: match
- `git tag -l v0.1.0`: `v0.1.0` (local)
- `gh release view v0.1.0 --json isDraft,body`: `isDraft=false`, body contains `### Added`
- `gh run list --limit 2 ... 841621d`: status=completed, conclusion=success
- Release URL: <https://github.com/Thoth-soft/sekha/releases/tag/v0.1.0>

## Next-Step Handoff

v0.1.0 is shippable from source **right now**:

```bash
pip install git+https://github.com/Thoth-soft/sekha.git@v0.1.0
```

To publish to PyPI (**user action**, requires `$PYPI_TOKEN`):

```bash
python -m pip install --upgrade build twine
python -m build
TWINE_USERNAME=__token__ TWINE_PASSWORD=$PYPI_TOKEN python -m twine upload dist/*
```

Full walkthrough: [`docs/release.md`](../../../docs/release.md). This closes
DOCS-07 and simultaneously reserves the `sekha` name on PyPI (Plan 00-02
bonus side effect).

After PyPI upload lands, the install instructions in README.md (`pip install
sekha`) start working as advertised.

## Known Stubs

None. Every section of the README, CHANGELOG, and docs points to live
content. The two `[30-second demo ...]` and `[Diagram: ...]` placeholders in
the README are intentionally-deferred-to-v0.1.1 items documented in
`07-CONTEXT.md <deferred>`; they are flagged as placeholders in plain text
so readers immediately see they are pending rather than mistake them for
broken embeds.

## Commits

| Hash      | Message                                                          |
|-----------|------------------------------------------------------------------|
| `6e7380e` | docs(07-01): rewrite README with v0.1.0 content                  |
| `137336e` | docs(07-01): add CHANGELOG.md with 0.1.0 release notes           |
| `2f534e5` | docs(07-01): ship 4 example rules under examples/rules/          |
| `f664bd5` | docs(07-01): add release runbook with PyPI publish steps         |
| `b40cf0c` | docs(07-01): enforce ASCII-only in CONTRIBUTING.md               |
| `9b12aa4` | chore(release): bump version to 0.1.0                            |
| `841621d` | fix(07-01): unpin placeholder test from 0.0.0 version            |

## Self-Check: PASSED

- README.md: FOUND (modified)
- CHANGELOG.md: FOUND (created)
- examples/rules/block-rm-rf.md: FOUND
- examples/rules/block-force-push-main.md: FOUND
- examples/rules/block-drop-table.md: FOUND
- examples/rules/warn-no-tests-before-commit.md: FOUND
- docs/release.md: FOUND
- CONTRIBUTING.md: FOUND (ASCII-fixed)
- pyproject.toml: FOUND (version=0.1.0)
- src/sekha/__init__.py: FOUND (__version__=0.1.0)
- tests/test_placeholder.py: FOUND (semver pattern assertion)
- Commits 6e7380e, 137336e, 2f534e5, f664bd5, b40cf0c, 9b12aa4, 841621d: all FOUND in `git log`
- Git tag v0.1.0: FOUND (local + origin)
- GitHub release v0.1.0: PUBLISHED, body contains `### Added`
- CI on 841621d: SUCCESS
