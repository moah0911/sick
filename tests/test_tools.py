"""Unit tests for Sick tools."""
import sys
import tempfile
from pathlib import Path
from types import ModuleType

from sick.tools.exec import Bash
from sick.tools.files import MAX_READ_BYTES, EditFile, ReadFile, WriteFile
from sick.tools.search import Glob, Grep


def test_read_file():
    t = ReadFile()
    r = t.execute(__file__)
    assert "test_read_file" in r


def test_write_and_read():
    root = Path(tempfile.mkdtemp())
    w = WriteFile(root)
    r = w.execute("test.txt", "hello world")
    assert r.startswith("Wrote")
    r = ReadFile(root).execute("test.txt")
    assert r == "hello world"


def test_edit_file():
    root = Path(tempfile.mkdtemp())
    WriteFile(root).execute("test.txt", "hello world")
    assert EditFile(root).execute("test.txt", "world", "sick")
    assert ReadFile(root).execute("test.txt") == "hello sick"


def test_edit_file_no_match():
    root = Path(tempfile.mkdtemp())
    WriteFile(root).execute("test.txt", "hello")
    assert not EditFile(root).execute("test.txt", "nope", "x")


def test_bash():
    t = Bash()
    r = t.execute("echo hello")
    assert "hello" in r


def test_bash_failure():
    t = Bash()
    r = t.execute("exit 1")
    assert "exit code 1" in r


def test_grep():
    t = Grep()
    r = t.execute("def test_grep", path="tests")
    assert any("test_grep" in line for line in r)


def test_glob():
    t = Glob()
    r = t.execute("*.py", path="tests")
    assert len(r) > 0


def test_file_tools_reject_paths_outside_workspace(tmp_path):
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("private")
    reader = ReadFile(tmp_path)

    assert "escapes workspace" in reader.execute("../outside.txt")
    assert "escapes workspace" in WriteFile(tmp_path).execute("../new.txt", "nope")
    assert not EditFile(tmp_path).execute("../outside.txt", "private", "public")
    assert outside.read_text() == "private"


def test_file_tools_reject_symlink_escaping_workspace(tmp_path):
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("private")
    link = tmp_path / "link.txt"
    link.symlink_to(outside)

    assert "escapes workspace" in ReadFile(tmp_path).execute("link.txt")


