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
