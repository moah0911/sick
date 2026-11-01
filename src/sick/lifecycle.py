"""Evidence-gated SDLC lifecycle — the deep module behind Sick's SDLC claim.

Small interface (``start`` / ``record`` / ``approve`` / ``can_deliver`` /
``finish``), all gate logic inside. Phases are observed from real tool
results, not requested in a prompt: exploration moves a run to DESIGN,
mutation to IMPLEMENT, a passing verification command after the last
mutation to VERIFY. ``can_deliver`` is a runtime predicate the LLM cannot
override — a STANDARD run with edits but no post-edit verification
evidence is BLOCKED, a RISKY run additionally needs approval + checkpoint
+ a clean hard design check.

Runs persist under ``.sick/runs/<id>/`` (requirements.md, design.md,
plan.md, verification.json, summary.md, run.json) for auditability.
"""

import json
import re
import time
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from sick.design_check import DesignIssue, analyze_files
from sick.tools.base import ToolResult

MUTATING_TOOLS = {"write_file", "edit_file", "self_write"}
EXPLORATION_TOOLS = {"read_file", "grep", "glob", "code_research", "self_read", "load_skill"}
VERIFY_RE = re.compile(
    r"(pytest|ruff|mypy|unittest|npm\s+test|pnpm\s+test|yarn\s+test|go\s+test|cargo\s+test"
    r"|python\d?\s+[^|&;]*\btest_[^\s]+\.py|python\d?\s+[^|&;]*[^\s]+_test\.py)"
)
DESTRUCTIVE_RE = re.compile(r"(\brm\s+-rf\b|DROP\s+TABLE|migrate|alembic)", re.IGNORECASE)
RISKY_PATH_HINTS = ("pyproject.toml", "migration", "auth", "password", "security", "secret")


class Phase(StrEnum):
    INTAKE = "intake"
    REQUIREMENTS = "requirements"
    DESIGN = "design"
    IMPLEMENT = "implement"
    VERIFY = "verify"
    DELIVER = "deliver"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"


class RiskTier(StrEnum):
    TRIVIAL = "trivial"
    STANDARD = "standard"
    RISKY = "risky"


@dataclass
class Evidence:
    tool: str
    detail: str
    seq: int
    at: float = 0.0


@dataclass
class GateVerdict:
    allowed: bool
    reasons: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return self.allowed


@dataclass
class Run:
    id: str
    task: str
    workspace: Path
    phase: Phase = Phase.REQUIREMENTS
    tier: RiskTier = RiskTier.TRIVIAL
    created_at: float = 0.0
    seq: int = 0
    last_mutation_seq: int = 0
    mutations: list[dict[str, Any]] = field(default_factory=list)
    changed_files: list[str] = field(default_factory=list)
    evidences: list[Evidence] = field(default_factory=list)
    explored: bool = False
    plan_created: bool = False
    approved: bool = False
    awaiting_approval: bool = False
    checkpointed: bool = False
    risky_flags: list[str] = field(default_factory=list)
    skills: dict[str, str] = field(default_factory=dict)
    calls_since_progress: int = 0
    verify_failures: int = 0
    verified_mutation_seq: int = 0
    plan_steps: list[dict[str, Any]] = field(default_factory=lambda: [
        {"name": "explore", "done": False},
        {"name": "implement", "done": False},
        {"name": "verify", "done": False},
        {"name": "summarize", "done": False},
    ])
    design_issues: list[DesignIssue] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    outcome: str = ""
    summary: str = ""

    @property
    def dir(self) -> Path:
        return Path(self.workspace) / ".sick" / "runs" / self.id


# phase -> keyword families matched against skill name + description, so
# routing works for the skills people actually install, not just three
# exact names (design skills, review skills, stack skills all match).
_PHASE_SKILL_KEYWORDS: dict[Phase, list[str]] = {
    Phase.REQUIREMENTS: ["domain-modeling", "grilling", "research", "requirements", "discovery"],
    Phase.DESIGN: ["codebase-design", "architecture", "design", "adr", "domain"],
    Phase.IMPLEMENT: ["tdd", "backend", "fastapi", "development", "implementation"],
    Phase.VERIFY: ["tdd", "testing", "pytest", "coverage", "review", "verification"],
}


