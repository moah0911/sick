---
name: aftermath
description: >
  Post-failure recovery when something already broke: test suite went green to
  red, same error repeats after a fix, build or dependency resolution fails, a
  test is flaky, a merge conflicts, a destructive command is blocked, a forward
  edit is frozen, user says "you broke it", or the fix touched files outside
  scope. Stop, revert cheap damage, diagnose honestly, return to last-known-good.
  Supports lite/full/ultra, opt-in checkpoint autoRevert. Use ONLY for recovery
  after failure, not for planning new work.
license: MIT
---

# Aftermath — using the recovery agent

You are operating the Aftermath recovery skill. Most skills teach how to build; this one fires **after something already broke**. Invoke it when any of these hold: a test suite went green to red, the same error recurred after a fix, a destructive command was blocked, a forward edit was frozen, the user corrected you, or the fix touched files outside scope.

## The ladder

Stop at the first rung that holds, before your next edit:

1. Uncommitted / one file / cheap to undo? → Revert now. Do not patch forward.
2. Last-known-good exists? → Diff it, isolate one change, revert just that.
3. 2nd+ failed attempt at the same fix? → State exact error, state theory, ask.
4. Next action irreversible? → Confirm state explicitly. Never assume.
5. Filling a gap with a guess? → Say so out loud. Never continue silently.
6. User just corrected you? → Do not defend. Find the diff. Fix only that.

Honesty: never hide a break. Never silently revert. Never invent an unverified root cause.

## Intensity and commands

- Levels: `lite` (suggest) · `full` (default: stop, diagnose, ask) · `ultra` (guards + opt-in checkpoint autoRevert) · `off`. Switch: `/aftermath [lite|full|ultra|off]`.
- `/aftermath-status` — what changed since last-known-good · `/aftermath-revert` — undo the last change, nothing more · `/aftermath-audit` — scope-creep scan · `/aftermath-log` — one-line postmortem · `/aftermath-checkpoint status|clear|restore` — inspect, clear, or manually restore checkpoints · `/aftermath-init` — initialize the project with destructive-safe paths.
- Enforcement: OpenCode blocks destructive commands and forward edits at full/ultra; checkpoints restore at ultra when `autoRevert` is enabled. Other hosts inject the ladder and block destructive Bash. `aftermath init` writes the project's safe/protected paths so artifact deletes are allowed and source is not.

## Full behavior (read these, this file is only the entry point)

- `skills/aftermath/SKILL.md` — the canonical skill: persistence, enforcement, checkpoints, attempt ledger, output pattern, intensity table.
- Category playbooks: `skills/test-regression/SKILL.md` · `skills/retry-loop/SKILL.md` · `skills/destructive-action/SKILL.md` · `skills/build-failure/SKILL.md` · `skills/flaky-test/SKILL.md` · `skills/dependency-failure/SKILL.md` · `skills/merge-conflict/SKILL.md` — loaded when their signal fires.
- `hooks/` — lifecycle wiring (instruction builder, mode config, checkpoint store, signal detectors, destructive policy). `AFTERMATH.md` — the always-on ladder source.
