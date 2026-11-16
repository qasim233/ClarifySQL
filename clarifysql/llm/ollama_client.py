import json
import re
from typing import Optional, Type, TypeVar
import httpx
from pydantic import BaseModel
from clarifysql.llm.base import BaseLLMClient
from config.settings import settings

T = TypeVar("T", bound=BaseModel)


class OllamaClient(BaseLLMClient):
    """
    LLM client for local inference via Ollama.
    Optimized for GPU environments (e.g., RTX 3070 8GB VRAM) using models like llama3.1:8b or qwen2.5-coder:7b.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout_seconds: Optional[float] = None
    ):
        self.base_url = (base_url or settings.ollama_base_url).rstrip("/")
        self.model = model or settings.ollama_model
        self.timeout_seconds = timeout_seconds if timeout_seconds is not None else settings.ollama_timeout_seconds

    def _get_client(self) -> httpx.Client:
        # Generous read timeout allowing local GPU to load model into VRAM
        timeout = httpx.Timeout(timeout=self.timeout_seconds, connect=15.0)
        return httpx.Client(base_url=self.base_url, timeout=timeout)

    def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.0
    ) -> str:
        """Send chat completion request to Ollama and return text output."""
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": temperature}
        }

        try:
            with self._get_client() as client:
                resp = client.post("/api/chat", json=payload)
                resp.raise_for_status()
                data = resp.json()
                return data.get("message", {}).get("content", "").strip()
        except httpx.TimeoutException as err:
            raise RuntimeError(
                f"Ollama request timed out after {int(self.timeout_seconds)}s waiting for model '{self.model}'.\n"
                f"Tips:\n"
                f"1. Pre-warm the model in GPU memory: Open a terminal and run 'ollama run {self.model}'.\n"
                f"2. You can increase timeout in .env: OLLAMA_TIMEOUT_SECONDS=600"
            ) from err
        except httpx.ConnectError as err:
            raise RuntimeError(
                f"Cannot connect to Ollama at '{self.base_url}'. "
                f"Ensure Ollama daemon is running ('ollama serve') and model '{self.model}' is available."
            ) from err
        except httpx.HTTPStatusError as err:
            raise RuntimeError(
                f"Ollama returned HTTP error {err.response.status_code}: {err.response.text}"
            ) from err

    def generate_structured(
        self,
        prompt: str,
        response_model: Type[T],
        system_prompt: Optional[str] = None,
        temperature: float = 0.0
    ) -> T:
        """
        Request structured JSON output from Ollama and validate with Pydantic.
        Uses format="json" for fast, reliable token generation without GBNF grammar freeze.
        """
        schema = response_model.model_json_schema()
        schema_instruction = (
            f"You must respond with a single valid JSON object strictly conforming to this schema:\n"
            f"{json.dumps(schema)}"
        )
        combined_system = (
            f"{system_prompt}\n\n{schema_instruction}" if system_prompt else schema_instruction
        )

        messages = [
            {"role": "system", "content": combined_system},
            {"role": "user", "content": prompt}
        ]

        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "format": "json",  # Fast and reliable JSON mode across all Ollama versions
            "options": {"temperature": temperature}
        }

        try:
            with self._get_client() as client:
                resp = client.post("/api/chat", json=payload)
                resp.raise_for_status()
                data = resp.json()
                raw_content = data.get("message", {}).get("content", "").strip()

                # Clean markdown fences if model outputs ```json ... ```
                if raw_content.startswith("```"):
                    raw_content = re.sub(r"^```[a-zA-Z]*\n?", "", raw_content)
                    raw_content = re.sub(r"\n?```$", "", raw_content).strip()

                return response_model.model_validate_json(raw_content)
        except httpx.TimeoutException as err:
            raise RuntimeError(
                f"Ollama request timed out after {int(self.timeout_seconds)}s waiting for model '{self.model}'.\n"
                f"Tips:\n"
                f"1. Pre-warm the model in GPU memory: Open a terminal and run 'ollama run {self.model}'.\n"
                f"2. You can increase timeout in .env: OLLAMA_TIMEOUT_SECONDS=600"
            ) from err
        except httpx.ConnectError as err:
            raise RuntimeError(
                f"Cannot connect to Ollama at '{self.base_url}'. "
                f"Ensure Ollama daemon is running and model '{self.model}' is pulled."
            ) from err
        except httpx.HTTPStatusError as err:
            raise RuntimeError(
                f"Ollama returned HTTP error {err.response.status_code}: {err.response.text}"
            ) from err
