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
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    r = subprocess.run([sys.executable, "-m", "sick.cli", "--help"], capture_output=True, text=True, cwd=root)
    assert "usage" in r.stdout.lower() or "sick" in r.stdout.lower()


def test_config_command_and_tracing_fields(tmp_path):
    from sick.config import load_config

    (tmp_path / ".sick").mkdir()
    (tmp_path / ".sick" / "config.toml").write_text(
        'tracing = true\n[command.review]\ntemplate = "Review $ARGUMENTS"\ndescription = "review it"\n'
    )
    cfg = load_config(tmp_path)
    assert cfg["tracing"] is True
    assert cfg["command"]["review"]["template"] == "Review $ARGUMENTS"


def test_config_commands_become_prompt_commands(tmp_path):
    from sick.tui.commands import SlashCommandRegistry

    (tmp_path / ".sick").mkdir()
    (tmp_path / ".sick" / "config.toml").write_text(
        '[command.hello]\ntemplate = "Say hi to $ARGUMENTS"\ndescription = "greet"\n'
    )
    reg = SlashCommandRegistry(workspace=tmp_path)
    assert "hello" in reg.commands


def test_templates_list_and_render(tmp_path):
    from sick.templates import list_templates, render_template

    assert set(list_templates()) >= {"fastapi", "cli", "remotion"}
    out = render_template("cli", tmp_path / "mycli")
    assert (tmp_path / "mycli" / "pyproject.toml").is_file()
    assert "mycli" in (tmp_path / "mycli" / "pyproject.toml").read_text() or out


def test_cli_version_and_list_templates():
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    r = subprocess.run(
        [sys.executable, "-m", "sick.cli", "--version"], capture_output=True, text=True, cwd=root
    )
    assert r.stdout.strip()
    r = subprocess.run(
        [sys.executable, "-m", "sick.cli", "--list-templates"], capture_output=True, text=True, cwd=root
    )
    assert "fastapi" in r.stdout


def test_lsp_uri_to_path_posix_and_windows_shapes():
    from pathlib import Path

    from sick.lsp.server import _uri_to_path

    assert _uri_to_path("file:///home/u/proj/a.py") == Path("/home/u/proj/a.py")
    win = _uri_to_path("file:///C:/Users/x/proj/a.py")
    assert win.name == "a.py" and "Users" in str(win)
    assert _uri_to_path("plain/relative.py") == Path("plain/relative.py")


def test_logging_configure_json_and_console(monkeypatch):
    from sick.logging_conf import configure_logging

    monkeypatch.setenv("SICK_LOG_FORMAT", "json")
    configure_logging()
    monkeypatch.setenv("SICK_LOG_FORMAT", "console")
    configure_logging()
