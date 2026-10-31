# Architecture — Sick

```
CLI (cli.py) ──detect provider──► SickAgent (agent.py)
                                       │ InteractiveAgent (nooa)
                                       ├─ ToolRegistry (tools/registry.py) ──► ToolResult (tools/base.py)
                                       │     Read/Write/Edit/Bash/Grep/Glob/ParsePdf/CodeResearch/Self*/FetchUrl/Checkpoint…
                                       ├─ Lifecycle (lifecycle.py) — SDLC runs, gates, artifacts .sick/runs/<id>/
                                       ├─ DesignCheck (design_check.py) — AST checks over changed files
                                       ├─ Skills → context blocks (ponytail/pdf/remotion/sdlc pointer) + phase-routed SKILL.md
                                       ├─ memory (global ~/.sick/memory.jsonl)
                                       ├─ audit (per-workspace .sick/audit.jsonl)
                                       └─ handle() @hidden ← TurnHost (tui/host.py) queue_manager.race()

TUI: SickApp (tui/app.py) compose Header+ChatView+SickInput → TurnHost dispatcher
     _expand_attachments @file → read_file/pdf (workspace-checked) → host.submit → agent.handle → respond() (LLM CodeAct)
     !cmd → agent.bash (thread) + hidden _send ; /cmd → SlashCommandRegistry (tui/commands.py)
```

## Key flows
- **SDLC gate** `lifecycle.py` — every turn/one-shot starts a Run; phases are observed from ToolResults (exploration→DESIGN, mutation→IMPLEMENT, passing verify command after last mutation→VERIFY). `finish()` runs DesignCheck + `can_deliver()`: STANDARD needs post-edit verification evidence, RISKY also needs approval + checkpoint (CLI invocation = approval; TUI needs `/plan`→`/approve`), TRIVIAL fast-paths. Blocked runs record experience as `blocked`, never `success`. Artifacts: `.sick/runs/<id>/{requirements,design,plan,verification,summary}`. See `docs/adr/0001-evidence-gated-sdlc.md`, `GLOSSARY.md`.
- **ToolResult** `tools/base.py` — every `Tool.execute()` returns `ToolResult{ok, output, error}`; `ToolRegistry.call()` (tools/registry.py) is the single seam for timing, audit, counts, lifecycle recording, and legacy-return wrapping. Agent proxies render `.output` for the LLM.
- **Checkpoint** `tools/git.py` — `sick-checkpoints` branch, `add -A; commit; rev-parse HEAD; checkout -`, `restore` uses `git restore || git checkout + clean -fd`.
- **CodeResearch** `tools/research.py` — ast chunks (.py) + 100-line bands, lexical 4/2/1 scoring, optional embeddings, mtime cache `.sick/indexes/code-index.json`.
- **Confinement** — every `WorkspaceTool` gates via `resolve_path` (`relative_to`); TUI re-checks `@` paths.
- **FetchUrl** `tools/web.py` — urllib, 100KB/10s bound, SSRF denylist (private nets, metadata host).
- **Preflight** `preflight.py` — checks import/git/pytest/bwrap/docling/npx.

## Decisions
- Evidence-gated, risk-tiered SDLC in the host process instead of prompt instructions (ADR 0001).
- Lexical index not embeddings by default (upgrade via litellm behind same API).
- Audit redacts API keys; memory tolerates corrupt JSONL.