def test_read_file_honors_ranges_and_truncates_large_files(tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text("one\ntwo\nthree\n")
    reader = ReadFile(tmp_path)

    assert reader.execute("notes.txt", offset=1, limit=1) == "two\n"
    assert "non-negative" in reader.execute("notes.txt", offset=-1)

    (tmp_path / "large.txt").write_text("x" * (MAX_READ_BYTES + 1))
    assert "[truncated after 500000 bytes]" in reader.execute("large.txt")


def test_edit_file_requires_a_single_match(tmp_path):
    (tmp_path / "notes.txt").write_text("repeat repeat")

    assert not EditFile(tmp_path).execute("notes.txt", "repeat", "changed")
    assert (tmp_path / "notes.txt").read_text() == "repeat repeat"


def test_search_tools_skip_hidden_binary_and_generated_files(tmp_path):
    (tmp_path / "visible.py").write_text("needle\n")
    (tmp_path / ".hidden.py").write_text("needle\n")
    (tmp_path / "build").mkdir()
    (tmp_path / "build" / "generated.py").write_text("needle\n")
    (tmp_path / "binary.bin").write_bytes(b"needle\0")

    assert Grep(tmp_path).execute("needle") == ["visible.py:1: needle"]
    assert Glob(tmp_path).execute("*.py") == ["visible.py"]
    assert Grep(tmp_path).execute("[")[0].startswith("Error:")


def test_bash_validates_timeout_and_truncates_output(tmp_path):
    bash = Bash(tmp_path)

    assert "timeout must be" in bash.execute("echo nope", timeout=0)
    assert "timed out" in bash.execute("sleep 2", timeout=1)
    out = bash.execute("python -c \"print('x' * 21000)\"")
    assert "[truncated after 20000 characters]" in out


def test_parse_pdf_page_ranges_with_mocked_docling(tmp_path, monkeypatch):
    from sick.tools.pdf import ParsePdf

    pdf = tmp_path / "report.pdf"
    pdf.write_bytes(b"%PDF")
    calls: list[tuple[int, int]] = []

    class FakeDocument:
        def __init__(self, page_range):
            self.page_range = page_range

        def export_to_markdown(self):
            return f"pages {self.page_range[0]}-{self.page_range[1]}"

    class FakeConverter:
        def convert(self, source, page_range=None):
            calls.append(page_range or (1, 999))
            return type("Result", (), {"document": FakeDocument(calls[-1])})()

    docling = ModuleType("docling")
    docling.__path__ = []
    converter_module = ModuleType("docling.document_converter")
    converter_module.DocumentConverter = FakeConverter
    monkeypatch.setitem(sys.modules, "docling", docling)
    monkeypatch.setitem(sys.modules, "docling.document_converter", converter_module)

    tool = ParsePdf(tmp_path)
    monkeypatch.setattr(tool, "available", lambda: True)
    assert tool.execute_pages("report.pdf", "1-2, 5") == "pages 1-2\n\npages 5-5"
    assert calls == [(1, 2), (5, 5)]
    assert "invalid page range" in tool.execute_pages("report.pdf", "0-2")


def test_self_tools_stay_within_their_source_root(tmp_path):
    from sick.tools.self import SelfRead, SelfWrite

    writer = SelfWrite(tmp_path)
    assert writer.execute("tool.py", "answer = 42\n").startswith("Wrote")
    assert "answer = 42" in SelfRead(tmp_path).execute("tool.py")
    assert "escapes workspace" in SelfRead(tmp_path).execute("../outside.py")


def test_agent_registers_every_advertised_tool():
    from sick.agent import SickAgent

    agent = SickAgent()
    assert {
        "read_file", "write_file", "edit_file", "bash", "grep", "glob",
        "parse_pdf", "code_research", "self_read", "self_write",
    } <= agent._tools.keys()
    assert "class SickAgent" in agent.self_read("agent.py")


def test_experience_memory(tmp_path):
    from sick.memory import Experience, ExperienceMemory
    mem = ExperienceMemory(path=tmp_path / "mem.jsonl")
    mem.record(Experience(task="add dark mode", outcome="success", pattern="css variables", tools=["read_file", "edit_file"]))
    results = mem.recall("dark mode")
    assert len(results) == 1
    assert results[0].task == "add dark mode"


def test_remotion_skill_default_in_agent_context(monkeypatch):
    from sick import agent as agent_module
    from sick.agent import SickAgent

    monkeypatch.setattr(agent_module, "_get_remotion_prompt", lambda: "## remotion\nfake skill body")
    agent = SickAgent()
    assert agent.context["remotion"] == "## remotion\nfake skill body"
    assert agent.remotion is not None


def test_remotion_skill_loader_combines_installed_skills(tmp_path):
    from sick.agent import _load_remotion_skill

    (tmp_path / "remotion-best-practices").mkdir()
    (tmp_path / "remotion-create").mkdir()
    (tmp_path / "remotion-best-practices" / "SKILL.md").write_text("best practices body")
    (tmp_path / "remotion-create" / "SKILL.md").write_text("create body")
    out = _load_remotion_skill(tmp_path)
    assert "best practices body" in out and "create body" in out
    assert "remotion-best-practices/" in out
    assert "npx skills add" not in out


def test_remotion_skill_loader_fallback(tmp_path):
    from sick.agent import _load_remotion_skill

    out = _load_remotion_skill(tmp_path / "missing")
    assert "npx skills add" in out


def test_sdlc_skill_default_in_agent_context(monkeypatch):
    from sick import agent as agent_module
    from sick.agent import SickAgent

    monkeypatch.setattr(agent_module, "SDLC_PROMPT", "## sdlc\nfake sdlc body")
    agent = SickAgent()
    assert agent.context["sdlc"] == "## sdlc\nfake sdlc body"
    assert agent.sdlc is not None


def test_parse_pdf_unavailable():
    from sick.tools.pdf import ParsePdf
    t = ParsePdf()
    if not t.available():
        r = t.execute("dummy.pdf")
        assert "not installed" in r or "Docling not" in r


def test_agent_audits_tool_calls(tmp_path):
    from sick.agent import SickAgent

    agent = SickAgent(workspace=tmp_path)
    agent.write_file("a.txt", "hello")
    agent.bash("exit 3")
    entries = agent.audit.entries()
    assert entries[-2]["tool"] == "write_file" and entries[-2]["ok"]
    assert entries[-1]["tool"] == "bash" and not entries[-1]["ok"]
    assert agent._tool_counts["write_file"] == 1


def test_config_excluded_dirs_apply_to_tools(tmp_path):
    from sick.agent import SickAgent

    (tmp_path / ".sick").mkdir()
    (tmp_path / ".sick" / "config.toml").write_text('excluded = ["vendor"]\n')
    (tmp_path / "vendor").mkdir()
    (tmp_path / "vendor" / "x.py").write_text("hidden = 1")
    (tmp_path / "keep.py").write_text("visible = 1")
    agent = SickAgent(workspace=tmp_path)
    assert agent.glob("*.py") == ["keep.py"]


def test_load_config_defaults_and_bad_toml(tmp_path):
    from sick.config import SickConfig, load_config

    expected = SickConfig().model_dump()
    assert load_config(tmp_path) == expected
    (tmp_path / ".sick").mkdir()
    (tmp_path / ".sick" / "config.toml").write_text("not [valid toml")
    assert load_config(tmp_path) == expected


def test_git_checkpoint_and_restore(tmp_path, monkeypatch):
    import subprocess

    from sick.tools.git import Checkpoint, Restore

    monkeypatch.setenv("GIT_AUTHOR_NAME", "t")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "t@t")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "t")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "t@t")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "--allow-empty", "-m", "init", "-q"], cwd=tmp_path, check=True)

    cp = Checkpoint(tmp_path)
    assert "no changes" in cp.execute()
    (tmp_path / "a.txt").write_text("v1")
    assert cp.execute().startswith("checkpoint created")
    (tmp_path / "a.txt").write_text("v2")
    assert "restored" in Restore(tmp_path).execute()
    assert (tmp_path / "a.txt").read_text() == "v1"


