# Release Runbook

This document describes how to cut a release of Sekha. Some steps are
automated via the GitHub release workflow; the final PyPI upload remains a
user-initiated step because it requires a PyPI API token.

The primary examples here show a concrete `0.1.0` release. Swap in the next
`<version>` when you cut future releases.

## Pre-flight checklist

- [ ] All tests pass on CI (9-cell matrix green on the commit to be tagged).
- [ ] `CHANGELOG.md` has a section for the version being released.
- [ ] `pyproject.toml` `version` field matches the release version.
- [ ] Fresh-VM install test (CLI-08) green on the main branch.
- [ ] Dogfooding exit (Phase 4 HOOK-10) captured in
      `docs/hook-integration-test-evidence.*`.

## Tag and GitHub release

Extract the matching section from `CHANGELOG.md` for the release notes, then
tag and publish. Option A (temp file on a Unix-ish shell):

```bash
awk '/^## \[0.1.0\]/{flag=1;next} /^## \[/{flag=0} flag' CHANGELOG.md > /tmp/release-notes-0.1.0.md

git tag -a v0.1.0 -m "v0.1.0"
git push origin v0.1.0
gh release create v0.1.0 --title "v0.1.0" --notes-file /tmp/release-notes-0.1.0.md
```

Option B (inline, no temp file):

```bash
git tag -a v0.1.0 -m "v0.1.0"
git push origin v0.1.0
gh release create v0.1.0 --title "v0.1.0" --notes "$(awk '/^## \[0.1.0\]/{flag=1;next} /^## \[/{flag=0} flag' CHANGELOG.md)"
```

Option C (lazy, good notes): generate notes from commits and the CHANGELOG
link:

```bash
gh release create v0.1.0 --title "v0.1.0" --generate-notes
```

## Build distribution artifacts

```bash
python -m pip install --upgrade build twine
python -m build
ls dist/
```

Expected: a wheel and sdist named `sekha-0.1.0-*.whl` and
`sekha-0.1.0.tar.gz`.

## Upload to PyPI (user action)

This step requires a PyPI API token. Create one at
<https://pypi.org/manage/account/token/> and export it as `PYPI_TOKEN` for
this shell session only -- do not commit it, do not paste it into CI secrets
without scoping.

```bash
python -m twine check dist/*
TWINE_USERNAME=__token__ TWINE_PASSWORD=$PYPI_TOKEN python -m twine upload dist/*
```

The first successful upload of `sekha` also reserves the project name on
PyPI (this closes the Phase 0 DOCS-07 / PyPI-name-reservation todo as a side
effect).

## Attach artifacts to the GitHub release

```bash
gh release upload v0.1.0 dist/sekha-0.1.0*
```

Uploading after `gh release create` keeps the release notes authoritative
and attaches the wheel + sdist for users who want to grab them without PyPI.

## Post-release

- Bump `pyproject.toml` `version` to the next dev version
  (e.g. `0.1.1.dev0`) on main.
- Bump `__version__` in `src/sekha/__init__.py` to match.
- Add an empty `## [Unreleased]` section at the top of `CHANGELOG.md` so the
  next round of commits has a home.
- Open a GitHub milestone for the next version.

## Troubleshooting

- `twine upload` returns 403: token scope wrong or expired. Regenerate at
  <https://pypi.org/manage/account/token/> and retry.
- `twine upload` returns 400 `File already exists`: the version is already on
  PyPI. PyPI refuses re-uploads; bump the version and re-tag.
- `python -m build` fails: confirm `hatchling` installs cleanly
  (`python -m pip install --upgrade build`) and that `pyproject.toml` still
  parses (`python -c "import tomllib; tomllib.loads(open('pyproject.toml','rb').read().decode())"`).
- `gh release create` errors with auth: run `gh auth login`, then re-run.
  This is a one-time handshake per machine.
