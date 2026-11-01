"""Tests for the repo guardian core (callbacks faked; no daemon timing)."""


def test_guardian_green_and_change_detection(tmp_path):
    from sick.guardian import Guardian

    (tmp_path / "a.py").write_text("x = 1\n")
    g = Guardian(tmp_path, verify_fn=lambda: (True, "ok"))
    assert g.check_once() == "green"
    assert g.changed() == []
    (tmp_path / "a.py").write_text("x = 2\n")
    changed = g.changed()
    assert changed == ["a.py"]
    assert g.changed() == []


def test_guardian_fixes_then_blocks_after_budget(tmp_path):
    from sick.guardian import Guardian

    state = {"red": True}
    fixes = []

    def verify():
        return (not state["red"], "1 failed" if state["red"] else "ok")

    def fix(sig, out):
        fixes.append(sig)
        state["red"] = False
        return True

    g = Guardian(tmp_path, verify_fn=verify, fix_fn=fix, max_attempts=2)
    assert g.check_once() == "fixed"
    assert (tmp_path / "AFTERMATH.log").is_file()
    # new failure, fixer never delivers -> attempts exhaust -> blocked
    state["red"] = True
    g.fix_fn = lambda sig, out: False
    assert g.check_once() == "failed"
    assert g.check_once() == "failed"
    assert g.check_once() == "blocked"


def test_guardian_ignores_own_artifacts(tmp_path):
    from sick.guardian import Guardian

    (tmp_path / "a.py").write_text("x = 1\n")
    g = Guardian(tmp_path, verify_fn=lambda: (True, "ok"))
    (tmp_path / "AFTERMATH.log").write_text("guardian: noise\n")
    (tmp_path / ".sick").mkdir(exist_ok=True)
    (tmp_path / ".sick" / "audit.jsonl").write_text("{}\n")
    assert g.changed() == []
