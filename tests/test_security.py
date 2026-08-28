"""Security tests: workspace confinement, SSRF, audit redaction."""

from sick.agent import SickAgent
from sick.tools.web import FetchUrl


def test_attachment_blocks_outside_workspace(tmp_path):
    # TUI attachments are user-initiated so they are ALLOWED outside workspace;
    # tool confinement must still block direct read_file outside
    outside = tmp_path.parent / "secret.txt"
    outside.write_text("private")
    agent = SickAgent(workspace=tmp_path)
    # tool read should be blocked
    assert "escapes workspace" in agent.read_file(str(outside))
    # but TUI @ attach is intentionally allowed (user explicitly asked)
    app = __import__("sick.tui.app", fromlist=["SickApp"]).SickApp(agent)
    out = app._expand_attachments(f"see @{outside}")
    assert "private" in out


def test_fetch_url_blocks_localhost():
    out = FetchUrl().execute("http://localhost:5001/secret")
    assert "blocked host" in out


def test_fetch_url_blocks_metadata():
    out = FetchUrl().execute("http://169.254.169.254/latest/meta-data/")
    assert "blocked host" in out


def test_fetch_url_rejects_credentials():
    out = FetchUrl().execute("http://user:pass@example.com/")
    assert "credentials not allowed" in out or "blocked" in out


def test_audit_redacts_api_key(tmp_path):
    agent = SickAgent(workspace=tmp_path)
    agent.write_file("secret.txt", "OPENAI_API_KEY=sk-1234567890abcdef")
    entries = agent.audit.entries()
    text = str(entries)
    assert "sk-1234567890abcdef" not in text
    assert "[REDACTED]" in text or "REDACTED" in text


def test_grep_include_uses_fnmatch(tmp_path):
    (tmp_path / "a.py").write_text("needle here\n")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "b.py").write_text("needle here too\n")
    (tmp_path / "c.txt").write_text("needle\n")
    from sick.tools.search import Grep

    results = Grep(tmp_path).execute("needle", include="*.py")
    assert any("a.py" in r for r in results)
    assert any("b.py" in r for r in results)
    assert not any("c.txt" in r for r in results)


def test_tools_excluded_union(tmp_path):
    (tmp_path / ".sick").mkdir()
    (tmp_path / ".sick" / "config.toml").write_text('excluded = ["vendor"]\n')
    (tmp_path / "vendor").mkdir()
    (tmp_path / "vendor" / "x.py").write_text("v=1\n")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "y.py").write_text("n=1\n")
    (tmp_path / "keep.py").write_text("k=1\n")
    agent = SickAgent(workspace=tmp_path)
    found = agent.glob("*.py")
    assert "keep.py" in found
    assert "vendor/x.py" not in found
    assert "node_modules/y.py" not in found


def test_memory_survives_corrupt_line(tmp_path):
    from sick.memory import ExperienceMemory

    p = tmp_path / "mem.jsonl"
    p.write_text('{"task":"ok","outcome":"success","pattern":"p","tools":[],"timestamp":1}\n')
    p.write_text(p.read_text() + "not json\n", encoding="utf-8")
    mem = ExperienceMemory(path=p)
    # should not crash, returns the one good entry
    assert len(mem.recall("ok")) == 1


def test_edit_audit_ok_is_false(tmp_path):
    agent = SickAgent(workspace=tmp_path)
    agent.write_file("a.txt", "hello")
    ok = agent.edit_file("a.txt", "missing", "new")
    assert ok is False
    entries = agent.audit.entries()
    edit_entry = [e for e in entries if e["tool"] == "edit_file"][-1]
    assert edit_entry["ok"] is False
