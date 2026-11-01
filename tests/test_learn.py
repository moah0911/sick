"""Tests for the /learn self-improvement core (sick.learn)."""

from sick.learn import analyze_audit, build_learn_prompt, summarize


def _entry(tool, ok=True, ms=10, **args):
    return {"tool": tool, "ok": ok, "duration_ms": ms, "args": args}


def test_analyze_empty_audit():
    r = analyze_audit([])
    assert r.total_calls == 0
    assert "no tool calls" in r.lessons[0]


def test_analyze_flags_failing_tool():
    entries = [_entry("edit_file", ok=False), _entry("edit_file", ok=False), _entry("read_file")]
    r = analyze_audit(entries, turns=2)
    assert r.tools["edit_file"].failures == 2
    assert r.tools["edit_file"].failure_rate == 1.0
    assert any("edit_file" in lesson and "fails most" in lesson for lesson in r.lessons)
    assert len(r.recent_failures) == 2


def test_analyze_flags_slow_tool_and_caps_failures():
    entries = [_entry("bash", ok=False, ms=5000)] * 7
    r = analyze_audit(entries)
    assert len(r.recent_failures) == 5  # capped
    assert any("slowest" in lesson for lesson in r.lessons)


def test_analyze_clean_session():
    r = analyze_audit([_entry("read_file"), _entry("grep")])
    assert any("no tool failures" in lesson for lesson in r.lessons)
    assert any("most-used" in lesson for lesson in r.lessons)


def test_summarize_and_prompt():
    r = analyze_audit([_entry("bash", ok=False)], focus="speed", turns=3)
    brief = summarize(r)
    assert "focus: speed" in brief and "turns: 3" in brief and "lessons:" in brief
    prompt = build_learn_prompt(brief, "speed")
    assert "checkpoint('pre-learn')" in prompt
    assert "restore(1)" in prompt and "pytest" in prompt
    assert "Focus on: speed." in prompt


def test_blocked_run_lessons_mined(tmp_path):
    import json

    from sick.learn import blocked_run_lessons

    run_dir = tmp_path / ".sick" / "runs" / "r1"
    run_dir.mkdir(parents=True)
    (run_dir / "verification.json").write_text(json.dumps(
        {"allowed": False, "tier": "standard", "reasons": ["no verification evidence after last edit"]}
    ))
    lessons = blocked_run_lessons(tmp_path)
    assert lessons and "blocked run (standard)" in lessons[0]
    assert "verification evidence" in lessons[0]


def test_lesson_store_lifecycle(tmp_path):
    from sick.learn import Lesson, LessonStore, analyze_audit

    store = LessonStore(tmp_path / "lessons.json")
    store.record(Lesson(trigger="tool:checkpoint", root_cause="non-git workspace", evidence=["a"]))
    store.record(Lesson(trigger="tool:checkpoint", root_cause="non-git workspace", evidence=["b"]))
    assert len(store.all()) == 1  # deduped by trigger+root_cause
    assert store.all()[0].evidence == ["a", "b"]
    done = store.complete_latest("host.py: skip checkpoint outside git")
    assert done is not None and done.verified and "host.py" in done.fix_applied
    assert store.relevant("checkpoint fails again")[0].trigger == "tool:checkpoint"
    # recurrence escalates instead of repeating the same lesson forever
    report = analyze_audit([{"tool": "checkpoint", "ok": False, "duration_ms": 1, "args": {}}])
    escalated = store.escalate_recurring(report)
    assert escalated and escalated[0].ineffective
    assert store.relevant("checkpoint") == []


def test_blocked_lessons_deduped(tmp_path):
    import json

    from sick.learn import blocked_run_lessons

    for rid in ("r1", "r2"):
        d = tmp_path / ".sick" / "runs" / rid
        d.mkdir(parents=True)
        (d / "verification.json").write_text(json.dumps(
            {"allowed": False, "tier": "standard", "reasons": ["no verification evidence after last edit"]}
        ))
    lessons = blocked_run_lessons(tmp_path)
    assert len(lessons) == 1


def test_learn_prompt_never_retries_checkpoint(tmp_path):
    from sick.learn import build_learn_prompt

    prompt = build_learn_prompt("brief")
    assert "not a git repository" in prompt and "do NOT retry" in prompt
    assert "at most 3 files" in prompt and "message()" in prompt


def test_python_test_file_counts_as_verification(tmp_path):
    from sick.lifecycle import Lifecycle
    from sick.tools.base import ToolResult

    lc = Lifecycle(tmp_path)
    run = lc.start("build tictactoe")
    lc.record(run, ToolResult.success("Wrote", tool="write_file"), {"path": "test_tictactoe.py"})
    lc.record(run, ToolResult.success("all pass", tool="bash"), {"command": "uv run python test_tictactoe.py"})
    assert lc.can_deliver(run).allowed


def test_self_source_prefers_sick_root_checkout(tmp_path, monkeypatch):
    from sick.tools.self import SelfRead, resolve_source_root

    checkout = tmp_path / "checkout" / "src" / "sick"
    checkout.mkdir(parents=True)
    (checkout / "agent.py").write_text("MARKER = 1\n")
    monkeypatch.setenv("SICK_ROOT", str(tmp_path / "checkout"))
    assert resolve_source_root() == checkout
    assert "MARKER" in SelfRead().execute("agent.py").output


def test_agent_learn_brief_records_lesson(tmp_path):
    from sick.agent import SickAgent
    from sick.memory import ExperienceMemory

    agent = SickAgent(workspace=tmp_path)
    agent.memory = ExperienceMemory(path=tmp_path / "mem.jsonl")
    agent.write_file("a.txt", "hello")
    brief = agent.learn_brief("testing")
    assert "learn" in brief and "write_file" in brief
    remembered = agent.memory.recall("learn")
    assert remembered and remembered[0].outcome == "lesson recorded"
