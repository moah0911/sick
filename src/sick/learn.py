"""Self-improvement (`/learn`): turn session evidence into one verified fix.

The deterministic half (this module) mines the audit log and experience
memory for what actually went wrong — failing tools, slow calls, repeated
patterns — records a lesson, and builds the prompt for the generative half
(the agent edits its own source, verifies, and checkpoints). Keeping the
evidence collection pure makes it testable without an LLM.
"""

import json
import os
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class ToolStat:
    calls: int = 0
    failures: int = 0
    total_ms: int = 0

    @property
    def avg_ms(self) -> float:
        return self.total_ms / self.calls if self.calls else 0.0

    @property
    def failure_rate(self) -> float:
        return self.failures / self.calls if self.calls else 0.0


@dataclass
class LearnReport:
    turns: int = 0
    focus: str = ""
    tools: dict[str, ToolStat] = field(default_factory=dict)
    recent_failures: list[str] = field(default_factory=list)
    lessons: list[str] = field(default_factory=list)

    @property
    def total_calls(self) -> int:
        return sum(s.calls for s in self.tools.values())


@dataclass
class Lesson:
    """One structured, falsifiable lesson — not a summary sentence.

    Recorded as a candidate by learn_brief; only promoted to verified
    when a self-edit addressing it passes the SDLC delivery gate. If the
    same trigger recurs after that, the lesson is marked ineffective
    instead of being repeated forever.
    """

    trigger: str  # e.g. "tool:checkpoint" or "gate:blocked"
    root_cause: str
    fix_applied: str = ""
    evidence: list[str] = field(default_factory=list)
    verified: bool = False
    ineffective: bool = False
    timestamp: float = 0.0

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = time.time()

    @property
    def key(self) -> str:
        return f"{self.trigger}|{self.root_cause}"


def lessons_path() -> Path:
    base = Path(os.environ.get("SICK_MEMORY_DIR") or (Path.home() / ".sick"))
    return base / "lessons.json"


class LessonStore:
    """JSON-backed lesson store (small data; whole-file rewrite is fine)."""

    def __init__(self, path: str | Path | None = None) -> None:
        self._path = Path(path) if path else lessons_path()

    def all(self) -> list[Lesson]:
        try:
            data = json.loads(self._path.read_text())
            return [Lesson(**d) for d in data if isinstance(d, dict)]
        except (OSError, ValueError, TypeError):
            return []

    def _save(self, lessons: list[Lesson]) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(json.dumps([asdict(x) for x in lessons], indent=2))
            tmp.replace(self._path)
        except OSError:
            pass

    def record(self, lesson: Lesson) -> Lesson:
        """Add a candidate lesson, deduped by trigger+root_cause."""
        lessons = self.all()
        for existing in lessons:
            if existing.key == lesson.key:
                existing.evidence = list(dict.fromkeys(existing.evidence + lesson.evidence))[:5]
                self._save(lessons)
                return existing
        lessons.append(lesson)
        self._save(lessons[-50:])
        return lesson

    def complete_latest(self, fix_applied: str) -> Lesson | None:
        """Promote the newest unverified lesson to verified (fix shipped)."""
        lessons = self.all()
        for lesson in reversed(lessons):
            if not lesson.verified:
                lesson.fix_applied = fix_applied
                lesson.verified = True
                lesson.ineffective = False
                self._save(lessons)
                return lesson
        return None

    def escalate_recurring(self, report: "LearnReport") -> list[Lesson]:
        """Mark verified lessons ineffective when their trigger recurs."""
        lessons = self.all()
        escalated: list[Lesson] = []
        for lesson in lessons:
            if not lesson.verified or lesson.ineffective:
                continue
            tool = lesson.trigger.removeprefix("tool:")
            stat = report.tools.get(tool)
            if stat and stat.failures:
                lesson.ineffective = True
                escalated.append(lesson)
        if escalated:
            self._save(lessons)
        return escalated

    def relevant(self, text: str, limit: int = 2) -> list[Lesson]:
        """Verified lessons whose trigger/root_cause overlaps the text."""
        words = {w for w in text.lower().split() if len(w) > 3}
        hits = [
            x for x in self.all()
            if x.verified and not x.ineffective
            and (x.trigger.split(":")[-1] in text.lower() or words & set(x.root_cause.lower().split()))
        ]
        return hits[-limit:]


def candidate_lesson(report: "LearnReport", workspace) -> Lesson | None:
    """Turn a report into a candidate lesson with a heuristic root cause."""
    if not report.tools:
        return None
    blocked = blocked_run_lessons(workspace)
    evidence = list(blocked) + [f"{f}" for f in report.recent_failures]
    worst_name, worst = max(report.tools.items(), key=lambda kv: kv[1].failure_rate)
    if worst.failures:
        root = f"{worst_name} failed {worst.failures}/{worst.calls} calls"
        if worst_name == "checkpoint" and not (Path(workspace) / ".git").exists():
            root = "checkpoint called in a non-git workspace (session-start checkpoint + retries)"
        return Lesson(trigger=f"tool:{worst_name}", root_cause=root, evidence=evidence[:5])
    if blocked:
        return Lesson(trigger="gate:blocked", root_cause=blocked[0], evidence=evidence[:5])
    return None


