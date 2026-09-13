import os
from abc import ABC, abstractmethod

from dotenv import load_dotenv
from nooa.unifiedllm import UnifiedLLM
from nooa.unifiedllm.registry import get_llm_client


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
