# Changelog
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
