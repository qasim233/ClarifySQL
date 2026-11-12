from typing import Optional
from clarifysql.llm.base import BaseLLMClient
from clarifysql.llm.ollama_client import OllamaClient
from clarifysql.llm.groq_client import GroqClient
from config.settings import settings


def get_llm_client(
    provider: Optional[str] = None,
    model: Optional[str] = None,
    **kwargs
) -> BaseLLMClient:
    """
    Factory function to retrieve configured LLM provider client.
    Supports 'ollama' (local GPU testing) and 'groq' (production).
    """
    active_provider = (provider or settings.llm_provider).lower().strip()

    if active_provider == "ollama":
        return OllamaClient(
            model=model or settings.ollama_model,
            base_url=kwargs.get("base_url") or settings.ollama_base_url,
            timeout_seconds=kwargs.get("timeout_seconds", 60.0)
        )
    elif active_provider == "groq":
        return GroqClient(
            model=model or settings.groq_model,
            api_key=kwargs.get("api_key") or settings.groq_api_key
        )
    else:
        raise ValueError(
            f"Unsupported LLM provider '{active_provider}'. Supported options: 'ollama', 'groq'."
        )
