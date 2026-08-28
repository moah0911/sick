"""CLI tests: arg parsing and preflight wiring."""

def test_preflight_returns_tuple(tmp_path):
    from sick.preflight import preflight

    report, ok = preflight(str(tmp_path))
    assert isinstance(report, str)
    assert isinstance(ok, bool)


def test_load_config_malformed_ignored(tmp_path):
    # covered but ensure bad excluded type ignored
    from sick.config import load_config

    (tmp_path / ".sick").mkdir()
    (tmp_path / ".sick" / "config.toml").write_text('excluded = "notalist"\n')
    cfg = load_config(tmp_path)
    assert cfg["excluded"] == []


def test_cli_help_shows(monkeypatch):
    import subprocess, sys

    r = subprocess.run([sys.executable, "-m", "sick.cli", "--help"], capture_output=True, text=True, cwd="/home/mahtwog/sick")
    assert "usage" in r.stdout.lower() or "sick" in r.stdout.lower()
