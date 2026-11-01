import getpass
import os
import sys
from abc import ABC, abstractmethod
from pathlib import Path

from dotenv import load_dotenv
from nooa.unifiedllm import UnifiedLLM
from nooa.unifiedllm.registry import get_llm_client

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
# Groq shut down llama-3.3-70b-versatile for free/developer tiers on
# 2026-08-16; openai/gpt-oss-120b is Groq's recommended replacement
# (131k context, native tool calling).
GROQ_MODEL = "openai/gpt-oss-120b"
# Retired Groq model IDs -> supported replacements. Saved configs naming
# a retired model are migrated automatically instead of failing turns
# with model_not_found after a provider-side shutdown.
GROQ_RETIRED_MODELS = {
    "llama-3.3-70b-versatile": "openai/gpt-oss-120b",
    "llama-3.1-70b-versatile": "openai/gpt-oss-120b",
    "llama3-groq-70b-8192-tool-use-preview": "openai/gpt-oss-120b",
    "llama-3.1-8b-instant": "openai/gpt-oss-20b",
}

# provider name -> env var holding its API key (wizard + /connect share this)
PROVIDER_KEYS = {
    "nvidia": "NVIDIA_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "groq": "GROQ_API_KEY",
}
_PROVIDER_MENU = [
    ("nvidia", "NVIDIA NIM — get a key at https://build.nvidia.com"),
    ("anthropic", "Anthropic — get a key at https://console.anthropic.com"),
    ("openai", "OpenAI / OpenAI-compatible — get a key at https://platform.openai.com"),
    ("groq", "Groq — fast OpenAI-compatible inference at https://console.groq.com"),
]

_ENV_KEYS = (
    "NVIDIA_API_KEY",
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "GROQ_API_KEY",
    "SICK_MODEL",
    "SICK_BASE_URL",
    "SICK_PROVIDER",
    "SICK_MEMORY_DIR",
    "SICK_REMOTION_DIR",
    "SICK_SANDBOX",
)


def load_env(path=None) -> None:
    """Load a .env file without letting empty placeholders shadow real values.

    `load_dotenv(override=False)` keeps the first value seen — including "".
    Empty means unset here, so drop empties after each load.
    """
    if path is None:
        load_dotenv(override=False)
    else:
        load_dotenv(path, override=False)
    for key in _ENV_KEYS:
        if not os.environ.get(key):
            os.environ.pop(key, None)


load_env()


def _upsert_env(lines: list[str], var: str, value: str) -> list[str]:
    for i, line in enumerate(lines):
        if line.strip().startswith(f"{var}="):
            lines[i] = f"{var}={value}"
            return lines
    lines.append(f"{var}={value}")
    return lines


def _remove_env(lines: list[str], var: str) -> list[str]:
    return [line for line in lines if not line.strip().startswith(f"{var}=")]


