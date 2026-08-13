import os
from abc import ABC, abstractmethod
from dotenv import load_dotenv
from nooa.unifiedllm import UnifiedLLM
from nooa.unifiedllm.registry import get_llm_client

load_dotenv(override=True)


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
        return get_llm_client(
            f"nvidia_nim/{self._model}",
            api_key=os.environ["NVIDIA_API_KEY"],
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
        kwargs = {"api_key": os.environ.get("OPENAI_API_KEY")}
        if self._base_url:
            kwargs["api_base"] = self._base_url
        return get_llm_client(self._model, **kwargs)


class Anthropic(LLMProvider):
    name = "anthropic"

    def __init__(self, model: str = "claude-sonnet-4-20250514"):
        self._model = model

    @property
    def model_id(self) -> str:
        return self._model

    def create_llm(self) -> UnifiedLLM:
        return get_llm_client(self._model, api_key=os.environ["ANTHROPIC_API_KEY"])


def detect(model: str | None = None) -> LLMProvider:
    if model is None:
        model = os.environ.get("SICK_MODEL")
    base_url = os.environ.get("SICK_BASE_URL")

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
