---
name: destructive-action
description: >
  Use when the next action is irreversible: force push, reset --hard, clean,
  drop, delete, rm, overwrite, schema migration, or permission change. Confirm
  current state explicitly and never proceed on assumption. Also covers scope
  creep and the forward-edit freeze that follows an unresolved failure.
license: MIT
---

# Destructive Action

Irreversible means unrecoverable. Slow down to the speed of verification.

## Before any destructive command

1. Stop. Name the command and what it destroys, in plain terms.
2. Confirm current state explicitly: `git status --short`, `git diff --stat`, remote/branch/database target. No proceeding on assumption.
3. Check cheapness: uncommitted / one file / cheap to undo? If not cheap, require explicit user confirmation with the target named back.
4. At `full`, ask before running. At `ultra`, still ask — ultra auto-reverts cheap damage only, never auto-destroys.
5. After running, report what changed and how to verify it.

## High-risk catalog and safer alternatives

| Risk | Examples | Safer first move |
|------|----------|------------------|
| History rewrite | `git push --force`, `git reset --hard` | New commit; `git revert`; back up the branch |
| Worktree wipe | `git clean -fd`, `git checkout -- .`, `git restore .` | `git clean -n`, `git stash -u`, revert specific files |
| Data loss | `DROP TABLE`, `DELETE FROM`, `TRUNCATE`, `dropdb` | Dump first; run in a transaction; target a copy |
| Filesystem | `rm -rf`, `shred`, `dd of=`, `mkfs`, `find -delete`, `xargs rm` | Name the absolute path; `ls` it first; move to trash |
| Infrastructure | `terraform apply/destroy`, `kubectl delete`, `helm uninstall`, `docker system prune` | `terraform plan`, `--dry-run=client`, inspect the target |
| Migrations | `prisma migrate reset` | `migrate status`, back up, apply forward |
| Permissions | `chmod -R 777` | Narrow the mode and the path |

## Enforcement and allowlist

- OpenCode blocks matching commands at `full`/`ultra`; `lite` only flags them.
- Claude Code / Codex block them through `PreToolUse` (exit 2) with the same policy.
- Run `aftermath init` / `/aftermath-init` to record the project's `safePaths` (disposable artifacts) and `protectedPaths` (source, VCS, secrets, manifests). Deletes under safe paths are allowed; protected, unknown, dynamic, and outside-project targets stay blocked.
- Intentional exceptions: `{"destructiveAllowlist": ["rm -rf ./dist"]}` in the global or project config. Entries are command substrings; keep them narrow.
- A blocked command is a stop sign, not a puzzle. Confirm state or ask the user; do not rephrase to slip past the matcher.

## Forward-edit freeze

After a test regression or an escalated repeat error, OpenCode and Claude Code / Codex block `edit`/`write` at `full`/`ultra` until a test passes, `/aftermath-revert` runs, or the level drops. Reverting through Bash is allowed. Do not bypass the freeze by editing through another tool or path.

## Scope-creep check (same skill, same caution)

1. `git diff --name-only` against task start. List every file outside the stated scope.
2. Revert or justify each one out loud. "While I was here" is not a justification.
3. Fix only the breaking diff. Move everything else to the audit (`/aftermath-audit`), not into this fix.

Never force-push, drop, or `rm -rf` on a guessed path. A destructive command with an unverified target is rung 5 (guessing) plus rung 4 (irreversible) — stop on both.
