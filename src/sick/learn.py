"""Self-improvement (`/learn`): turn session evidence into one verified fix.

The deterministic half (this module) mines the audit log and experience
memory for what actually went wrong — failing tools, slow calls, repeated
patterns — records a lesson, and builds the prompt for the generative half
(the agent edits its own source, verifies, and checkpoints). Keeping the
evidence collection pure makes it testable without an LLM.
"""

from collections import Counter
from dataclasses import dataclass, field


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
                lessons.append(f"blocked run ({data.get('tier', '?')}): {reason}")
    return lessons


def build_learn_prompt(brief: str, focus: str = "") -> str:
    """Prompt for the generative half: one minimal, verified self-improvement."""
    scope = f" Focus on: {focus}." if focus else ""
    return (
        "Learn from this session and improve yourself (sick's own source code).\n\n"
        f"{brief}\n\n"
        "Protocol — follow it exactly:\n"
        "1. `checkpoint('pre-learn')` first, so the change can be rolled back.\n"
        "2. Pick the SINGLE highest-value improvement the evidence supports"
        f" (a failing tool, a repeated mistake, a missing capability).{scope}\n"
        "3. `self_read` the relevant source, make the smallest correct change "
        "with `self_write`/edit. Ponytail rules apply: deletion over addition, "
        "no speculative abstraction.\n"
        "4. Verify: `bash('uv run python -c \"from sick.agent import SickAgent\"')` "
        "and `bash('uv run pytest -q')`. If verification fails, `restore(1)` and "
        "report what you learned instead of leaving broken code.\n"
        "5. Record the lesson as an experience and reply with: what you changed, "
        "the evidence that motivated it, and the verification output.\n"
        "If the evidence shows nothing worth changing, say so, record the lesson, "
        "and do not invent busywork."
    )
