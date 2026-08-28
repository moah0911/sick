# Contributing to Sick

## Dev setup
```bash
./install.sh
uv sync --group dev
uv run pytest -q --cov
uv run ruff check src tests
uv run sick --preflight
```

## Project structure
- `src/sick/agent.py` — `SickAgent(InteractiveAgent)` composition root, tools registry, skills
- `src/sick/tools/` — bounded, workspace-confined tools (`base.py` is security boundary)
- `src/sick/tui/` — Textual app (`app.py`+`host.py` dispatch `queue_manager.race()`)
- `experiments/001-self-modify/README.md` — keep updated with quantitative results

## Conventions
- `ponytail` always active: stdlib > deps, shortest correct diff, `ponytail:` comment on shortcuts.
- All file tools must `resolve_path` and respect `excluded`; add tests in `tests/test_security.py`.
- No `pip`, only `uv`. No secrets in `audit.jsonl` (redaction in `audit.py`).
- `uv run pytest -q` must pass before push; CI runs `ruff`, `mypy`, `pytest --cov`.

## Adding a tool
1. Subclass `WorkspaceTool` or `Tool` in `src/sick/tools/`, add `name/descript/execute`.
2. Register in `SickAgent.__init__` `agent.py:149` and wire `excluded` merge.
3. Add unit test + security test, update `README.md` tools table.
