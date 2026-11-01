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

    for k in ("NVIDIA_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GROQ_API_KEY", "SICK_MODEL", "SICK_PROVIDER", "SICK_BASE_URL"):
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
    # SICK_MODEL is cleared on provider save: a stale model from another
    # provider must not leak into the new provider's client
    assert "SICK_MODEL" not in text
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


def test_detect_groq_explicit_and_defaults(monkeypatch):
    from sick.providers import GROQ_BASE_URL, GROQ_MODEL, Groq

    monkeypatch.setenv("GROQ_API_KEY", "gsk-test")
    monkeypatch.setenv("SICK_PROVIDER", "groq")
    monkeypatch.setenv("NVIDIA_API_KEY", "nv-test")
    p = detect()
    assert isinstance(p, Groq)
    assert p.name == "groq"
    assert p.model_id == GROQ_MODEL == "openai/gpt-oss-120b"
    assert p.base_url == GROQ_BASE_URL == "https://api.groq.com/openai/v1"


def test_groq_retired_models_migrate_automatically():
    from sick.providers import Groq

    # Groq shut this down 2026-08-16 (free/developer); saved configs heal
    assert Groq("llama-3.3-70b-versatile").model_id == "openai/gpt-oss-120b"
    assert Groq("groq/llama-3.3-70b-versatile").model_id == "openai/gpt-oss-120b"
    assert Groq("llama-3.1-8b-instant").model_id == "openai/gpt-oss-20b"
    # current models pass through untouched
    assert Groq("openai/gpt-oss-120b").model_id == "openai/gpt-oss-120b"
    assert Groq("moonshotai/kimi-k2-instruct-0905").model_id == "moonshotai/kimi-k2-instruct-0905"


def test_groq_create_llm_uses_groq_key_and_base(monkeypatch):
    import sick.providers as providers

    captured = {}

    def fake_get(model, **kwargs):
        captured["model"] = model
        captured.update(kwargs)
        return "llm"

    monkeypatch.setattr(providers, "get_llm_client", fake_get)
    monkeypatch.setenv("GROQ_API_KEY", "gsk-secret")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    out = providers.Groq().create_llm()
    assert out == "llm"
    assert captured["api_key"] == "gsk-secret"
    assert captured["api_base"] == "https://api.groq.com/openai/v1"
    # native litellm Groq routing (bare names take the OpenAI-compatible
    # path, which forwards OpenAI-only params Groq rejects)
    assert captured["model"] == "groq/openai/gpt-oss-120b"
    # NOOA injects prompt_cache_key on every call; Groq must strip it
    assert captured["additional_drop_params"] == ["prompt_cache_key"]
    # fail fast: an oversized request must not retry for minutes in silence
    retry = captured["retry_config"]
    assert retry.max_retries == 1 and retry.rate_limit_extra_retries == 0


def test_groq_client_config_strips_prompt_cache_key(monkeypatch):
    """Real client construction: groq/ model + drop config, no network."""
    from sick.providers import Groq

    monkeypatch.setenv("GROQ_API_KEY", "gsk-fake")
    llm = Groq().create_llm()
    assert llm.model == "groq/openai/gpt-oss-120b"
    assert llm.config["additional_drop_params"] == ["prompt_cache_key"]


def test_prompt_cache_key_dropped_from_groq_params():
    """Transform-level proof (no network, no valid key needed)."""
    from litellm.utils import get_optional_params

    optional = get_optional_params(
        model="groq/openai/gpt-oss-120b",
        custom_llm_provider="groq",
        prompt_cache_key="agent-1-CodeActStrategy",
        additional_drop_params=["prompt_cache_key"],
    )
    assert "prompt_cache_key" not in optional


def test_save_groq_clears_stale_base_url(tmp_path):
    from sick.providers import save_provider_config

    env_file = tmp_path / ".env"
    env_file.write_text("OPENAI_API_KEY=old\nSICK_BASE_URL=https://old.example/v1\nSICK_MODEL=gpt-4o-mini\n")
    save_provider_config(env_file, "groq", "gsk-new")
    text = env_file.read_text()
    assert "GROQ_API_KEY=gsk-new" in text
    assert "SICK_PROVIDER=groq" in text
    assert "SICK_BASE_URL" not in text
    assert "SICK_MODEL" not in text
    assert "OPENAI_API_KEY=old" in text  # other providers' keys preserved


def test_prompt_wizard_selects_groq(tmp_path):
    from sick.providers import prompt_for_api_key

    env_file = tmp_path / ".env"
    ok = prompt_for_api_key(env_file, input_fn=lambda _p: "4", secret_fn=lambda _p: "gsk-wiz")
    assert ok is True
    text = env_file.read_text()
    assert "GROQ_API_KEY=gsk-wiz" in text and "SICK_PROVIDER=groq" in text


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
