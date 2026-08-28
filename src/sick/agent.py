import os
import time
from pathlib import Path
from typing import Any

from nooa import Skill, hidden, spec
from nooa.interactive import InteractiveAgent, RespondReason, RespondResult

from sick.audit import AuditLog
from sick.config import load_config
from sick.memory import Experience, ExperienceMemory
from sick.tools.base import Tool
from sick.tools.exec import Bash
from sick.tools.files import EditFile, ReadFile, WriteFile
from sick.tools.git import Checkpoint, ListCheckpoints, Restore
from sick.tools.pdf import ParsePdf
from sick.tools.research import CodeResearch
from sick.tools.search import Glob, Grep
from sick.tools.self import SelfRead, SelfWrite
from sick.tools.web import FetchUrl

PONYTAIL_PROMPT = """## ponytail (always active)
- Shortest correct solution. No over-engineering.
- Stdlib before dependencies. Native features before libraries.
- Deletion over addition. Boring over clever.
- Mark deliberate shortcuts with `ponytail:` comment.
- Evidence before assertions — run tests after every change.
- Always use `uv` for Python operations in this project."""


PDF_PROMPT = """## pdf_handling
PDF files CANNOT be read with read_file() — it returns raw binary.
Use parse_pdf(path) instead — returns clean Markdown via Docling.
When a user attaches a PDF, its content is already parsed and in context."""


REMOTION_SKILL_DIR = Path(os.environ.get("SICK_REMOTION_DIR", Path.home() / ".agents" / "skills"))
REMOTION_REFERENCE_HINT = (
    "\n\nReference guides (markup, render, captions, maps, studio, saas) live in "
    "~/.agents/skills/remotion-best-practices/ — when a guide is relevant, read it "
    "with `bash cat ~/.agents/skills/remotion-best-practices/remotion-markup/REFERENCE.md` "
    "(adjust the subdirectory) and follow its guidance."
)
REMOTION_FALLBACK = """## remotion
You create explanatory videos with Remotion (https://remotion.dev).
The remotion skill files are missing. Install them with:
    npx skills add remotion-dev/skills@remotion-create -g -y
    npx skills add remotion-dev/skills@remotion-best-practices -g -y
Then scaffold with `npx create-video@latest --yes --blank --no-tailwind <name>`
and render with `npx remotion render`."""


def _load_remotion_skill(base: Path = REMOTION_SKILL_DIR) -> str:
    parts = []
    for name in ("remotion-best-practices", "remotion-create"):
        try:
            parts.append((base / name / "SKILL.md").read_text())
        except OSError:
            continue
    if not parts:
        return REMOTION_FALLBACK
    return "\n\n".join(parts) + REMOTION_REFERENCE_HINT


def _get_remotion_prompt() -> str:
    try:
        return _load_remotion_skill()
    except Exception:
        return REMOTION_FALLBACK


# ponytail: lazy so import doesn't hit filesystem in tests
REMOTION_PROMPT = ""


class _LazyRemotionSkill(Skill):
    context_block = ("remotion", "")

    def attach(self, agent):
        prompt = _get_remotion_prompt()
        agent.context["remotion"] = prompt
        self.context_block = ("remotion", prompt)


SDLC_PROMPT = """## sdlc_and_oo
- Work in SDLC phases, but keep them lightweight: requirements (what problem,
  edge cases) -> design (structure, key interfaces) -> implement -> verify
  (tests) -> summarize. Skip phases that add nothing for the task.
- Prefer object-oriented structure where it earns its keep: encapsulation,
  single responsibility, clear boundaries between components. Flat code wins
  when a class adds nothing.
- No speculative abstraction (see ponytail): interfaces, factories, and layers
  only when there is more than one real consumer or variant."""


class PonytailSkill(Skill):
    context_block = ("ponytail", PONYTAIL_PROMPT)

    def attach(self, agent):
        agent.context["ponytail"] = PONYTAIL_PROMPT


class PDFSkill(Skill):
    context_block = ("pdf_handling", PDF_PROMPT)

    def attach(self, agent):
        agent.context["pdf_handling"] = PDF_PROMPT


class RemotionSkill(_LazyRemotionSkill):
    pass


class SdlcSkill(Skill):
    context_block = ("sdlc", SDLC_PROMPT)

    def attach(self, agent):
        agent.context["sdlc"] = SDLC_PROMPT


