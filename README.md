# Sick

**Self-improving coding agent** built on the [NVIDIA OO Agents Framework](https://github.com/NVIDIA-NeMo/labs-OO-Agents).

Sick is an object-oriented coding agent that reads, writes, and edits code — and modifies its own source to improve over time.

## Quick Start

```bash
# Set your API key
export NVIDIA_API_KEY="nvapi-..."
# or: export OPENAI_API_KEY="sk-..."
# or: export ANTHROPIC_API_KEY="sk-ant-..."

# Interactive chat (TUI)
uv run sick

# One-shot task
uv run sick "generate a python script to download a github repo's issues"
```

## TUI

```
uv run sick
```

- `@file` — attach a file (PDFs parsed into Markdown via Docling)
- `!cmd` — run a shell command; the output is shown and fed to the agent
- `/visual <topic>` — make an explanatory video with Remotion
- `/help`, `/clear`, `/models`, `/exit`
- `ctrl+x h/c/q` — help / clear / quit

## Attach PDFs

```bash
# Attach a PDF — Docling parses it into clean Markdown automatically
uv run sick --attach spec.pdf "implement the login flow from section 3"

# Multiple attachments
uv run sick --attach requirements.pdf --attach spec.pdf "build the project"
```

The agent can also parse PDFs mid-task:

```python
result = agent.parse_pdf("docs/report.pdf")
```

## Built-in Skills

| Skill | Description | Status |
|-------|-------------|--------|
| **ponytail** (always) | Lazy-first philosophy: shortest correct solution, no over-engineering | Always active |
| **PDF handling** | Parse PDFs via Docling — clean Markdown, not raw binary | Always active |
| **Remotion** | Create explanatory videos: Remotion scaffold, markup, render | Always active |
| **SDLC & OO** | Lightweight SDLC phases (requirements → design → implement → verify), OO where it earns its keep | Always active |

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

## Memory

Experiences are stored in `~/.sick/memory.jsonl`. The agent recalls past patterns on similar tasks. Code-research indexes are cached per project in `.sick/indexes/` (ignored by Git).

## Project Structure

```
src/sick/
├── agent.py          # SickAgent — composes tools + skills + memory
├── cli.py            # CLI entry point
├── providers.py      # LLM providers (NVIDIA, OpenAI, Anthropic)
├── memory.py         # Experience memory (JSONL log)
├── tools/
│   ├── base.py       # Tool ABC
│   ├── files.py      # ReadFile, WriteFile, EditFile
│   ├── exec.py       # Bash
│   ├── search.py     # Grep, Glob
│   ├── pdf.py        # ParsePdf (Docling)
│   └── self.py       # SelfRead, SelfWrite
└── tui/
    ├── app.py        # SickApp — Textual application
    ├── chat.py       # ChatView — chat history
    ├── inputbar.py   # SickInput + @file suggester
    ├── commands.py   # Slash commands
    └── host.py       # TurnHost — agent turn loop
```

## Experiments

See `experiments/` for research on self-modification and internet-augmented coding.
