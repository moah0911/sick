---
name: merge-conflict
description: >
  Use when a merge, rebase, or cherry-pick stops on conflicts. Read both sides,
  never blindly take ours or theirs, never reset/abort to escape, and run the
  affected tests after resolving.
license: MIT
---

# Merge Conflict

A conflict is two intents colliding. Resolving it means understanding both, not picking a side quickly.

## Steps

1. Stop. Run `git status --short` and list every unmerged path.
2. Read the conflict markers in each file: `<<<<<<<` (current side), `=======`, `>>>>>>>` (incoming side). Read the surrounding code, not just the marked lines.
3. State the two intents in one line each. If you cannot, you are not ready to resolve.
4. Resolve the smallest region that satisfies both intents. Keep unrelated formatting out of the resolution.
5. Remove every conflict marker. Search the tree for `<<<<<<<`, `=======`, `>>>>>>>`.
6. Run the affected tests, then the broader suite. A clean `git status` is not proof of correctness.
7. Stage only the resolved files. Never `git add -A` during a conflict.

## Never

- Never blindly take `--ours` or `--theirs` for a whole file.
- Never `git reset --hard`, `git merge --abort`, or `git rebase --abort` just to escape; those discard state. Confirm with the user if abandoning is truly intended.
- Never commit with conflict markers or with a half-run test suite.
- Never mix the conflict resolution with unrelated edits.

## Checkpoints

Checkpoint auto-revert covers test green→red edits, not merges. Resolve conflicts deliberately; do not expect a restore to rescue a bad resolution.
