# Audit — Sick (2026-10-31)

Multi-axis review (correctness, security, performance, maintainability) of the
full source tree, tests, packaging, and installer. Baseline before fixes:
67 tests passing, coverage 50.33% (gate: 50%), `ruff` 1 error, `mypy` 55 errors
(CI tolerates with `|| true`). After fixes: **81 tests passing, coverage
56.4%, `ruff` clean, no new `mypy` errors.**

## Critical bugs (fixed)

1. **Checkpoint could commit onto the user's working branch.**
   [git.py](/home/mahtwog/sick/src/sick/tools/git.py) `Checkpoint.execute`
   ignored the return codes of `git checkout sick-checkpoints` and the switch
   back. When the checkout was refused (dirty tree conflicting with the
   diverged checkpoint branch — the normal state of this very repo), the
   following `git add -A; git commit` ran on the user's current branch,
   breaking the tool's core promise ("master untouched"). Observed live during
   this audit: uncommitted edits were swept into `[sick] session start`
   commits on `main` by test runs. Fix: create the branch ref without
   switching, check every step, verify HEAD is on the checkpoint branch
   before committing, abort with `[error: ...]` otherwise. Regression test:
   `test_git_checkpoint_never_commits_to_working_branch`.

2. **Empty env vars resolved to `Path(".")`, disabling skills and leaking
   memory into the cwd.** `SICK_MEMORY_DIR=` / `SICK_REMOTION_DIR=` (the
   shipped `.env.example` defaults) made
   [memory.py](/home/mahtwog/sick/src/sick/memory.py) write `memory.jsonl`
   into whatever directory `sick` was started in (the copy tracked at the
   repo root was exactly this leak; now untracked + gitignored), and made
   [agent.py](/home/mahtwog/sick/src/sick/agent.py) look for Remotion
   `SKILL.md` files relative to the cwd, so the Remotion skill *always*
   fell back to the "files are missing" prompt even when installed. Fix:
   treat empty as unset at both read sites; regression tests in
   [test_skills.py](/home/mahtwog/sick/tests/test_skills.py).

3. **Wheel build was broken.** The global hatch `force-include` rewrote
   `templates` inside the sdist, so `uv build` (and the tag-publish CI)
   failed with `Forced include not found: .../sick-0.1.0/templates`. Fix:
   scope `force-include` to the wheel target in
   [pyproject.toml](/home/mahtwog/sick/pyproject.toml). Verified: sdist +
   wheel build, wheel contains `sick/templates/*` and `sick/skills.py`.

## Dead code (removed)

| Location | What | Why dead |
|---|---|---|
| `agent.py` | `REMOTION_PROMPT = ""` | never read; loader is lazy via `_get_remotion_prompt()` |
| `config.py` | `_max_bytes()` | never called; duplicated in 3 tool modules |
| `config.py` | `SickConfig` fields `workspace`, `provider`, `embedding_model`, `embedding_provider`, `hybrid_alpha` | no reader anywhere (embeddings read env vars directly) |
| `research.py` | `CodeIndex.status()` | no callers in src/tests/demos |
| `research.py` | `MAX_FILE_BYTES` + `_get_max_bytes()` copies in `search.py`/`files.py` | consolidated into one `max_read_bytes()` in [base.py](/home/mahtwog/sick/src/sick/tools/base.py) |
| repo root | `memory.jsonl` (tracked) | runtime data leaked by bug 2; untracked + gitignored |

Made live instead of deleting: `SickConfig` gained `command` and `tracing`
fields — [cli.py](/home/mahtwog/sick/src/sick/cli.py) already read
`cfg.get("tracing")` and [commands.py](/home/mahtwog/sick/src/sick/tui/commands.py)
already read `cfg.get("command")`, both always `None` before (config-file
custom commands and the tracing toggle silently never worked).

## Skills — now all of them are used

Only the two Remotion skills were ever loaded from disk (and, per bug 2,
never successfully). New [skills.py](/home/mahtwog/sick/src/sick/skills.py)
discovers **every** `SKILL.md` under `~/.agents/skills`, `~/.sick/skills`,
and workspace `.sick/skills` (67 found on the audit machine), indexes
name + description into the agent context, and loads full bodies on demand
via the new `load_skill(name)` agent method — so all installed skills are
usable without blowing up the context window.

## Other fixes

- [preflight.py](/home/mahtwog/sick/src/sick/preflight.py): import check no
  longer shells out to `uv run` + instantiates `SickAgent` (slow index build;
  false `FAILED` when the uv cache is read-only/offline — preflight failed
  inside this repo for that reason). Now `sys.executable` import-only;
  pytest summary picks the real summary line instead of tracing noise;
  portalocker check actually imports portalocker (the old `try` could never
  fail).
- [audit.py](/home/mahtwog/sick/src/sick/audit.py): arg values truncated at
  1000 chars — full `write_file` contents no longer land in `audit.jsonl`.
- [commands.py](/home/mahtwog/sick/src/sick/tui/commands.py): `_expand_template`
  read attached files twice; now once.
- [app.py](/home/mahtwog/sick/src/sick/tui/app.py): `@file.pdf` outside the
  workspace embedded the tool's error string as if it were the document;
  now reported as `[unreadable: ...]`.
- `providers.py`: ruff import-sort (the 1 baseline lint error).
- [bin/sick](/home/mahtwog/sick/bin/sick): prefers the checkout venv binary
  (fast, offline) over `uv run` on every invocation.
- [install.sh](/home/mahtwog/sick/install.sh): added `--global`
  (`uv tool install`), `--uninstall`, `--help`; skips `uv python install`
  when a Python already resolves; `GIT_LFS_SKIP_SMUDGE=1` so the `nooa` git
  dependency clones without git-lfs. Verified end-to-end with a scratch
  `$HOME` (sync → shim → preflight `ok` → `sick --version` from another
  directory → uninstall → reinstall). `--global` was verified up to
  dependency resolution; the final PyPI download is blocked by this
  sandbox's proxy, so a full global install still needs one run on an
  unrestricted network.

## Known limitations (not fixed, by design or out of scope)

- `FetchUrl` SSRF guard matches literal hosts/IPs only; DNS resolution to
  private addresses (rebinding) is not checked.
- `Restore` runs `git clean -fd` (deletes untracked files) after a
  successful restore — documented behavior, keep backups via checkpoints.
- `mypy` still reports the 55 pre-existing errors (mostly `Tool.execute`
  signature-vs-ABC noise and missing `nooa` stubs); CI already tolerates
  them. New/edited files (`skills.py`, `config.py`, `tools/base.py`) are
  clean and the total did not grow.
- `cli.py` shows 0% *in-process* coverage because CLI tests exercise it via
  subprocess (`--help`/`--version`/`--list-templates`); it is covered
  end-to-end, just not attributed by coverage.py.