class SickAgent(InteractiveAgent):
    """You are Sick, a coding agent who modifies itself to get better over time.

    Core philosophy (ponytail, always active):
    - Shortest correct solution. No over-engineering.
    - Stdlib before dependencies. Native features before libraries.
    - Deletion over addition. Boring over clever.
    - Mark deliberate shortcuts with `ponytail:` comment.
    - Evidence before assertions — run tests after every change.
    - Always use `uv` for Python operations in this project.

    Available tools:
    {doc(self)}

    Past experiences relevant to this task:
    {self._recall_for_prompt}
    """

    _tools: dict[str, Tool]
    memory: ExperienceMemory

    def __init__(
        self,
        attachments: list[str] | None = None,
        skills: list[Skill] | None = None,
        workspace: str | Path = ".",
        **kwargs: Any,
    ):
        super().__init__(**kwargs)
        self.memory = ExperienceMemory()
        self._tools = {}
        self._skills: list[Skill] = skills or []
        self.workspace = Path(workspace).resolve()
        if not self.workspace.is_dir():
            raise ValueError(f"workspace is not a directory: {workspace}")

        cfg = load_config(self.workspace)
        self.audit = AuditLog(self.workspace)
        self._tool_counts: dict[str, int] = {}
        self.turns = 0

        from sick.tools.base import EXCLUDED_DIRS as _EXCL

        merged_excluded = set(_EXCL) | set(cfg.get("excluded") or [])
        # CodeResearch builds index on init; ensure it uses merged excluded
        # by setting excluded before build (rebuild if needed)
        code_research_tool = CodeResearch(str(self.workspace))
        if getattr(code_research_tool.index, "excluded", None) != merged_excluded:
            code_research_tool.index.excluded = merged_excluded
            # rebuild if config adds exclusions (cheap: uses cache when possible)
            code_research_tool.index.build()
            code_research_tool.chunk_count = len(code_research_tool.index.chunks)

        for t in [
            ReadFile(self.workspace), WriteFile(self.workspace), EditFile(self.workspace),
            Bash(self.workspace), Grep(self.workspace), Glob(self.workspace),
            ParsePdf(self.workspace), code_research_tool, SelfRead(), SelfWrite(),
            FetchUrl(), Checkpoint(self.workspace), Restore(self.workspace),
            ListCheckpoints(self.workspace),
        ]:
            t.excluded = merged_excluded
            self._tools[t.name] = t

        self._register_skill(PonytailSkill())
        self._register_skill(PDFSkill())
        self._register_skill(RemotionSkill())
        self._register_skill(SdlcSkill())
        for skill in self._skills:
            self._register_skill(skill)

        self._handle_attachments(attachments or [])

        spec(self, "memory", hidden=False)

    def _register_skill(self, skill: Skill) -> None:
        attr_name = type(skill).__name__.lower().replace("skill", "")
        setattr(self, attr_name, skill)
        skill.attach(self)
        spec(self, attr_name, hidden=False)

    def _handle_attachments(self, attachments: list[str]) -> None:
        MAX_ATTACH_BYTES = 100_000
        for a in attachments:
            p = Path(a)
            if not p.exists() or p.is_dir():
                continue
            if p.suffix.lower() == ".pdf":
                tool = self._tools.get("parse_pdf")
                if tool:
                    md = self._call("parse_pdf", path=str(p))
                    self.context[f"attachment_{p.stem}"] = md
            else:
                try:
                    # Reuse workspace confinement: try read_file, fallback raw read with bound
                    content = self._tools["read_file"].execute(path=str(p))
                    if content.startswith("Error:"):
                        content = p.read_text(errors="replace")[:MAX_ATTACH_BYTES]
                    else:
                        content = content[:MAX_ATTACH_BYTES]
                    if len(content) >= MAX_ATTACH_BYTES:
                        content += f"\n[truncated after {MAX_ATTACH_BYTES} bytes]"
                    self.context[f"attachment_{p.stem}"] = content
                except Exception as e:
                    self.context[f"attachment_{p.stem}"] = f"[unreadable: {e}]"

    # ── tool proxy methods ──

    def _call(self, tool: str, **kwargs: Any) -> Any:
        start = time.monotonic()
        result = self._tools[tool].execute(**kwargs)
        # ponytail: type-aware ok detection — bool/list/str each have distinct error shapes
        if isinstance(result, bool):
            ok = result
        elif isinstance(result, list):
            ok = not (result and isinstance(result[0], str) and result[0].startswith("Error:"))
        elif isinstance(result, str):
            head = result.strip()[:12]
            ok = not head.startswith(("Error", "[error", "[timed out", "[exit code"))
        else:
            ok = True
        try:
            self.audit.record(tool, ok=ok, duration_ms=round((time.monotonic() - start) * 1000), **kwargs)
        except Exception:
            pass
        self._tool_counts[tool] = self._tool_counts.get(tool, 0) + 1
        return result

    def read_file(self, path: str, offset: int = 0, limit: int | None = None) -> str:
        return self._call("read_file", path=path, offset=offset, limit=limit)

    def write_file(self, path: str, content: str) -> str:
        return self._call("write_file", path=path, content=content)

    def edit_file(self, path: str, old: str, new: str) -> bool:
        return self._call("edit_file", path=path, old=old, new=new)

    def bash(self, command: str, timeout: int = 60) -> str:
        return self._call("bash", command=command, timeout=timeout)

    def grep(self, pattern: str, include: str | None = None, path: str = ".") -> list[str]:
        return self._call("grep", pattern=pattern, include=include, path=path)

    def glob(self, pattern: str, path: str = ".") -> list[str]:
        return self._call("glob", pattern=pattern, path=path)

    def parse_pdf(self, path: str) -> str:
        return self._call("parse_pdf", path=path)

    def code_research(self, query: str, k: int = 8) -> str:
        return self._call("code_research", query=query, k=k)

    def fetch_url(self, url: str) -> str:
        return self._call("fetch_url", url=url)

    def checkpoint(self, message: str = "checkpoint") -> str:
        return self._call("checkpoint", message=message)

    def restore(self, n: int = 1) -> str:
        return self._call("restore", n=n)

    def checkpoints(self) -> str:
        return self._call("checkpoints")

    # ── self-modification helpers ──

    def self_read(self, path: str) -> str:
        return self._call("self_read", path=path)

    def self_write(self, path: str, content: str) -> str:
        return self._call("self_write", path=path, content=content)

    # ── memory ──

    def _recall_for_prompt(self) -> str:
        results = self.memory.recall("")
        if not results:
            return "No past experiences yet."
        lines = []
        for e in results:
            lines.append(f"- {e.task}: {e.outcome} (pattern: {e.pattern}, tools: {', '.join(e.tools)})")
        return "\n".join(lines)

    def _record_experience(self, task: str, outcome: str, pattern: str) -> None:
        tools = sorted(self._tool_counts.keys())
        self.memory.record(Experience(task=task, outcome=outcome, pattern=pattern, tools=tools))

    # ── interactive turn protocol ──

    @hidden
    async def handle(self, notification: dict[str, list]) -> RespondResult:
        msgs = notification.get("user_messages", [])
        if msgs:
            self.context["user_request"] = msgs[-1]
            self.turns += 1
            await self.respond()
            self._record_experience(msgs[-1][:80], "success", "chat turn")
            return RespondResult(
                kind=RespondReason.DONE,
                explanation="answered the request; waiting for the next user message",
            )
        for cmd in notification.get("slash_commands", []):
            value = getattr(cmd, "value", cmd)
            text = getattr(cmd, "text", str(cmd))
            self.context["user_request"] = f"Slash command result: {text}"
            await self.respond()
            return RespondResult(
                kind=RespondReason.DONE,
                explanation=str(value or text),
            )
        for sysmsg in notification.get("system_messages", []):
            self.context["user_request"] = str(sysmsg)
            await self.respond()
            return RespondResult(
                kind=RespondReason.DONE,
                explanation="processed system message",
            )
        return RespondResult(
            kind=RespondReason.DONE,
            explanation="no pending input",
        )

    async def respond(self) -> str:
        """Respond to the user's latest message (in the `user_request` context block).

        This is a chat session. Do ALL the work before responding: explore,
        implement, test, iterate. Then reply to the user in Markdown with a
        concise summary of what you did. Call `message()` to send the reply.

        ponytail: always apply the lazy philosophy.
        """
        ...

    # ── one-shot generation methods (CLI mode) ──

    async def run(self, task: str) -> str:
        """Complete a coding task.

        1. Understand the task
        2. Research existing code if needed (grep, read)
        3. Make changes (write_file, edit_file)
        4. Verify with tests/bash
        5. Record experience

        ponytail: always apply the lazy philosophy
        """
        ...

    async def modify_self(self, instruction: str) -> str:
        """Modify sick's own source code to improve capabilities.

        Steps:
        1. self_read('agent.py') — understand current code
        2. Make changes via self_write/edit
        3. bash('uv run python -c "from sick.agent import SickAgent"') — verify import
        4. bash('uv run python -m pytest tests/ -x') — verify tests pass
        5. Record the improvement as an experience

        You can modify: src/sick/agent.py, tools/*.py, skills/*.py, pyproject.toml, README.md
        """
        ...
