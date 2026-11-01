import os
from pathlib import Path
from typing import Any

from nooa import Skill, hidden, spec
from nooa.interactive import InteractiveAgent, RespondReason, RespondResult

from sick.audit import AuditLog
from sick.config import load_config
from sick.lifecycle import Lifecycle, Phase, Run
from sick.memory import Experience, ExperienceMemory
from sick.tools.base import Tool, ToolResult
from sick.tools.exec import Bash
from sick.tools.files import EditFile, ReadFile, WriteFile
from sick.tools.git import Checkpoint, ListCheckpoints, Restore
from sick.tools.pdf import ParsePdf
from sick.tools.registry import ToolRegistry
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


# ponytail: empty env var means unset (`SICK_REMOTION_DIR=` in .env must not
# resolve to Path("."), which silently disabled the remotion skills)
REMOTION_SKILL_DIR = Path(os.environ.get("SICK_REMOTION_DIR") or (Path.home() / ".agents" / "skills"))
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
    """Short pointer, not the full skill bodies.

    The full Remotion SKILL.md files cost ~1.3k tokens on every LLM call;
    they are also in the discovered-skills index and loadable on demand
    via load_skill(). Always-on context only needs to say they exist.
    """
    try:
        present = [
            name
            for name in ("remotion-best-practices", "remotion-create")
            if (REMOTION_SKILL_DIR / name / "SKILL.md").is_file()
        ]
        if not present:
            return REMOTION_FALLBACK
        paths = ", ".join(f"`{REMOTION_SKILL_DIR / name / 'SKILL.md'}`" for name in present)
        return (
            "## remotion\n"
            "You create explanatory videos with Remotion (https://remotion.dev). "
            f"Full skill instructions are installed at {paths} — read the matching one "
            "with load_skill(name) or read_file before scaffolding, then render with "
            "`npx remotion render`." + REMOTION_REFERENCE_HINT
        )
    except Exception:
        return REMOTION_FALLBACK


class _LazyRemotionSkill(Skill):
    context_block = ("remotion", "")

    def attach(self, agent):
        prompt = _get_remotion_prompt()
        agent.context["remotion"] = prompt
        self.context_block = ("remotion", prompt)