def analyze_audit(entries: list[dict], focus: str = "", turns: int = 0) -> LearnReport:
    """Mine audit entries (oldest→newest) for failure/slowness signals."""
    report = LearnReport(turns=turns, focus=focus)
    for e in entries:
        stat = report.tools.setdefault(str(e.get("tool", "?")), ToolStat())
        stat.calls += 1
        stat.total_ms += int(e.get("duration_ms") or 0)
        if not e.get("ok", True):
            stat.failures += 1
            args = ", ".join(f"{k}={str(v)[:40]}" for k, v in (e.get("args") or {}).items())
            report.recent_failures.append(f"{e.get('tool')}({args})" if args else str(e.get("tool")))
    report.recent_failures = report.recent_failures[-5:]

    if not report.tools:
        report.lessons.append("no tool calls recorded yet — nothing to learn from")
        return report
    worst = max(report.tools.items(), key=lambda kv: kv[1].failure_rate)
    if worst[1].failures:
        report.lessons.append(
            f"`{worst[0]}` fails most ({worst[1].failures}/{worst[1].calls} calls) — "
            "inspect its error paths first"
        )
    slowest = max(report.tools.items(), key=lambda kv: kv[1].avg_ms)
    if slowest[1].avg_ms >= 1000:
        report.lessons.append(
            f"`{slowest[0]}` is slowest (avg {slowest[1].avg_ms:.0f}ms) — look for redundant work"
        )
    most_used = Counter({k: v.calls for k, v in report.tools.items()}).most_common(1)
    if most_used:
        report.lessons.append(f"most-used tool: `{most_used[0][0]}` ({most_used[0][1]} calls)")
    if not any(s.failures for s in report.tools.values()):
        report.lessons.append("no tool failures recorded — session was clean; capture what worked")
    return report


def summarize(report: LearnReport, experiences: list | None = None) -> str:
    """Render the report as the markdown brief shown to user and agent."""
    lines = ["## learn — session evidence"]
    if report.focus:
        lines.append(f"focus: {report.focus}")
    lines.append(f"turns: {report.turns} · tool calls: {report.total_calls}")
    for name, s in sorted(report.tools.items(), key=lambda kv: -kv[1].calls):
        lines.append(f"- `{name}`: {s.calls} calls, {s.failures} failed, avg {s.avg_ms:.0f}ms")
    if report.recent_failures:
        lines.append("recent failures:")
        lines += [f"  - {f}" for f in report.recent_failures]
    if experiences:
        lines.append("past experiences:")
        for e in experiences:
            lines.append(f"- {e.task}: {e.outcome} (pattern: {e.pattern})")
    lines.append("lessons:")
    lines += [f"- {lesson}" for lesson in report.lessons]
    return "\n".join(lines)


def blocked_run_lessons(workspace) -> list[str]:
    """Mine persisted SDLC gate verdicts (.sick/runs/*/verification.json)."""
    import json
    from pathlib import Path

    lessons: list[str] = []
    seen: set[str] = set()
    runs = Path(workspace) / ".sick" / "runs"
    if not runs.is_dir():
        return lessons
    for vf in sorted(runs.glob("*/verification.json"))[-5:]:
        try:
            data = json.loads(vf.read_text())
        except (OSError, ValueError):
            continue
        if not data.get("allowed", True):
            for reason in data.get("reasons", [])[:2]:
                lesson = f"blocked run ({data.get('tier', '?')}): {reason}"
                if lesson not in seen:
                    seen.add(lesson)
                    lessons.append(lesson)
    return lessons


def build_learn_prompt(brief: str, focus: str = "") -> str:
    """Prompt for the generative half: one minimal, verified self-improvement."""
    import sys

    from sick.tools.self import SOURCE_ROOT

    scope = f" Focus on: {focus}." if focus else ""
    exe = sys.executable
    return (
        "Learn from this session and improve yourself (sick's own source code).\n\n"
        f"{brief}\n\n"
        "Protocol — follow it exactly. You have a limited iteration budget; "
        "spend it on one edit and its verification, not on exploration.\n"
        "1. Try `checkpoint('pre-learn')` ONCE so the change can be rolled back. "
        "If it errors with 'not a git repository', proceed without a checkpoint "
        "and note that in your summary — do NOT retry it, and do NOT run git "
        "commands to work around it.\n"
        "2. Pick the SINGLE highest-value improvement the evidence supports"
        f" (a failing tool, a repeated mistake, a missing capability).{scope} "
        f"Your self source root (what self_read/self_write operate on) is `{SOURCE_ROOT}`. "
        "Read at most 3 files before editing.\n"
        "3. Make the smallest correct change with `self_write` within your first "
        "few tool calls. Never repeat a failing tool call with the same "
        "arguments — if a call fails twice, change approach or stop. Ponytail "
        "rules apply: deletion over addition, no speculative abstraction.\n"
        f"4. Verify with the interpreter running sick: `bash('{exe} -c \"from sick.agent import SickAgent\"')` "
        f"and `bash('{exe} -m pytest -q')`. If verification fails and you had a "
        "successful checkpoint, `restore(1)` and report what you learned instead "
        "of leaving broken code.\n"
        "5. Reply with `message()` BEFORE you run low on iterations: what you "
        "changed, the evidence that motivated it, and the verification output.\n"
        "If the evidence shows nothing worth changing, say so immediately in "
        "your first reply, record the lesson, and stop. Do not invent busywork."
    )
