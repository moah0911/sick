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