SDLC_PROMPT = """## sdlc_and_oo
SDLC is runtime-enforced by sick.lifecycle (see the live `sdlc_state` context
block): phases are observed from tool results, and delivery is blocked
without verification evidence after the last edit. Prefer OO structure where
it earns its keep (deep modules, small interfaces); flat code wins otherwise."""


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
        self._skills: list[Skill] = skills or []
        self.workspace = Path(workspace).resolve()
        if not self.workspace.is_dir():
            raise ValueError(f"workspace is not a directory: {workspace}")

        cfg = load_config(self.workspace)
        self.audit = AuditLog(self.workspace)
        self.lifecycle = Lifecycle(self.workspace)
        self.current_run: Run | None = None
        self.registry = ToolRegistry(audit=self.audit, on_result=self._record_lifecycle)
        self._tools = self.registry.tools
        self._tool_counts = self.registry.counts()
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
            self.registry.register(t)

        self._register_skill(PonytailSkill())
        self._register_skill(PDFSkill())
        self._register_skill(RemotionSkill())
        self._register_skill(SdlcSkill())
        for skill in self._skills:
            self._register_skill(skill)
        self._register_discovered_skills()

        self._handle_attachments(attachments or [])

        spec(self, "memory", hidden=False)

    def _register_skill(self, skill: Skill) -> None:
        attr_name = type(skill).__name__.lower().replace("skill", "")
        setattr(self, attr_name, skill)
        skill.attach(self)
        spec(self, attr_name, hidden=False)

    def _register_discovered_skills(self) -> None:
        """Index every installed SKILL.md (name + description) for on-demand use."""
        try:
            from sick.skills import discover_skills, skills_index_prompt

            self.discovered_skills = discover_skills(self.workspace)
            if self.discovered_skills:
                self.context["skills"] = skills_index_prompt(self.discovered_skills)
        except Exception:
            self.discovered_skills = []

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
                    result = self.registry.call("read_file", path=str(p))
                    content = str(result.output)
                    if not result.ok:
                        content = p.read_text(errors="replace")[:MAX_ATTACH_BYTES]
                    else:
                        content = content[:MAX_ATTACH_BYTES]
                    if len(content) >= MAX_ATTACH_BYTES:
                        content += f"\n[truncated after {MAX_ATTACH_BYTES} bytes]"
                    self.context[f"attachment_{p.stem}"] = content
                except Exception as e:
                    self.context[f"attachment_{p.stem}"] = f"[unreadable: {e}]"

    # ── lifecycle ──

    def _record_lifecycle(self, result: ToolResult, args: dict) -> None:
        if self.current_run is not None:
            self.lifecycle.record(self.current_run, result, args)

    def begin_run(self, task: str, *, planned: bool = False, approved: bool = False) -> Run:
        """Start an evidence-gated SDLC run and route phase skills.

        `approved=True` is for CLI one-shot/modify/learn invocations: typing
        the command is the human's approval to execute. Interactive TUI runs
        leave it False, so RISKY runs there need /plan -> /approve.
        """
        run = self.lifecycle.start(task)
        if planned:
            self.lifecycle.create_plan(run)
        if approved:
            self.lifecycle.approve(run)
        self.current_run = run
        for phase in (Phase.REQUIREMENTS, Phase.DESIGN, Phase.VERIFY):
            routed = self.lifecycle.route_skill(run, phase)
            if routed:
                name, body = routed
                self.context[f"skill_{phase.value}"] = body
        self.context["sdlc_state"] = self.lifecycle.prompt(run)
        return run

    def finish_run(self, summary: str = "") -> Any:
        """Apply the delivery gate to the current run. Returns the verdict."""
        if self.current_run is None:
            return None
        verdict = self.lifecycle.finish(self.current_run, summary)
        self.context["sdlc_state"] = self.lifecycle.prompt(self.current_run)
        self.context["sdlc_result"] = (
            "DELIVERED" if verdict.allowed else "BLOCKED: " + "; ".join(verdict.reasons)
        )
        return verdict

    def switch_provider(self, provider: str) -> str:
        """Switch the active LLM provider live (key must already be saved).

        Persists SICK_PROVIDER via set_active_provider (which also clears
        stale endpoint/model), recreates the LLM, and hot-swaps it so the
        running session uses the new provider without a restart.
        """
        import os

        from sick.providers import PROVIDER_KEYS, detect, set_active_provider

        provider = provider.strip().lower()
        if provider not in PROVIDER_KEYS:
            return f"unknown provider `{provider}` — choose: {', '.join(PROVIDER_KEYS)}"
        var = PROVIDER_KEYS[provider]
        if not os.environ.get(var):
            return f"{var} is not set — run `sick --setup` in a terminal to add the {provider} key (keys are never entered in chat)"
        set_active_provider(self.workspace / ".env", provider)
        try:
            new_llm = detect().create_llm()
        except Exception as e:
            return f"saved {provider} as active, but creating its client failed ({e}) — restart sick"
        # NOOA stores the client under _llm (see PromptCommand); set both spellings
        self._llm = new_llm  # type: ignore[attr-defined]
        try:
            self.llm = new_llm  # type: ignore[attr-defined]
        except Exception:
            pass
        active = detect()
        return f"switched to {provider}: `{active.model_id}` via {active.name} (live, no restart)"

    # ── tool proxy methods (rendered output for the LLM; ToolResult inside) ──

    def _call_result(self, tool: str, **kwargs: Any) -> ToolResult:
        return self.registry.call(tool, **kwargs)

    def _call(self, tool: str, **kwargs: Any) -> Any:
        return self.registry.call(tool, **kwargs).output

    def read_file(self, path: str, offset: int = 0, limit: int | None = None) -> str:
        return str(self._call("read_file", path=path, offset=offset, limit=limit))

    def write_file(self, path: str, content: str) -> str:
        return str(self._call("write_file", path=path, content=content))

    def edit_file(self, path: str, old: str, new: str) -> bool:
        return bool(self._call_result("edit_file", path=path, old=old, new=new).ok)

    def bash(self, command: str, timeout: int = 60) -> str:
        return str(self._call("bash", command=command, timeout=timeout))

    def grep(self, pattern: str, include: str | None = None, path: str = ".") -> list[str]:
        out = self._call("grep", pattern=pattern, include=include, path=path)
        return out if isinstance(out, list) else [str(out)]

    def glob(self, pattern: str, path: str = ".") -> list[str]:
        out = self._call("glob", pattern=pattern, path=path)
        return out if isinstance(out, list) else [str(out)]

    def parse_pdf(self, path: str) -> str:
        return str(self._call("parse_pdf", path=path))

    def code_research(self, query: str, k: int = 8) -> str:
        return str(self._call("code_research", query=query, k=k))

    def fetch_url(self, url: str) -> str:
        return str(self._call("fetch_url", url=url))

    def load_skill(self, name: str) -> str:
        """Load the full instructions of an installed skill by name (see the skills index)."""
        from sick.skills import load_skill_body

        body = load_skill_body(name, self.workspace)
        if body is not None and self.current_run is not None:
            self.lifecycle.record(self.current_run, ToolResult.success(body[:200], tool="load_skill"), {"name": name})
        return body if body is not None else f"Error: unknown skill: {name}"

    def checkpoint(self, message: str = "checkpoint") -> str:
        return str(self._call("checkpoint", message=message))

    def restore(self, n: int = 1) -> str:
        return str(self._call("restore", n=n))

    def checkpoints(self) -> str:
        return str(self._call("checkpoints"))

    # ── self-modification helpers ──

    def self_read(self, path: str) -> str:
        return str(self._call("self_read", path=path))

    def self_write(self, path: str, content: str) -> str:
        return str(self._call("self_write", path=path, content=content))

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

    def learn_brief(self, focus: str = "") -> str:
        """Mine audit + memory for lessons, record one, return the brief.

        Deterministic half of `/learn`; the generative half (actually editing
        sick's source) runs from `sick.learn.build_learn_prompt`'s prompt.
        """
        from sick.learn import analyze_audit, blocked_run_lessons, summarize

        report = analyze_audit(self.audit.entries(100), focus=focus, turns=self.turns)
        report.lessons = blocked_run_lessons(self.workspace) + report.lessons
        brief = summarize(report, self.memory.recall(""))
        lesson = report.lessons[0] if report.lessons else "session reviewed"
        self.memory.record(
            Experience(
                task=f"learn: {focus or 'session review'}",
                outcome="lesson recorded",
                pattern=lesson,
                tools=sorted(self._tool_counts.keys()),
            )
        )
        return brief

    # ── interactive turn protocol ──

    @hidden
    async def handle(self, notification: dict[str, list]) -> RespondResult:
        msgs = notification.get("user_messages", [])
        if msgs:
            task = msgs[-1]
            # Reuse a planned run: awaiting approval = planning turn (do not
            # finish it); approved = execution turn (gate it). Else start fresh.
            run = self.current_run
            planning_turn = bool(
                run is not None and run.plan_created and not run.approved
                and run.phase in (Phase.DESIGN, Phase.REQUIREMENTS)
            )
            if run is None or not (planning_turn or (run.approved and run.phase == Phase.IMPLEMENT)):
                run = self.begin_run(str(task))
                planning_turn = False
            self.context["user_request"] = task
            self.turns += 1
            await self.respond()
            if planning_turn:
                run.phase = Phase.DESIGN  # type: ignore[union-attr]
                self.lifecycle.persist(run)
                self._record_experience(str(task)[:80], "planned", f"sdlc:{run.phase.value}:{run.tier.value}")  # type: ignore[union-attr]
                return RespondResult(
                    kind=RespondReason.DONE,
                    explanation="plan produced; awaiting /approve or /reject",
                )
            verdict = self.finish_run("chat turn")
            delivered = bool(verdict and verdict.allowed)
            outcome = "success" if delivered else "blocked"
            pattern = f"sdlc:{run.phase.value}:{run.tier.value}" if run else "chat turn"
            self._record_experience(str(task)[:80], outcome, pattern)
            return RespondResult(
                kind=RespondReason.DONE,
                explanation=(
                    "delivered; waiting for the next user message" if delivered
                    else f"blocked by SDLC gate: {'; '.join(verdict.reasons) if verdict else 'no run'}"
                ),
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
        1. checkpoint('pre-modify') first — self_write makes this a RISKY run
           and the SDLC gate requires a checkpoint before delivery
        2. self_read('agent.py') — understand current code
        3. Make changes via self_write/edit
        4. bash('uv run python -c "from sick.agent import SickAgent"') — verify import
        5. bash('uv run python -m pytest tests/ -x') — verify tests pass
           (verification must come after the last edit or delivery is blocked)
        6. Record the improvement as an experience

        You can modify: src/sick/agent.py, tools/*.py, skills/*.py, pyproject.toml, README.md
        """
        ...
