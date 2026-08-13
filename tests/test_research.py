"""Tests for the code research index."""
import tempfile
from pathlib import Path

from sick.tools.research import CodeIndex, CodeResearch


def _make_repo() -> Path:
    d = Path(tempfile.mkdtemp())
    (d / "auth.py").write_text(
        "def authenticate(token):\n"
        "    \"\"\"Validate a session token.\"\"\"\n"
        "    return token == 'secret'\n"
        "\n"
        "def login(user, password):\n"
        "    return user\n"
    )
    (d / "payments.py").write_text(
        "def charge_card(card, amount):\n"
        "    return amount\n"
    )
    (d / "notes.md").write_text(
        "# README\n\nhow to run the tests\n"
    )
    return d


def test_index_builds_ast_chunks():
    idx = CodeIndex(str(_make_repo()))
    n = idx.build()
    names = {c.name for c in idx.chunks}
    assert "authenticate" in names
    assert "login" in names
    assert "charge_card" in names
    assert n >= 4


def test_search_ranks_name_hits_first():
    idx = CodeIndex(str(_make_repo()))
    idx.build()
    hits = idx.search("token validation")
    assert hits, "expected hits"
    assert hits[0].chunk.name == "authenticate"


def test_research_returns_paths():
    idx = CodeIndex(str(_make_repo()))
    idx.build()
    out = idx.research("charge card payment")
    assert "payments.py" in out
    assert "charge_card" in out
    assert ":1" in out


def test_research_no_match():
    idx = CodeIndex(str(_make_repo()))
    idx.build()
    out = idx.research("zzzz_qqqq")
    assert out.startswith("no matching code")


def test_index_cache_reuse_and_invalidation():
    d = _make_repo()
    a = CodeIndex(str(d))
    a.build()
    cached = CodeIndex(str(d))
    assert cached.build() == a.build()
    (d / "auth.py").write_text("def authenticate(token):\n    return True\n")
    changed = CodeIndex(str(d))
    changed.build()
    assert len(changed.chunks) < len(a.chunks)
    assert (d / ".sick" / "indexes" / "code-index.json").is_file()


def test_code_research_tool_execute():
    tool = CodeResearch(str(_make_repo()))
    out = tool.execute("how does login work")
    assert "auth.py" in out


def test_code_research_skips_hidden_and_venv():
    d = _make_repo()
    (d / ".venv").mkdir()
    (d / ".venv" / "junk.py").write_text("def hidden_thing():\n    pass\n")
    (d / "__pycache__").mkdir()
    (d / "__pycache__" / "junk.py").write_text("def hidden_thing():\n    pass\n")
    idx = CodeIndex(str(d))
    idx.build()
    assert not any("hidden_thing" in c.name or "junk" in c.path for c in idx.chunks)