def _write_env(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")
    try:
        path.chmod(0o600)
    except OSError:
        pass


def save_provider_config(
    env_path: str | Path,
    provider: str,
    key: str,
    base_url: str | None = None,
    model: str | None = None,
) -> Path:
    """Store a provider key + selection in .env, clearing stale endpoint/model.

    Switching providers must not inherit the previous provider's
    SICK_BASE_URL/SICK_MODEL (the classic "switched but still calling the
    old endpoint" trap), so both are removed unless explicitly given.
    Other providers' keys are preserved so /connect can switch back.
    """
    if provider not in PROVIDER_KEYS:
        raise ValueError(f"unknown provider: {provider}")
    path = Path(env_path)
    lines = path.read_text().splitlines() if path.exists() else []
    lines = _upsert_env(lines, PROVIDER_KEYS[provider], key)
    lines = _upsert_env(lines, "SICK_PROVIDER", provider)
    for var, value in (("SICK_BASE_URL", base_url), ("SICK_MODEL", model)):
        if value:
            lines = _upsert_env(lines, var, value)
            os.environ[var] = value
        else:
            lines = _remove_env(lines, var)
            os.environ.pop(var, None)
    _write_env(path, lines)
    os.environ[PROVIDER_KEYS[provider]] = key
    os.environ["SICK_PROVIDER"] = provider
    return path


def save_api_key(env_path: str | Path, provider: str, key: str) -> Path:
    """Idempotently store one provider key (+ SICK_PROVIDER) in a .env file."""
    return save_provider_config(env_path, provider, key)


def set_active_provider(env_path: str | Path, provider: str) -> Path:
    """Switch SICK_PROVIDER to an already-saved provider (no key needed)."""
    if provider not in PROVIDER_KEYS:
        raise ValueError(f"unknown provider: {provider}")
    path = Path(env_path)
    lines = path.read_text().splitlines() if path.exists() else []
    lines = _upsert_env(lines, "SICK_PROVIDER", provider)
    # stale endpoint/model from another provider must not leak across a switch
    lines = _remove_env(lines, "SICK_BASE_URL")
    lines = _remove_env(lines, "SICK_MODEL")
    _write_env(path, lines)
    os.environ["SICK_PROVIDER"] = provider
    os.environ.pop("SICK_BASE_URL", None)
    os.environ.pop("SICK_MODEL", None)
    return path


def prompt_for_api_key(env_path: str | Path, input_fn=input, secret_fn=None) -> bool:
    """First-run wizard: choose a provider, paste its key (hidden), save it.

    Returns True when a key was saved. Never echoes the key. Safe to call
    only on an interactive terminal — the caller checks `isatty()`.
    """
    if secret_fn is None:
        secret_fn = getpass.getpass
    out = sys.stderr
    print("\nsick needs an LLM API key to start — let's set one up (one time).", file=out)
    print("Step 1 of 2 — choose your provider:", file=out)
    for i, (_, label) in enumerate(_PROVIDER_MENU, 1):
        print(f"  {i}. {label}", file=out)
    try:
        choice = input_fn("Provider [1]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print("\nsetup skipped — set a key in .env when you're ready.", file=out)
        return False
    names = [name for name, _ in _PROVIDER_MENU]
    if choice in ("", "1"):
        provider = names[0]
    elif choice.isdigit() and 1 <= int(choice) <= len(names):
        provider = names[int(choice) - 1]
    elif choice in names:
        provider = choice
    else:
        print(f"unknown choice {choice!r} — setup skipped.", file=out)
        return False
    print(f"Step 2 of 2 — paste your {provider} API key (input stays hidden).", file=out)
    try:
        key = secret_fn("API key: ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\nsetup skipped — set a key in .env when you're ready.", file=out)
        return False
    if not key:
        print("no key entered — setup skipped.", file=out)
        return False
    base_url: str | None = None
    model: str | None = None
    if provider == "openai":
        try:
            base_url = input_fn("Base URL [blank = OpenAI default]: ").strip() or None
            model = input_fn("Model [blank = gpt-4o-mini]: ").strip() or None
        except (EOFError, KeyboardInterrupt):
            print("\nsetup skipped — set a key in .env when you're ready.", file=out)
            return False
    save_provider_config(env_path, provider, key, base_url=base_url, model=model)
    detail = f" (model: {GROQ_MODEL}, endpoint: {GROQ_BASE_URL})" if provider == "groq" else ""
    print(f"saved {provider} to {env_path} (only you can read it){detail}. Starting sick…", file=out)
    print("note: *_API_KEY vars exported in your shell override .env — unset stale ones if sick picks the wrong provider.", file=out)
    return True


class LLMProvider(ABC):
    name: str

    @property
    @abstractmethod
    def model_id(self) -> str: ...

    @abstractmethod
    def create_llm(self) -> UnifiedLLM: ...


class NVIDIA(LLMProvider):
    name = "nvidia"

    def __init__(self, model: str = "nvidia/llama-3.1-8b-instruct"):
        self._model = model

    @property
    def model_id(self) -> str:
        return self._model

    def create_llm(self) -> UnifiedLLM:
        key = os.environ.get("NVIDIA_API_KEY")
        if not key:
            raise ValueError("NVIDIA_API_KEY not set")
        return get_llm_client(
            f"nvidia_nim/{self._model}",
            api_key=key,
            timeout=60,
        )


class OpenAICompatible(LLMProvider):
    name = "openai"
    key_env = "OPENAI_API_KEY"

    def __init__(self, model: str = "gpt-4o-mini", base_url: str | None = None):
        self._model = model
        self._base_url = base_url
        self._key_fallback: str | None = None

    @property
    def model_id(self) -> str:
        return self._model

    @property
    def base_url(self) -> str | None:
        return self._base_url

    def _client_model(self) -> str:
        return self._model

    def _extra_client_kwargs(self) -> dict:
        return {}

    def create_llm(self) -> UnifiedLLM:
        key = os.environ.get(self.key_env) or self._key_fallback
        if not key:
            raise ValueError(f"{self.key_env} not set")
        kwargs: dict = {"api_key": key, "timeout": 60, **self._extra_client_kwargs()}
        if self._base_url:
            kwargs["api_base"] = self._base_url.rstrip("/")
        return get_llm_client(self._client_model(), **kwargs)


class Groq(OpenAICompatible):
    """Groq's OpenAI-compatible API with its own key, endpoint, and model."""

    name = "groq"
    key_env = "GROQ_API_KEY"

    def __init__(self, model: str = GROQ_MODEL, base_url: str | None = GROQ_BASE_URL):
        model = model or GROQ_MODEL
        bare = model.removeprefix("groq/")
        model = GROQ_RETIRED_MODELS.get(bare, model)
        super().__init__(model, base_url or GROQ_BASE_URL)

    def _client_model(self) -> str:
        # Route via litellm's native Groq provider, not the generic
        # OpenAI-compatible endpoint path (which forwards OpenAI-only
        # params such as prompt_cache_key that Groq's API rejects).
        return self._model if self._model.startswith("groq/") else f"groq/{self._model}"

    def _extra_client_kwargs(self) -> dict:
        # NOOA's actor injects prompt_cache_key on every call for OpenAI
        # prompt caching; Groq rejects it as an unsupported property.
        # additional_drop_params is forwarded by get_llm_client to every
        # litellm completion, stripping it before the request is built.
        return {"additional_drop_params": ["prompt_cache_key"]}


class Anthropic(LLMProvider):
    name = "anthropic"

    def __init__(self, model: str = "claude-sonnet-4-20250514"):
        self._model = model

    @property
    def model_id(self) -> str:
        return self._model

    def create_llm(self) -> UnifiedLLM:
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise ValueError("ANTHROPIC_API_KEY not set")
        return get_llm_client(self._model, api_key=key, timeout=60)


def detect(model: str | None = None) -> LLMProvider:
    if model is None:
        model = os.environ.get("SICK_MODEL")
    base_url = os.environ.get("SICK_BASE_URL")
    provider_override = os.environ.get("SICK_PROVIDER", "").lower()

    def _model_matches(prefixes: list[str]) -> bool:
        if not model:
            return False
        ml = model.lower()
        return any(ml.startswith(p) for p in prefixes)

    # legacy Groq config: OpenAI key + Groq endpoint via SICK_BASE_URL
    if base_url and "groq.com" in base_url and provider_override not in ("nvidia", "anthropic"):
        if os.environ.get("GROQ_API_KEY") or os.environ.get("OPENAI_API_KEY"):
            groq = Groq(model or GROQ_MODEL)
            if not os.environ.get("GROQ_API_KEY"):
                groq._key_fallback = os.environ.get("OPENAI_API_KEY")
            return groq

    # explicit override
    if provider_override == "nvidia" and os.environ.get("NVIDIA_API_KEY"):
        return NVIDIA(model or "nvidia/llama-3.1-8b-instruct")
    if provider_override == "anthropic" and os.environ.get("ANTHROPIC_API_KEY"):
        return Anthropic(model or "claude-sonnet-4-20250514")
    if provider_override == "groq" and os.environ.get("GROQ_API_KEY"):
        return Groq(model or GROQ_MODEL)
    if provider_override in ("openai", "openai_compatible") and os.environ.get("OPENAI_API_KEY"):
        return OpenAICompatible(model or "gpt-4o-mini", base_url)

    # infer from model prefix if set
    if _model_matches(["nvidia"]):
        if os.environ.get("NVIDIA_API_KEY"):
            return NVIDIA(model or "nvidia/llama-3.1-8b-instruct")
    if _model_matches(["claude"]):
        if os.environ.get("ANTHROPIC_API_KEY"):
            return Anthropic(model or "claude-sonnet-4-20250514")
    if _model_matches(["gpt", "o1", "o3"]):
        if os.environ.get("OPENAI_API_KEY"):
            return OpenAICompatible(model or "gpt-4o-mini", base_url)

    if os.environ.get("NVIDIA_API_KEY"):
        return NVIDIA(model or "nvidia/llama-3.1-8b-instruct")

    if os.environ.get("ANTHROPIC_API_KEY"):
        return Anthropic(model or "claude-sonnet-4-20250514")

    if os.environ.get("OPENAI_API_KEY"):
        return OpenAICompatible(model or "gpt-4o-mini", base_url)

    if os.environ.get("GROQ_API_KEY"):
        return Groq(model or GROQ_MODEL)

    raise ValueError(
        "No LLM provider detected. Set one of:\n"
        "  NVIDIA_API_KEY\n"
        "  ANTHROPIC_API_KEY\n"
        "  OPENAI_API_KEY\n"
        "  GROQ_API_KEY\n"
        "Or set SICK_MODEL + SICK_BASE_URL + OPENAI_API_KEY for custom endpoints."
    )
