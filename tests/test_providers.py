"""Tests for providers: detection, validation, prefix."""

from sick.providers import NVIDIA, Anthropic, OpenAICompatible, detect


def test_detect_nvidia_priority(monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", "nv-test")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("SICK_MODEL", raising=False)
    monkeypatch.delenv("SICK_PROVIDER", raising=False)
    p = detect()
    assert isinstance(p, NVIDIA)


def test_detect_override_via_provider(monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", "nv-test")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("SICK_PROVIDER", "openai")
    p = detect()
    assert isinstance(p, OpenAICompatible)


def test_detect_model_prefix_infers_provider(monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", "nv-test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "anth-test")
    monkeypatch.delenv("SICK_PROVIDER", raising=False)
    p = detect(model="claude-sonnet-4-20250514")
    assert isinstance(p, Anthropic)


def test_detect_raises_when_no_keys(monkeypatch):
    import pytest

    for k in ("NVIDIA_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "SICK_MODEL", "SICK_PROVIDER"):
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(ValueError, match="No LLM provider"):
        detect()


def test_create_llm_validates_missing_key(monkeypatch):
    import pytest

    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    with pytest.raises(ValueError):
        NVIDIA().create_llm()


def test_save_api_key_upserts_and_protects(tmp_path, monkeypatch):
    import os
    import stat

    from sick.providers import detect, save_api_key

    env_file = tmp_path / ".env"
    env_file.write_text("NVIDIA_API_KEY=\nSICK_MODEL=my-model\n")
    save_api_key(env_file, "anthropic", "test-key-123")
    text = env_file.read_text()
    assert "ANTHROPIC_API_KEY=test-key-123" in text
    assert "SICK_MODEL=my-model" in text  # other entries preserved
    assert "SICK_PROVIDER=anthropic" in text
    assert stat.S_IMODE(os.stat(env_file).st_mode) == 0o600
    # saving again replaces, never duplicates
    save_api_key(env_file, "anthropic", "test-key-456")
    assert env_file.read_text().count("ANTHROPIC_API_KEY=") == 1
    assert "test-key-456" in env_file.read_text()
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-456")
    assert isinstance(detect(), Anthropic)


def test_prompt_for_api_key_wizard(tmp_path, monkeypatch):
    from sick.providers import prompt_for_api_key

    env_file = tmp_path / ".env"
    answers = iter(["2"])
    ok = prompt_for_api_key(
        env_file,
        input_fn=lambda _prompt: next(answers),
        secret_fn=lambda _prompt: "  wizard-key  ",
    )
    assert ok is True
    assert "ANTHROPIC_API_KEY=wizard-key" in env_file.read_text()


def test_prompt_for_api_key_skips_cleanly(tmp_path):
    from sick.providers import prompt_for_api_key

    env_file = tmp_path / ".env"
    # empty key -> skipped, nothing written
    assert prompt_for_api_key(env_file, input_fn=lambda _p: "", secret_fn=lambda _p: "  ") is False
    assert not env_file.exists()
    # unknown provider choice -> skipped
    assert prompt_for_api_key(env_file, input_fn=lambda _p: "9", secret_fn=lambda _p: "k") is False
    assert not env_file.exists()

    # Ctrl-C / EOF at the first question -> skipped, no traceback
    def _eof(_prompt):
        raise EOFError

    assert prompt_for_api_key(env_file, input_fn=_eof, secret_fn=lambda _p: "k") is False


def test_cli_without_key_noninteractive_exits_friendly(tmp_path):
    import os
    import subprocess
    import sys

    env = {k: v for k, v in os.environ.items() if "API_KEY" not in k and not k.startswith("SICK_")}
    env["PATH"] = os.environ.get("PATH", "")
    r = subprocess.run(
        [sys.executable, "-m", "sick.cli", "hello"],
        capture_output=True, text=True, cwd=tmp_path, env=env, input="",
        timeout=60,
    )
    assert r.returncode == 2
    assert "No LLM provider" in r.stderr or "no API key" in r.stderr
    assert "Traceback" not in r.stderr
