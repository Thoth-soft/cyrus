# Phase 4 End-to-End Integration Test (HOOK-10)

**Goal:** prove that a Sekha rule actually blocks a Bash tool call inside a
real Claude Code session. This is the felt-experience exit criterion for
Phase 4 — unit tests verify the JSON shape, but only a real Claude Code
session verifies that *our* JSON shape is the one Claude Code currently
accepts.

This runbook is the manual version (Phase 4). An automated version via a
headless Claude Code harness is deferred to a v2 concern.

## Prerequisites

- Claude Code installed and working (no Sekha changes required yet — try
  a normal session first to confirm the baseline)
- Python 3.11 or newer on PATH (`python --version`)
- A checkout of this repository at the current phase-4 branch / main

## Setup

### 1. Install Sekha from source (editable)

From the repo root:

```
pip install -e .
```

Verify:

- `sekha --help` prints the CLI usage
- `sekha hook --help` lists `run`, `bench`, `enable`, `disable`

If the `sekha` command is not found after install, either reactivate your
virtualenv or substitute `python -m sekha.cli` for `sekha` in every
command below (the hook `command:` in `settings.json` can use either).

### 2. Install the block-bash rule

```
mkdir -p ~/.sekha/rules
cp tests/fixtures/bench_rules/block-bash.md ~/.sekha/rules/
```

As shipped, the rule's pattern is `rm -rf` (anchored false), so it only
blocks Bash commands containing that literal substring. For the
"block ALL Bash" demo, edit the copy in `~/.sekha/rules/block-bash.md`
and change:

```
pattern: rm -rf
```

to:

```
pattern: .
```

Leave `anchored: false`. Now any Bash command (one character or more)
matches and is blocked.

### 3. Register the hook in `~/.claude/settings.json`

**Back up first:**

```
cp ~/.claude/settings.json ~/.claude/settings.json.bak
```

Edit `~/.claude/settings.json` and add the following (or merge into any
existing `hooks` block):

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          { "type": "command", "command": "sekha hook run" }
        ]
      }
    ]
  }
}
```

Phase 6 will automate this via `sekha init`. For Phase 4, the registration
is manual on purpose — we want to feel the friction before we automate it.

If `sekha` isn't on PATH inside the shell Claude Code spawns (common on
Windows when using virtualenvs), substitute the full absolute path to the
`sekha` executable, or use `python -m sekha.cli hook run`.

## Run the test

1. Launch Claude Code in a project directory. Any project will do.
2. Ask Claude: **"Run `ls -la` in the terminal."**
3. Expected:
   - Claude attempts a Bash tool call
   - The tool call is **blocked** by Sekha
   - Claude's response includes text like
     `rm -rf is blocked by Sekha (bench fixture)` — the `message:` from
     the rule file
   - The `ls` command did NOT actually execute
4. Ask Claude: **"Read the README file."**
5. Expected:
   - The Read tool call proceeds normally
   - Confirms the rule is scoped to Bash (matcher narrow) and not
     over-matching

## Verification checklist

- [ ] Bash tool calls are blocked with the rule message visible to the user
- [ ] Non-Bash tools (Read, Write, Edit) still work normally
- [ ] `~/.sekha/hook-errors.log` is empty or does not exist
      — if present, the hook is erroring and silently allowing (fail-open
      is intended behavior, but its presence means something's off and
      needs investigation before shipping)
- [ ] `~/.sekha/hook-disabled.marker` does NOT exist
      — if it does, the kill-switch tripped and the hook is short-circuiting
      to allow; run `sekha hook enable` to clear

## Capture evidence

Take a screenshot or copy the terminal transcript showing the blocked
Bash call, and save it next to this runbook as:

- `docs/hook-integration-test-evidence.png` (screenshot), or
- `docs/hook-integration-test-evidence.txt` (transcript)

This is the proof artifact for the Phase 4 exit checkpoint. Phase 6's
fresh-VM install test will re-run this same runbook to confirm the hook
is still wired correctly — keep the format readable.

## Expected output snippets

**When Sekha blocks a Bash call**, the hook writes this JSON to stdout
(the bytes Claude Code reads):

```json
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": "rm -rf is blocked by Sekha (bench fixture)"
  }
}
```

and exits with code 2 (belt-and-suspenders — stdout JSON is the primary
signal, exit 2 is the documented backup path per the Claude Code hook
contract).

**Inside Claude Code**, the user-visible surface looks like (exact
wording depends on the Claude Code version):

> I tried to run `ls -la` but a Sekha rule blocked it: "rm -rf is blocked
> by Sekha (bench fixture)". Let me know if you'd like to proceed a
> different way.

## Cleanup

Restore the previous Claude Code settings and remove the test rule:

```
rm ~/.sekha/rules/block-bash.md
cp ~/.claude/settings.json.bak ~/.claude/settings.json
```

If you changed the pattern to `.` for the block-all demo, either delete
the rule file or restore the original `rm -rf` pattern before leaving it
in place.

## Troubleshooting

**Bash runs anyway, no block.** Check the hook in isolation:

```
sekha hook run < tests/fixtures/hook_events/bash_rm_rf.json
```

Expected: JSON with `"permissionDecision": "deny"` on stdout and exit 2.
If stdout is empty, the rule isn't loading — check `~/.sekha/rules/`
permissions and file name.

You can also dry-run the rule match directly (Phase 3 diagnostic):

```
sekha rule test block-bash Bash '{"command":"rm -rf /tmp"}'
```

**Claude Code errors about the hook.** Inspect `~/.claude/settings.json`
for JSON syntax errors. The hook `command` must be exactly `sekha hook run`
(or `python -m sekha.cli hook run`) with no surrounding quoting
weirdness; malformed JSON in `settings.json` disables all hooks silently.

**`sekha: command not found`.** The editable install didn't put the
console script on PATH. Either reactivate the venv, or use
`python -m sekha.cli hook run` as the `command:` string in
`~/.claude/settings.json`.

**Hook seems slow.** Measure the cold-start numbers:

```
sekha hook bench
```

Expected on Linux: p50<50ms, p95<150ms (HOOK-08 budget).
Expected on Windows: p50~130ms, p95~180ms due to Python cold-start
(override via `SEKHA_HOOK_P95_MS=300` if running bench in CI).

If p95 regresses substantially over these numbers, that's a real
performance regression worth investigating before shipping. Likely
culprit: a non-stdlib import sneaking into the hot path (check `import
time` output via `python -X importtime -m sekha.cli hook run < fixture`).

**Hook is fail-open-ing (tool calls succeed despite rules).** Check
`~/.sekha/hook-errors.log` for tracebacks — any exception during the
hook pipeline causes fail-open by design (HOOK-06). Three consecutive
errors in 10 minutes trip the kill switch; clear with `sekha hook enable`
after fixing the root cause.

## Exit criterion

Phase 4 is complete when the tester (Mo) has:

1. Run the test successfully: Claude Code attempted a Bash call and was
   blocked by the Sekha rule
2. Confirmed non-Bash tools still work
3. Captured the evidence file
4. Recorded the subjective reaction — **did the block feel useful, or
   annoying?** This is the input to the "dogfooding exit" decision for
   v0.1.0 release.
