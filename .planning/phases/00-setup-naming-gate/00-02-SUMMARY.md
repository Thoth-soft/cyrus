---
phase: 00-setup-naming-gate
plan: 02
status: deferred
date: 2026-04-13
blocker: external_credentials_required
---

# Plan 00-02 Summary: PyPI Reservation (DEFERRED)

## Status

**Deferred** — waiting on user to provide PyPI credentials.

This plan cannot be executed by Claude autonomously because it requires:
1. A PyPI account (user must create)
2. 2FA enabled on PyPI (user must configure)
3. An API token scoped to the `sekha` package (user must generate)

None of these can be automated without the user's login.

## What's Needed from User

1. Go to https://pypi.org/account/register/ — create account
2. Enable 2FA (PyPI requires it for publishing)
3. Go to https://pypi.org/manage/account/token/ — generate API token
   - Name: `sekha-publish`
   - Scope: "Entire account" initially (can scope to project after first upload)
4. Paste the token (starts with `pypi-AgEI...`) — Claude will complete the upload

## Plan Execution (When User Provides Token)

```bash
cd ~/gsd-workspaces/cortex
python -m pip install --upgrade build twine
python -m build  # produces dist/sekha-0.0.0-py3-none-any.whl and dist/sekha-0.0.0.tar.gz
TWINE_USERNAME=__token__ TWINE_PASSWORD="<pasted_token>" python -m twine upload dist/*
```

Then verify: `pip install sekha==0.0.0` succeeds from a clean venv.

## Requirements Addressed (When Unblocked)

- **SETUP-01** — name reserved on PyPI
- **SETUP-05** — v0.0.0 placeholder package live

## Impact of Deferral

**Low.** PyPI name reservation is a one-way guard against squatters, but the actual `sekha` name is still available (verified 2026-04-11). The Phase 0 gate (enforced by Plan 00-01) achieved:
- Repo exists with correct scaffolding
- CI matrix proven green on 9 cells
- Python 3.11+ locked in `pyproject.toml`
- Zero dependencies enforced structurally

Phase 1 (Storage Foundation) can proceed with no dependency on Plan 00-02.

## Self-Check: DEFERRED (not failed — blocked on user action)