class Lifecycle:
    """Owns run state, risk classification, gates, artifacts, skill routing."""

    def __init__(self, workspace: str | Path = ".", skills_home: str | Path | None = None) -> None:
        self.workspace = Path(workspace).resolve()
        self._skills_home = Path(skills_home) if skills_home else None
        self._discovered: list | None = None

    # ── run creation / persistence ──

    def start(self, task: str) -> Run:
        run = Run(
            id=time.strftime("%Y%m%d%H%M%S") + "-" + uuid.uuid4().hex[:6],
            task=task,
            workspace=self.workspace,
            created_at=time.time(),
        )
        run.dir.mkdir(parents=True, exist_ok=True)
        self.add_artifact(run, "requirements.md", f"# Requirements\n\nTask: {task}\n")
        self._persist(run)
        return run

    def persist(self, run: Run) -> None:
        self._persist(run)

    def add_artifact(self, run: Run, name: str, content: str) -> Path:
        run.dir.mkdir(parents=True, exist_ok=True)
        path = run.dir / name
        path.write_text(content)
        if name == "plan.md":
            run.plan_created = True
        return path

    def _persist(self, run: Run) -> None:
        try:
            run.dir.mkdir(parents=True, exist_ok=True)
            data = {
                "id": run.id, "task": run.task, "phase": run.phase.value, "tier": run.tier.value,
                "changed_files": run.changed_files, "mutations": run.mutations,
                "evidence": [e.__dict__ for e in run.evidences], "skills": run.skills,
                "approved": run.approved, "checkpointed": run.checkpointed,
                "plan_created": run.plan_created, "outcome": run.outcome,
                "design_issues": [i.__dict__ for i in run.design_issues],
                "warnings": run.warnings,
            }
            (run.dir / "run.json").write_text(json.dumps(data, indent=2, default=str))
        except OSError:
            pass

    # ── phase observation from real tool results ──

    def _step(self, run: Run, name: str) -> None:
        for step in run.plan_steps:
            if step["name"] == name:
                step["done"] = True

    def record(self, run: Run, result: ToolResult, args: dict[str, Any] | None = None) -> None:
        args = args or {}
        run.seq += 1
        run.calls_since_progress += 1
        tool = result.tool or ""
        if tool in EXPLORATION_TOOLS and not run.mutations:
            run.explored = True
            self._step(run, "explore")
            if run.phase in (Phase.REQUIREMENTS, Phase.INTAKE):
                run.phase = Phase.DESIGN
        if tool in MUTATING_TOOLS and result.ok:
            run.calls_since_progress = 0
            self._step(run, "implement")
            if not run.explored and not run.plan_created and not run.mutations:
                run.warnings.append(f"{tool} mutated before any exploration/plan")
            path = str(args.get("path", ""))
            run.mutations.append({"tool": tool, "path": path, "seq": run.seq})
            run.last_mutation_seq = run.seq
            if path and path not in run.changed_files:
                run.changed_files.append(path)
            if tool == "self_write":
                run.risky_flags.append("self_write")
            run.phase = Phase.IMPLEMENT
        if tool == "bash":
            command = str(args.get("command", ""))
            if DESTRUCTIVE_RE.search(command):
                run.risky_flags.append("destructive/migration bash")
            if VERIFY_RE.search(command):
                # Verification is progress only once per mutation. Re-running
                # an already-green suite against unchanged code is a loop,
                # not diligence (the 0.5.1 commit-task screenshot: 9 passes).
                fresh = run.last_mutation_seq > run.verified_mutation_seq
                if result.ok and fresh:
                    run.verified_mutation_seq = run.last_mutation_seq
                    run.calls_since_progress = 0
                    run.verify_failures = 0
                    self._step(run, "verify")
                    run.evidences.append(Evidence(tool=tool, detail=command[:120], seq=run.seq, at=time.time()))
                    if run.mutations:
                        run.phase = Phase.VERIFY
                elif not result.ok:
                    run.verify_failures += 1
        if tool == "checkpoint" and result.ok and "checkpoint created" in str(result.output):
            run.checkpointed = True
        run.tier = self.classify(run)
        self._persist(run)

    def classify(self, run: Run) -> RiskTier:
        if not run.mutations:
            return RiskTier.TRIVIAL
        lowered = [f.lower() for f in run.changed_files]
        if (
            run.risky_flags
            or len(run.changed_files) > 5
            or any(any(h in f for h in RISKY_PATH_HINTS) for f in lowered)
        ):
            return RiskTier.RISKY
        return RiskTier.STANDARD

    # ── gates ──

    def approve(self, run: Run) -> Run:
        run.approved = True
        run.awaiting_approval = False
        if not run.plan_created:
            self.add_artifact(run, "plan.md", f"# Plan (approved)\n\nTask: {run.task}\n")
        if run.phase in (Phase.DESIGN, Phase.REQUIREMENTS, Phase.DELIVER, Phase.BLOCKED):
            run.phase = Phase.IMPLEMENT
        self._persist(run)
        return run

    def create_plan(self, run: Run, content: str = "") -> Run:
        self.add_artifact(run, "plan.md", content or f"# Plan\n\nTask: {run.task}\nStatus: awaiting approval\n")
        run.awaiting_approval = True
        run.phase = Phase.DESIGN
        self._persist(run)
        return run

    def cancel(self, run: Run) -> Run:
        run.phase = Phase.CANCELLED
        run.awaiting_approval = False
        run.outcome = "cancelled"
        self._persist(run)
        return run

    def can_deliver(self, run: Run) -> GateVerdict:
        if run.phase == Phase.CANCELLED:
            return GateVerdict(False, ["run was cancelled"])
        run.tier = self.classify(run)
        reasons: list[str] = []
        hard = [i for i in run.design_issues if i.level == "hard"]
        reasons += [i.message for i in hard]
        if run.tier in (RiskTier.STANDARD, RiskTier.RISKY):
            if not any(e.seq > run.last_mutation_seq for e in run.evidences):
                reasons.append("no verification evidence after last edit — run tests/lint after the final change")
            if run.tier == RiskTier.RISKY:
                if not run.approved:
                    reasons.append("risky run requires approval (/plan then /approve) before delivery")
                if not run.checkpointed:
                    reasons.append("risky run requires a checkpoint before delivery")
        return GateVerdict(not reasons, reasons)

    def finish(self, run: Run, summary: str = "") -> GateVerdict:
        run.design_issues = analyze_files(run.changed_files, run.workspace)
        verdict = self.can_deliver(run)
        run.summary = summary
        run.phase = Phase.DELIVER if verdict.allowed else Phase.BLOCKED
        run.outcome = "delivered" if verdict.allowed else "blocked"
        explored = "yes" if run.explored else "no"
        self.add_artifact(
            run, "design.md",
            f"# Design\n\nExploration before mutation: {explored}\n"
            f"Changed files: {', '.join(run.changed_files) or 'none'}\n"
            f"Skills routed: {json.dumps(run.skills)}\nWarnings: {'; '.join(run.warnings) or 'none'}\n",
        )
        if verdict.allowed:
            self._step(run, "summarize")
        checks = "\n".join(f"- [{'x' if s['done'] else ' '}] {s['name']}" for s in run.plan_steps)
        self.add_artifact(run, "plan.md", f"# Plan\n\nTask: {run.task}\n\n{checks}\n")
        verification = {
            "tier": run.tier.value, "allowed": verdict.allowed, "reasons": verdict.reasons,
            "evidence": [e.__dict__ for e in run.evidences],
            "mutations": run.mutations,
            "design_issues": [i.__dict__ for i in run.design_issues],
            "plan_steps": run.plan_steps,
            "calls_since_progress": run.calls_since_progress,
            "verify_failures": run.verify_failures,
        }
        run.dir.mkdir(parents=True, exist_ok=True)
        (run.dir / "verification.json").write_text(json.dumps(verification, indent=2, default=str))
        gate = "DELIVERED" if verdict.allowed else "BLOCKED: " + "; ".join(verdict.reasons)
        self.add_artifact(
            run, "summary.md",
            f"# Summary\n\nTask: {run.task}\nTier: {run.tier.value}\nGate: {gate}\n\n{summary}\n",
        )
        self._persist(run)
        return verdict

    def prompt(self, run: Run) -> str:
        return (
            f"## sdlc (live, runtime-enforced)\nRun {run.id} · phase {run.phase.value} · tier {run.tier.value}\n"
            "Delivery is gated by sick.lifecycle: edits require verification evidence "
            "after the last edit; risky changes also require approval + checkpoint. "
            "Work: explore (design) -> edit (implement) -> run tests (verify)."
        )

    # ── skill-routed phases ──

    def _skills(self):
        if self._discovered is None:
            try:
                if self._skills_home is not None:
                    from sick.skills import SkillInfo, _parse_frontmatter

                    found: dict[str, Any] = {}
                    base = self._skills_home
                    if base.is_dir():
                        for skill_md in sorted(base.glob("*/SKILL.md")):
                            try:
                                meta, _ = _parse_frontmatter(skill_md.read_text(errors="replace"))
                            except OSError:
                                continue
                            name = str(meta.get("name") or skill_md.parent.name).strip()
                            if name:
                                found[name] = SkillInfo(name=name, description=str(meta.get("description") or name), path=skill_md.parent)
                    self._discovered = sorted(found.values(), key=lambda s: s.name)
                else:
                    from sick.skills import discover_skills

                    self._discovered = discover_skills(self.workspace)
            except Exception:
                self._discovered = []
        return self._discovered

    def skill_for_phase(self, phase: Phase):
        keywords = _PHASE_SKILL_KEYWORDS.get(phase, [])
        skills = self._skills()
        for kw in keywords:
            for skill in skills:
                haystack = f"{skill.name} {skill.description}".lower()
                if kw in haystack:
                    return skill
        return None

    def route_skill(self, run: Run, phase: Phase) -> tuple[str, str] | None:
        skill = self.skill_for_phase(phase)
        if skill is None:
            return None
        try:
            if self._skills_home is not None:
                body = (skill.path / "SKILL.md").read_text(errors="replace")
                body = body.split("---", 2)[-1].strip() if body.startswith("---") else body
            else:
                from sick.skills import load_skill_body

                body = load_skill_body(skill.name, self.workspace) or ""
        except OSError:
            return None
        if not body:
            return None
        run.skills[phase.value] = skill.name
        self._persist(run)
        return skill.name, body[:6000]
