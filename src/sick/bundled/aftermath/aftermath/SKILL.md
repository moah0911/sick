---
name: aftermath
description: >
  Post-failure recovery when something already broke: a test suite went green
  to red, the same error repeats after a fix, a destructive command was
  blocked, a forward edit is frozen, the user says "you broke it", or the fix
  touched files outside scope. Stop, revert cheap damage, diagnose honestly,
  return to last-known-good. Supports intensity levels lite, full (default),
  ultra, plus opt-in checkpoint auto-revert. Use ONLY for recovery after
  failure, not for planning new work.
license: MIT
---

# Aftermath

Recovery after failure. Most skills teach how to build. This one teaches how to stop when you broke something.

## Persistence

ACTIVE EVERY RESPONSE while a failure is unresolved. No drift back to forward-editing. Still active if unsure. Off only via `/aftermath off`. Default: **full**. Switch: `/aftermath lite|full|ultra|off`.

## The ladder

Stop at the first rung that holds. Re-read it mid-panic before your next edit:

1. Uncommitted / one file / cheap to undo? → Revert now. Do not patch forward.
2. Last-known-good exists (passing test, last commit)? → Diff against it, isolate the one change, revert just that.
3. 2nd+ failed attempt at the same fix? → Stop varying the fix. State the exact error, state your theory, ask.
4. Next action irreversible (force push, drop, delete, overwrite)? → Confirm current state explicitly. Do not proceed on assumption.
5. Filling a gap with a guess right now? → Say so out loud instead of continuing silently.
6. User just corrected you ("you broke it")? → Do not defend the last step. Find the diff. Fix only that.

## Enforcement

The OpenCode plugin turns the ladder's stop rules into tool guards at `full` and `ultra`:

- Destructive Bash (force push, reset --hard, clean -f, rm -rf, drop, prune, destroy) is **blocked** before it runs. `lite` only flags it; `off` disables the guard.
- `edit`/`write` is **blocked while a failure is unresolved**. Clear the guard by getting a test command green, running `/aftermath-revert`, or dropping to `lite`/`off`.
- Intentional exceptions go in `~/.config/aftermath/config.json` → `destructiveAllowlist` (array of command substrings).
- `aftermath init` / `/aftermath-init` writes project `safePaths` (disposable artifacts) and `protectedPaths` (source, VCS, secrets, manifests). Filesystem deletes under safe paths are allowed; protected or unknown targets stay blocked.
- Claude Code / Codex use `PreToolUse` for the same path policy and forward-edit freeze, and `PostToolUse` / `UserPromptSubmit` to deliver failure and correction reminders. They do not checkpoint files.
- Never try to bypass a block by rephrasing the command. Confirm state, then proceed deliberately.

## Checkpoints and ultra auto-revert

Checkpoints are OpenCode-only and opt-in:

- Enable with `{"autoRevert": true}` in `~/.config/aftermath/config.json`. Default is off.
- At `ultra`, every edited file is snapshotted before the edit. A passing test marks last-known-good and clears old snapshots.
- On a green→red test, restore runs only for files whose current content still matches the agent's edit. Manual edits are reported as conflicts and never overwritten.
- First red (no prior green), `full`, and `autoRevert: false` never restore.
- `/aftermath-checkpoint status|clear|restore` inspects, clears, or manually restores the store.
- Auto-revert never touches committed or pushed history.

## Attempt ledger

- Same error with no edit in between = the same attempt. Re-running is not a new try.
- Same error after an edit = the 2nd failed attempt. Stop, paste the exact error, state the theory, ask.
- A green test, `/aftermath-revert`, or `/aftermath off` resets the ledger.

## Rules

- Never hide that something broke. Say what broke in one line before doing anything else.
- Never silently revert at full intensity and above. Announce every revert: what was undone and why.
- Never fabricate a root cause that has not been verified. Unverified theory is labeled theory.
- One bad edit, then stop. Compounding-edit count is the metric: 1 bad edit + revert beats 4 bad edits + patch-around.
- Revert the actual bad hunk, not a patch around it. `git diff` first, smallest revert that restores last-known-good.
- Scope discipline: fix only the diff that broke. Anything outside the stated task goes in the audit, not in the fix.
- No forward edit while a failure is unresolved. The enforcement guard holds this line at full/ultra.

## Output

State first, then act: what broke (one line), what was undone (one line), what is next (one line). If the explanation is longer than the fix, the fix is not isolated yet.

Pattern: `broke: [X] → undid: [Y] → next: [Z].`

For an auto-revert: `broke: [X] → restored: [N files, conflicts] → next: re-run the failing subset.`

## Intensity

| Level | What changes |
|-------|--------------|
| **lite** | Flags the problem, suggests the revert, lets the user decide. No blocks, no auto-revert. |
| **full** | Stops forward motion automatically, blocks destructive commands and forward edits, runs the diagnostic (diff, isolate), asks before the next edit. Default. |
| **ultra** | Same guards as full, plus checkpoint auto-revert when `autoRevert: true`. Restores cheap uncommitted damage, then reports what was undone and why. |

Example: test suite went green to red after an edit.
- lite: "Tests broke after this edit (3 failures in auth.spec). Suggest reverting auth.ts hunk 2 — proceed?"
- full: "Stopping. Broke: auth.ts hunk 2 broke 3 tests. Undid nothing yet. Forward edits are blocked; revert just that hunk before any new edit."
- ultra: "Broke: auth.ts hunk 2 broke 3 tests. Undid: restored auth.ts to last green checkpoint. 3 tests green again. No other files touched."

## When NOT to recover

Anything explicitly committed, pushed, or marked irreversible by the user is not auto-reverted — not even on ultra. Confirm first. A revert you do not understand is a second bug. If a guard blocks work you believe is safe, confirm state and use the allowlist or `/aftermath lite`; do not disguise the command.

## Boundaries

Aftermath governs recovery, not construction. Once the session is back to last-known-good (tests green, diff clean, user confirms), stand down and return to the building skill. Level persists until changed or session end. Checkpoints and forward-edit enforcement are OpenCode capabilities; other hosts get the ladder and destructive-command blocking.
