# Architecture — Sick

```
CLI (cli.py:15) ──detect provider──► SickAgent (agent.py:108)
                                         │ InteractiveAgent (nooa)
                                         ├─ tools dict (14) ──► WorkspaceTool (base.py:17) resolve_path + is_ignored
                                         │     Read/Write/Edit/Bash/Grep/Glob/ParsePdf/CodeResearch/Self*/FetchUrl/Checkpoint…
                                         ├─ Skills → context blocks (ponytail/pdf/remotion/sdlc)  agent.py:80
                                         ├─ memory (global ~/.sick/memory.jsonl)  memory.py:25
                                         ├─ audit (per-workspace .sick/audit.jsonl) audit.py:6
                                         └─ handle() @hidden (agent.py:260) ← TurnHost (tui/host.py:47) queue_manager.race()

TUI: SickApp (tui/app.py:20) compose Header+ChatView+SickInput → TurnHost dispatcher
     _expand_attachments @file → read_file/pdf (workspace-checked) → host.submit → agent.handle → respond() (LLM CodeAct)
     !cmd → agent.bash (thread) + hidden _send ; /cmd → SlashCommandRegistry (tui/commands.py:160)
```

## Key flows
- **Checkpoint** `tools/git.py:27` — `sick-checkpoints` branch, `add -A; commit; rev-parse HEAD; checkout -` , `restore` uses `git restore || git checkout + clean -fd`.
- **CodeResearch** `tools/research.py:59` — ast chunks (.py) + 100-line bands, lexical 4/2/1 scoring, mtime cache `.sick/indexes/code-index.json`.
- **Confinement** — every `WorkspaceTool` gates via `resolve_path` (`relative_to`); TUI `app.py:116` re-checks `@` paths.
- **FetchUrl** `tools/web.py:11` — urllib, 100KB/10s bound, SSRF denylist (private nets, metadata host).
- **Preflight** `preflight.py:10` — tuple[str,bool], checks import/git/pytest/bwrap/docling/npx.

## Decisions
- Ponytail: lexical index not embeddings (upgrade via litellm behind same API).
- Audit redacts API keys; memory tolerates corrupt JSONL.
