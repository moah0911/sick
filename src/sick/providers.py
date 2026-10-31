import getpass
import os
import sys
from abc import ABC, abstractmethod
from pathlib import Path

from dotenv import load_dotenv
from nooa.unifiedllm import UnifiedLLM
from nooa.unifiedllm.registry import get_llm_client

# provider name -> env var holding its API key (wizard + /connect share this)
PROVIDER_KEYS = {
    "nvidia": "NVIDIA_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
}
_PROVIDER_MENU = [
    ("nvidia", "NVIDIA NIM — get a key at https://build.nvidia.com"),
    ("anthropic", "Anthropic — get a key at https://console.anthropic.com"),
    ("openai", "OpenAI / OpenAI-compatible — get a key at https://platform.openai.com"),
]

_ENV_KEYS = (
    "NVIDIA_API_KEY",
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
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


def save_api_key(env_path: str | Path, provider: str, key: str) -> Path:
    """Idempotently store one provider key (+ SICK_PROVIDER) in a .env file.

    Creates the file (mode 600) when missing, preserves other entries, and
    exports both values into this process so startup can continue at once.
    """
    if provider not in PROVIDER_KEYS:
        raise ValueError(f"unknown provider: {provider}")
    path = Path(env_path)
    lines = path.read_text().splitlines() if path.exists() else []
    lines = _upsert_env(lines, PROVIDER_KEYS[provider], key)
    lines = _upsert_env(lines, "SICK_PROVIDER", provider)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    os.environ[PROVIDER_KEYS[provider]] = key
    os.environ["SICK_PROVIDER"] = provider
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
    elif choice in ("2", "3"):
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
    save_api_key(env_path, provider, key)
    print(f"saved to {env_path} (only you can read it). Starting sick…", file=out)
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

    def __init__(self, model: str = "gpt-4o-mini", base_url: str | None = None):
        self._model = model
        self._base_url = base_url

    @property
    def model_id(self) -> str:
        return self._model

    def create_llm(self) -> UnifiedLLM:
        key = os.environ.get("OPENAI_API_KEY")
        if not key:
            raise ValueError("OPENAI_API_KEY not set")
        kwargs: dict = {"api_key": key, "timeout": 60}
        if self._base_url:
            kwargs["api_base"] = self._base_url.rstrip("/")
        return get_llm_client(self._model, **kwargs)


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

    # explicit override
    if provider_override == "nvidia" and os.environ.get("NVIDIA_API_KEY"):
        return NVIDIA(model or "nvidia/llama-3.1-8b-instruct")
    if provider_override == "anthropic" and os.environ.get("ANTHROPIC_API_KEY"):
        return Anthropic(model or "claude-sonnet-4-20250514")
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

    raise ValueError(
        "No LLM provider detected. Set one of:\n"
        "  NVIDIA_API_KEY\n"
        "  ANTHROPIC_API_KEY\n"
        "  OPENAI_API_KEY\n"
        "Or set SICK_MODEL + SICK_BASE_URL + OPENAI_API_KEY for custom endpoints."
    )
