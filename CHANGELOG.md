# Changelog
## 0.2.5
- Fix blank "thinking…" screen on Groq: root cause was Groq free-tier 8k TPM vs Sick's ~24k-token agent request, retried silently 7× with minute-long backoffs. Sick context diet cut the request to ~14.6k (skills index capped at 6k chars in `skills.py`, Remotion context is now an on-demand pointer in `agent.py`), Groq clients fail fast (max 2 attempts, `providers.py`), and CLI turns surface the real provider error + an actionable hint instead of a traceback or silent hang `cli.py`
- Show model thinking live: TUI subscribes to NOOA `LLMComplete` events and renders `reasoning_content` dimmed via `ChatView.add_thinking`; `/thinking` now actually controls it and defaults to visible (previously a placebo toggle) `tui/app.py`, `tui/chat.py`
- Note: Groq free tier (8k TPM) still cannot fit any ~15k-token agent request — Dev Tier (250k TPM) or another provider is required; README documents this

## 0.2.4
- Fix Groq `model_not_found` turns: Groq shut down `llama-3.3-70b-versatile` for free/developer tiers on 2026-08-16. Default Groq model is now `openai/gpt-oss-120b` (Groq's recommended replacement, 131k context, tool calling), and saved configs naming retired Groq models (`llama-3.3-70b-versatile`, `llama-3.1-70b-versatile`, `llama-3.1-8b-instant`, tool-use preview) migrate to supported replacements automatically in `Groq.__init__` `providers.py`

## 0.2.3
- Add missing `mcp` dependency: litellm >=1.106 imports its MCP handler whenever a request carries tools (NOOA CodeAct always does), so fresh `uv tool` installs crashed with `No module named 'mcp'` for any provider. The dev venv's older litellm (1.96.2) masked this in 0.2.2 — the published-wheel isolated smoke test caught it. Includes the 0.2.2 Groq routing fix below.

## 0.2.2
- Fix Groq turns failing in the installed tool (`GroqException - No module named 'mcp'`, then `property 'prompt_cache_key' is unsupported`): route Groq via litellm's native `groq/<model>` provider instead of the bare-name OpenAI-compatible path, and pass `additional_drop_params=["prompt_cache_key"]` so NOOA's per-call OpenAI prompt-cache shard key never reaches Groq's API `providers.py`. Verified through the real NOOA client with tools in an env without `mcp`: request now reaches Groq auth instead of import/param errors
- Tests: +2 (real Groq client config, transform-level param stripping)

## 0.2.1
- Fix "cannot change API key after first setup": new `sick --setup` re-runs the provider wizard any time; `/connect <provider>` switches live between saved providers (hot-swapped LLM, no restart); provider saves/switches clear stale `SICK_BASE_URL`/`SICK_MODEL` so the old endpoint/model cannot leak across a switch `providers.py`, `cli.py`, `agent.py`, `tui/commands.py`
- Add Groq as a first-class provider (`GROQ_API_KEY`, `SICK_PROVIDER=groq`, built-in `https://api.groq.com/openai/v1` + `llama-3.3-70b-versatile`); legacy OpenAI-key + Groq base-URL configs still detect as Groq
- Tests: +6 (Groq detect/client/save/wizard, /connect hot-swap, stale-model clearing)

## Unreleased
- Real SDLC: `sick.lifecycle` evidence-gated runs (phases observed from tool results, risk-tiered delivery gates, `.sick/runs/<id>/` artifacts, `/run` command, `/plan`→`/approve` backed by run state); `handle()` no longer records unconditional success — unverified edits record `blocked` `lifecycle.py`, `agent.py`, `tui/commands.py`, `cli.py` (exit 3 when blocked)
- Real OO seam: every tool returns typed `ToolResult`, dispatched via `ToolRegistry` (audit/counts/lifecycle in one place); removed `isinstance` output-sniffing in `agent._call`, fixed private leaks (`registry.set_sandboxed()`, `registry.counts()`), removed duplicate `_register_discovered_skills` `tools/base.py`, `tools/registry.py`, all `tools/*.py`
- AST design checks on changed files (duplicate definitions block, size/private-access recorded), skill-routed phases via existing discovery, `/learn` mines blocked runs `design_check.py`, `learn.py`
- Tests: +12 (lifecycle gates, registry, agent handle gating, plan lifecycle, blocked-run lessons); demo `demos/sdlc_gate.py` (no LLM); `GLOSSARY.md`, `docs/adr/0001-evidence-gated-sdlc.md`
- Add `/learn [focus]` self-improvement (audit/memory mining → lesson → verified self-edit, rollback via checkpoint) + `sick --learn`; memory writes are now best-effort `learn.py`, `agent.py`, `tui/commands.py`, `cli.py`, `memory.py`
- Add OpenCode-basic TUI commands: `/undo`, `/redo`, `/compact` (`/summarize`), `/export`, `/init`, `/sessions` (`/resume`/`/continue`), `/details`, `/thinking`, `/editor`, `/connect`, `/themes`, `/update` + `ctrl+x u/r/s` bindings and a conversation transcript for export `tui/commands.py`, `tui/app.py`
- Tests: +13 (learn core, new-command dispatch, undo/redo roundtrip, editor)
- First run without a key now opens a setup wizard (provider → hidden key entry → saved to `.env`, mode 600) instead of an edit-this-file error; non-interactive runs still exit 2 with a hint `providers.py:prompt_for_api_key`, `cli.py`
- TUI redesign: custom `sick` theme, status sidebar + status bar (live turns/tools/view state, auto-hide <90 cols), restyled chat roles/input, grouped `/help` with full keymap, OpenCode-style `ctrl+x` leader keymap (`n` new, `c` compact, `l` learn, `s` sessions, `u` undo…) + `ctrl+t` theme cycling `tui/app.py`, `tui/chat.py`, `tui/inputbar.py`, `tui/commands.py`
- Windows support: `install.ps1` + `install.bat` + `bin/sick.cmd` (uv sync/tool, `sick` on PATH, preflight), drive-safe LSP file URIs, Windows-safe `$EDITOR` parsing, `windows-smoke` CI job, compatibility matrix in `WINDOWS.md` (bwrap sandbox stays Linux-only; WSL for 100%)
- Fix `ctrl+x` leader keymap: Textual binding commas mean alternative keys, not chords, so leader keys typed into the input instead of dispatching — now a real leader handler (`handle_leader_key`) with regression test; `install.ps1` now fails loudly when `uv` fails instead of reporting success
- Fix `Checkpoint` committing onto the working branch when the branch switch fails (checks every git step, verifies HEAD before committing) `tools/git.py`
- Fix empty `SICK_MEMORY_DIR=`/`SICK_REMOTION_DIR=` resolving to `Path(".")` — memory leaked into the cwd and Remotion skills never loaded `memory.py`, `agent.py`
- Fix broken wheel build: scope hatch `force-include` to the wheel target `pyproject.toml`
- Add skill discovery: every installed `SKILL.md` indexed in context, `load_skill(name)` loads bodies on demand `skills.py`, `agent.py`
- Dead code removed: `REMOTION_PROMPT`, `config._max_bytes`, `CodeIndex.status`, unused `SickConfig` fields; byte-limit helpers consolidated into `tools/base.py:max_read_bytes`
- `SickConfig` gains `command` + `tracing` so config-file custom commands and the tracing toggle actually work `config.py`
- `preflight` import check uses the current interpreter (no `uv run`, no agent instantiation); real portalocker probe; cleaner pytest summary `preflight.py`
- Audit arg values truncated at 1000 chars `audit.py`; TUI `@file.pdf` outside workspace and double-read in template expansion fixed `tui/`
- `install.sh`: `--global` (uv tool), `--uninstall`, offline-safe re-runs, LFS-skip for the `nooa` git dep; `bin/sick` prefers the venv binary
- Tests: 67 → 81, coverage 50.3% → 56.4%; see `AUDIT.md`

## 0.1.0 — 2026-08-28
- Fix `_call` ok-heuristic for bool/list/str (audit correctness) `agent.py:190`
- Fix `excluded` union (preserve node_modules/.venv/.git) + thread to CodeIndex `agent.py:156`, `tools/research.py:59`, `tools/base.py:6`
- CLI `--attach` now supports non-PDF via bounded read `agent.py:177`
- `_record_experience` now captures tool counts `agent.py:254`
- `preflight` returns `tuple[str,bool]`, adds bwrap/docling/npx probes `preflight.py:10`
- `git` checkpoint uses `rev-parse HEAD` short hash, restore cleans untracked `tools/git.py:27`
- `FetchUrl` SSRF denylist + content-type guard `tools/web.py:11`
- `Grep` uses fnmatch + 200-result cap `tools/search.py:14`, `base.py` expanded EXCLUDED_DIRS
- `Bash` sandbox binds /usr/local,/opt,~/.cargo,/tmp `tools/exec.py:13`
- TUI `@` confinement (`resolve_path` re-check) + trailing punct strip + truncation notice `tui/app.py:116`
- `FileSuggester` nested path completion `tui/inputbar.py:10`
- `Memory/Audit` corrupt-line tolerance + audit redaction `memory.py:30`, `audit.py:18`
- `Providers` dotenv `override=False`, SICK_PROVIDER + prefix inference, timeouts `providers.py:7`
- Packaging: pyproject `>=3.11`, ruff/mypy/pytest config, wheel, Dockerfile, CI workflow `pyproject.toml`, `.github/workflows/ci.yml`
- Tests: `test_providers.py`, `test_security.py`, `test_cli.py`, fix mktemp `tests/test_tools.py:177`
- Demos: `pdf_to_feature.py`, `refactor_legacy.py`, `web_research.py`, `visual_demo.py`; fix `self_evolve.py`
- Docs: `CONTRIBUTING.md`, `ARCHITECTURE.md`, `CHANGELOG.md`