def test_git_checkpoint_requires_repo(tmp_path):
    from sick.tools.git import Checkpoint, Restore

    assert "not a git repository" in Checkpoint(tmp_path).execute()
    assert "not a git repository" in Restore(tmp_path).execute()


def test_fetch_url_ok(monkeypatch):
    from sick.tools.web import FetchUrl

    class FakeResp:
        def __init__(self, data):
            self._data = data

        def read(self, n):
            return self._data

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    def fake_urlopen(req, timeout):
        assert req.full_url == "https://example.com/x"
        return FakeResp(b"<html>hi</html>")

    monkeypatch.setattr("sick.tools.web.urllib.request.urlopen", fake_urlopen)
    assert "hi" in FetchUrl().execute("https://example.com/x")


def test_fetch_url_rejects_non_http():
    from sick.tools.web import FetchUrl

    out = FetchUrl().execute("file:///etc/passwd")
    assert "only http/https" in out


def test_fetch_url_truncates_oversize(monkeypatch):
    from sick.tools.web import MAX_URL_BYTES, FetchUrl

    class FakeResp:
        def read(self, n):
            return b"x" * (MAX_URL_BYTES + 100)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    monkeypatch.setattr("sick.tools.web.urllib.request.urlopen", lambda req, timeout: FakeResp())
    out = FetchUrl().execute("https://example.com/big")
    assert "[truncated" in out


def test_bash_sandbox_requires_bwrap(monkeypatch, tmp_path):
    import shutil

    from sick.tools.exec import Bash

    monkeypatch.setattr(shutil, "which", lambda *a, **k: None)
    out = Bash(tmp_path, sandboxed=True).execute("echo hi")
    assert "bwrap is not installed" in out


def test_preflight_no_project(tmp_path):
    from sick.preflight import preflight

    report, ok = preflight(str(tmp_path))
    assert "import check: FAILED" in report
    assert ok is False
