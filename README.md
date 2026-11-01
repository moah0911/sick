# Sick

[![PyPI](https://img.shields.io/pypi/v/sick-agent)](https://pypi.org/project/sick-agent/)
[![Python](https://img.shields.io/pypi/pyversions/sick-agent)](https://pypi.org/project/sick-agent/)
[![License](https://img.shields.io/github/license/moah0911/sick)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-162%20passing-brightgreen)](tests/)

**The coding agent that can't claim "done" without proof.**

Sick is a self-improving, object-oriented coding agent built on the
[NVIDIA OO Agents Framework](https://github.com/NVIDIA-NeMo/labs-OO-Agents).
It reads, writes, and edits code in your workspace — and unlike other
agents, its host process *enforces* the engineering process: a task is
only "delivered" when verification evidence exists after the last edit.
Everything it does leaves artifacts you can audit.

## Highlights

- **Evidence-gated delivery** — runtime SDLC lifecycle (requirements →
  design → implement → verify → deliver). Unverified work ends
  `BLOCKED`, never "success". Every run persists proof in
  `.sick/runs/<id>/` (`verification.json`, plan, summary).
- **It actually learns** — structured lessons
  (`trigger → root cause → fix`) that are promoted only when a fix
  verifies, and marked *ineffective* when a failure recurs.
- **It grows its own tools** — when a capability is missing, the agent
  writes a new tool, smoke-tests it in a subprocess, registers it live,
  and keeps it for future sessions (`.sick/tools/`, with provenance).
- **Skills from success** — `/distill` turns a delivered task into a
  reusable `SKILL.md` playbook, activated only after your approval.
- **Repo guardian** — `sick watch` re-verifies your repo on change and
  makes one bounded, checkpointed fix attempt when tests go red.
- **Real default plugins** — the actual Ponytail and Aftermath skills
  (vendored, pinned), including destructive-command blocking and
  post-failure edit freezes enforced in code.
- **Live, honest TUI** — streaming tool feed, visible model thinking,
  an SDLC phase tracker, and fail-fast provider errors with the real
  message — never a silent spinner.
- **Runs on your model** — Gemma 4, Muse Spark, Groq, Anthropic,
  OpenAI, and more, switchable live mid-session with `/connect`.

## Quick Start

```bash
# From PyPI (recommended)
uv tool install sick-agent
sick

# Or from source
git clone https://github.com/moah0911/sick.git sick && cd sick
./install.sh            # uv, deps, .env, `sick` command, preflight
# or: ./install.sh --global   (uv tool install — `sick` on PATH from anywhere)
# optional: ./install.sh --with-video  (remotion skills for /visual)

# No key yet? Just run `sick` — the first-run wizard asks for your
# provider + API key (hidden input) and saves it to .env for next time.
# Prefer env vars? export NVIDIA_API_KEY / OPENAI_API_KEY / ANTHROPIC_API_KEY.

# Interactive chat (TUI)
sick

# Windows: .\install.ps1 (or install.bat) — same flow; see WINDOWS.md
# for the compatibility matrix (WSL recommended for the bwrap sandbox)

# One-shot task
sick "generate a python script to download a github repo's issues"

# Health checks before starting work
sick --preflight
```

### Environment

All configuration lives in `.env` (see [`.env.example`](.env.example)):

| Variable | Purpose |
|----------|---------|
| `NVIDIA_API_KEY` / `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` / `GROQ_API_KEY` | Provider selection (set one) |
| `SICK_MODEL` | Model override |
| `SICK_BASE_URL` | Custom OpenAI-compatible endpoint (Groq's is built in) |
| `SICK_PROVIDER` | Force `nvidia`/`anthropic`/`openai`/`groq`/`meta` when multiple keys set |
| `MODEL_API_KEY` | Meta Model API key (Muse Spark) |
| `SICK_MEMORY_DIR` | Experience memory location (default `~/.sick`) |
| `SICK_REMOTION_DIR` | Remotion skill location (default `~/.agents/skills`) |
| `SICK_SANDBOX` | `1` to force bash sandboxing |
| `SICK_MAX_TOKENS` | Cap model output tokens per call (default 4096 on slow endpoints) |
| `SICK_TOOL_GENESIS` | `off` disables agent-created tools |

Change provider or key any time with `sick --setup` (hidden key entry, works
even when already configured) or switch live between saved providers in the
TUI with `/connect groq|meta|openai|nvidia|anthropic` — no restart, and stale
endpoints/models from the previous provider are cleared automatically.

> **Groq free tier warning:** Groq's free (`on_demand`) plan caps chat models
> at **8,000 tokens/minute**, but one Sick agent request is ~15k tokens
> (system context + tool documentation + conversation), so every turn is
> rejected with `Request too large … Limit 8000` — no coding agent fits in
> that budget. Groq's Dev Tier (pay-as-you-go, 250k TPM) works; Sick now
> fails fast with that exact message instead of retrying silently for
> minutes. Model reasoning is shown live in the TUI (`/thinking` toggles it).

## Runs on Gemma 4

Sick runs on **Gemma 4** (`google/gemma-4-31b-it`) as a full coding
agent — same tool use, evidence-gated delivery, self-learning, and live
TUI, unchanged:

```bash
SICK_PROVIDER=nvidia SICK_MODEL=google/gemma-4-31b-it sick
# or make it permanent for a workspace with one line in .env:
#   SICK_MODEL=google/gemma-4-31b-it   (after /connect nvidia)
```

Swap models any time mid-session with `/connect`, or per launch with
`sick --model <model-id>`. The header and `/models` always show the
model the running client is actually using.

Per-project settings go in `.sick/config.toml`:

```toml
model = "gpt-4o-mini"      # override the LLM model
excluded = ["vendor"]      # extra dirs to skip in search/research
```

### Sandbox (beta)

`sick --sandbox` runs every `bash` command inside a
[bubblewrap](https://github.com/containers/bubblewrap) sandbox: the workspace
is writable, the rest of the filesystem is read-only, and there is no
network. Falls back to normal bash with a warning if `bwrap` is not installed.

## TUI — complete

```
sick
```

- `@file` / `@"file with spaces"` — attach files (PDFs via Docling), deduped, `300k` total cap, `100k` per file
- `!cmd` — bash with sandbox, exit-code coloring, truncation notice, `ctrl+c` interrupt, `!` history `up/down`
- `/help` — all slash commands + bindings; fuzzy suggest for typos (`/hepl` → `/help`)
- `/clear` `new` — clear chat (audit kept); `/audit [n]` last N with args; `/stats` turns/tools; `/models` provider
- `/plan <task>` / `/approve` / `/reject` — plan workflow backed by a real SDLC run (DESIGN → IMPLEMENT), `/run` shows live phase/tier/gate, `pending_task` shown
- `/learn [focus]` — self-improvement: mines audit + memory for failures, records a lesson, then edits sick's own source (checkpoint first, tests after, `/restore` to roll back); also `sick --learn [focus]`
- `/undo` / `/redo` — back to the previous checkpoint (current state snapshotted first), `/compact` (`/summarize`), `/export [path]`, `/init`, `/sessions` (`/resume`, `/continue`), `/details`, `/thinking`, `/editor` ($EDITOR), `/connect`, `/themes [name]`, `/update`
- `/checkpoint [msg]` / `/restore [n]` / `/checkpoints` — git `sick-checkpoints` branch
- `/version` — version + live model; `/visual <topic>` remotion; `/tools` builtins + grown tools; `/sidebar` toggles the right panel; `/status` full session detail
- Layout: header (clock) · full-width chat with live tool feed + thinking · responsive right panel (SDLC phase tracker, plugins, skills; auto-hides under 120 cols, `/sidebar` toggles) · status bar (state, sdlc/gate, plugins) · input (border shows `message`, subtitle shows hints) · footer with everyday keys. Precision-dark `sick` theme (+ `sick-light`); `ctrl+t` cycles Sick's curated themes only
- Keymap (`ctrl+x` leader): `h` help, `n` new, `c` compact, `l` learn, `s` sessions, `u` undo, `r` redo, `e` editor, `x` export, `m` models, `t` themes, `d` details, `q` quit; direct: `ctrl+c` interrupt, `ctrl+l` clear, `f1` help, `esc` focus input, `pageup/pagedown/home/end` scroll, `up/down` history — all listed in `/help`
- Suggester: `/` commands + `@` files (workspace-aware, `EXCLUDED_DIRS` filtered)

### Custom commands

Add prompt files `.sick/commands/<name>.md` (workspace) or `~/.sick/commands/*.md` (global):

```markdown
---
description: review code with tests
---
Review $ARGUMENTS via code_research and grep, propose plan, run pytest, keep diff minimal.
```

- `$ARGUMENTS` / `{{args}}` / `$1` replaced with args, appears in `/help`, dispatch via `app._send`.
- Example: `.sick/commands/review.md`, `.sick/commands/commit.md` → `/review file.py`, `/commit "fix auth"`

## Attach PDFs

```bash
# Attach a PDF — Docling parses it into clean Markdown automatically
sick --attach spec.pdf "implement the login flow from section 3"

# Multiple attachments
sick --attach requirements.pdf --attach spec.pdf "build the project"
```

The agent can also parse PDFs mid-task:

```python
result = agent.parse_pdf("docs/report.pdf")
```

## Built-in Skills

| Skill | Description | Status |
|-------|-------------|--------|
| **ponytail** (always, real plugin) | The actual vendored Ponytail skill (github.com/DietrichGebert/ponytail, pinned — see `src/sick/bundled/BUNDLED.md`): lazy-senior-dev ladder, levels via `/ponytail [lite/full/ultra/off]`, plus `/ponytail-review`, `/ponytail-audit`, `/ponytail-debt` | Always active |
| **aftermath** (always, real plugin) | The actual vendored Aftermath recovery skill (github.com/moah0911/aftermath, pinned): failure ladder in context + enforcement in code — destructive commands blocked, forward edits frozen after unresolved failures at `full` (default), `/aftermath [lite/full/ultra/off]`, `/aftermath-status`, `/aftermath-revert`, `/aftermath-log` | Always active |
| **PDF handling** | Parse PDFs via Docling — clean Markdown, not raw binary | Always active |
| **Remotion** | Create explanatory videos: Remotion scaffold, markup, render | Always active |
| **SDLC & OO** | Runtime-enforced lifecycle (`sick.lifecycle`): phases observed from tool results, delivery blocked without post-edit verification evidence; OO via `ToolResult`/`ToolRegistry` deep modules | Always active |
| **Installed skills** | Every `SKILL.md` under `~/.agents/skills`, `~/.sick/skills`, `.sick/skills` is indexed (name + description) in context; full body loaded on demand via `load_skill(name)` | Auto-discovered |

## SDLC that is actually enforced

Most agents *prompt* the model to follow a process. Sick's host process
enforces one (`src/sick/lifecycle.py`, see `docs/adr/0001-evidence-gated-sdlc.md`):

- Every task is a **Run** with phases observed from real tool results:
  exploration → `design`, file mutation → `implement`, a passing
  test/lint command *after the last edit* → `verify`.
- **Delivery is gated in code, not in a prompt.** A standard run with
  edits but no post-edit verification evidence ends `BLOCKED`, and the
  experience is recorded as `blocked` — never `success`. Risky runs
  (self-modification, auth/migrations, >5 files) additionally require
  `/plan` → `/approve` and a checkpoint in the TUI (CLI invocation
  itself counts as approval). Trivial tasks fast-path.
- Every run leaves auditable artifacts in `.sick/runs/<id>/`:
  `requirements.md`, `design.md`, `plan.md`, `verification.json`,
  `summary.md`. `/run` shows the live phase, tier, and gate reasons.
- Changed Python files get AST design checks: duplicate top-level
  definitions block delivery; oversized classes and private-attribute
  access are recorded in `verification.json`.
- Phases route installed skills automatically (design →
  `codebase-design`, verify → `tdd`, ...); every tool returns one
  typed `ToolResult` through `ToolRegistry` — no output-string sniffing.

Proof, no LLM needed: `uv run python demos/sdlc_gate.py` — an unverified
edit is blocked, a verified edit delivers, artifacts are listed.

## Explainer videos

`/visual <topic>` makes an explanatory video about the topic with Remotion: the
agent scaffolds a project in the workspace, designs the composition, and
renders it with `npx remotion render`.

The Remotion skills (create + best practices) must be installed once:

```bash
npx skills add remotion-dev/skills@remotion-create -g -y
npx skills add remotion-dev/skills@remotion-best-practices -g -y
```

Sick loads both `SKILL.md` files into the agent context at startup; reference
guides under `~/.agents/skills/remotion-best-practices/` are read on demand
via `bash cat`.

## Tools

| Tool | Description |
|------|-------------|
| `read_file` | Read files with optional line range |
| `write_file` | Write content to files |
| `edit_file` | Search-and-replace edit |
| `bash` | Execute shell commands |
| `grep` | Regex search across files |
| `glob` | Find files by pattern |
| `parse_pdf` | Parse PDFs into clean Markdown via Docling |
| `code_research` | Search the codebase index (ast chunks + lexical scoring, mtime-cached in `.sick/indexes/`) |
| `self_read` / `self_write` | Read/write own source code |
| `fetch_url` | Fetch a web page (http/https, bounded to 100KB) |
| `checkpoint` / `restore` / `checkpoints` | Snapshot the workspace and undo changes (separate `sick-checkpoints` branch) |
| `load_skill` | Load an installed skill's full instructions on demand |
| `create_tool` / `use_tool` | Grow a new persistent tool (validated in a subprocess, registered live) and call grown tools |

Plus the guardian daemon: `sick watch` (verify on change, bounded
checkpointed fix attempts, never commits — see `sick watch --help`
behaviour in `src/sick/guardian.py`).

All file-backed tools operate inside the project where Sick was started. Paths
that escape it (including via symlinks) are rejected. `read_file`, `grep`, and
`code_research` skip hidden/generated files and bound file sizes so a large
artifact cannot consume the agent context. `edit_file` replaces only a unique
match; use `read_file` first when a file contains repeated text.

`bash` runs with the project as its working directory, with a 300-second
timeout ceiling and bounded output. It is a local power-user tool, not an OS
sandbox: shell commands can still access files permitted to the running user.

For PDF excerpts, use `parse_pdf.execute_pages(path, "1-5,8")`. Sick converts
each requested inclusive range to Markdown through Docling.

## Why Sick — pain points addressed

| AI-agent pain point | How Sick addresses it |
|---|---|
| "The agent broke my code and I can't undo it" | Auto-checkpoint on session start + `checkpoint`/`restore` tools (commits to a separate `sick-checkpoints` branch; master untouched) |
| Context blow-up from huge files | Bounded reads with truncation notice; grep/glob return path lists; vendor/hidden/binary skipped |
| Editing the wrong file / hallucinated paths | Workspace-rooted boundary incl. symlink escapes; deterministic relative results |
| Accidental broad/duplicated edits | `edit_file` replaces only a unique match; atomic writes; failures are explicit tool results |
| Agents charge ahead with the wrong approach | `/plan` → `/approve` → execute, or `/reject` |
| "What did it actually do to my repo?" | Full audit log of every tool call (`.sick/audit.jsonl`) + `/audit` |
| Uncontrolled shell / runaway commands | Validated timeouts, bounded output, workspace `cwd`; opt-in `--sandbox` via bwrap (read-only host, no network) |
| Agents can't read docs/websites mid-task | `fetch_url` tool (bounded, http/https only) |
| No memory across sessions | `ExperienceMemory` recall in every prompt |
| Setup friction / provider confusion | `./install.sh` + `.env.example` + auto-detection across 5 providers + live `/connect` switching |
| No verification loop | "Run tests after every change" baked in; `sick --preflight` health checks |
| Agents over-engineer or drift off-task | Always-on ponytail + runtime SDLC gate (`sick.lifecycle`) that blocks unverified delivery |
| Can't use PDFs/docs in context | Docling `parse_pdf` + auto-parsed `@file` attachments |
| Outputs are code-only | `/visual` — Remotion explainer videos as a deliverable |
| Not self-improving | `self_read`/`self_write` rooted at `src/sick/`, `--modify` flow with test verification |

## Memory & learning

Experiences are stored in `~/.sick/memory.jsonl`; structured lessons
(`trigger → root cause → fix → verified`) live in `~/.sick/lessons.json`
and are recalled into future prompts when relevant. Code-research
indexes are cached per project in `.sick/indexes/` (ignored by Git).
Run `/learn` after a rough session: Sick mines its audit log for what
actually failed, records a structured lesson, and — with your review —
turns verified fixes and successful runs into lasting capability
(edits, lessons, distilled skills).

## Project Structure

```
src/sick/
├── agent.py          # SickAgent — composes tools + skills + memory + plugins
├── lifecycle.py      # Evidence-gated SDLC: phases, risk tiers, delivery gates, run artifacts
├── design_check.py   # AST OO/design checks over changed files
├── guard.py          # Aftermath guard: destructive blocks + edit freeze at the registry seam
├── guardian.py       # Repo guardian daemon core (sick watch)
├── learn.py          # Structured lessons: candidate → verified → ineffective on recurrence
├── plugins.py        # Bundled default plugins loader (ponytail + aftermath, vendored pinned)
├── bundled/          # Vendored plugin content + BUNDLED.md manifest (source + commit pins)
├── audit.py          # JSONL audit log of every tool call
├── cli.py            # CLI entry point (run, modify, learn, watch, preflight, sandbox)
├── config.py         # .sick/config.toml loader
├── preflight.py      # health checks (import, git, pytest)
├── skills.py         # SKILL.md discovery, relevance ranking, on-demand loading
├── providers.py      # LLM providers (NVIDIA, Anthropic, OpenAI, Groq, Meta)
├── memory.py         # Experience memory (JSONL log)
├── tools/
│   ├── base.py       # Tool ABC + ToolResult + workspace boundary
│   ├── registry.py   # ToolRegistry — dispatch/audit/counts/lifecycle/activity seam
│   ├── files.py      # ReadFile, WriteFile, EditFile
│   ├── exec.py       # Bash (optionally bwrap-sandboxed)
│   ├── search.py     # Grep, Glob
│   ├── pdf.py        # ParsePdf (Docling)
│   ├── git.py        # Checkpoint, Restore, ListCheckpoints
│   ├── web.py        # FetchUrl
│   ├── skill.py      # LoadSkill (audited skill loading)
│   ├── genesis.py    # create_tool: agent-grown persistent tools
│   └── self.py       # SelfRead, SelfWrite ($SICK_ROOT-aware)
└── tui/
    ├── app.py        # SickApp — Textual application (live feed, SDLC tracker)
    ├── chat.py       # ChatView — structured message renderables
    ├── inputbar.py   # SickInput + @file suggester
    ├── commands.py   # Slash commands (incl. bundled /commit)
    └── host.py       # TurnHost — agent turn loop
```

## Built with

Python 3.12 · [NVIDIA OO Agents (NOOA)](https://github.com/NVIDIA-NeMo/labs-OO-Agents)
· LiteLLM · Textual · Pydantic · Docling (PDF) · Remotion (explainer
videos) · pytest · bubblewrap (optional sandbox). Models: bring your
own key — NVIDIA, Anthropic, OpenAI, Groq, Meta (Muse Spark), and
Gemma 4 are all supported through one provider layer.

## Demos (real, no mocks)

```bash
uv run python demos/pdf_to_feature.py   # PDF spec → auth → checkpoint/restore
uv run python demos/refactor_legacy.py  # grep + edit_file rename across files
uv run python demos/web_research.py     # fetch_url SSRF + truncation
uv run python demos/visual_demo.py      # /visual slash + real filesystem scaffold
uv run python demos/hello.py            # fibonacci + verify
uv run python demos/sdlc_gate.py        # SDLC gate: unverified edit blocked, verified delivered (no LLM)
uv run python scripts/eval_suite.py     # graded live evals: hello/pomodoro/crud/refactor, pass + time + tool counts
uv run python demos/self_evolve.py      # modify_self ping demo
```

## Experiments

See `experiments/` for research on self-modification and internet-augmented coding.

## Development

```bash
uv sync --group dev
uv run ruff check src tests
uv run mypy src
uv run pytest -q --cov
sick --preflight
docker build -t sick:local .
```
See `CONTRIBUTING.md`, `ARCHITECTURE.md`, `CHANGELOG.md`.
