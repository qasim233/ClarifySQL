import json
from typing import Optional, Type, TypeVar
from groq import Groq
from pydantic import BaseModel
from clarifysql.llm.base import BaseLLMClient
from config.settings import settings

T = TypeVar("T", bound=BaseModel)


class GroqClient(BaseLLMClient):
    """
    LLM client for cloud inference via Groq.
    Targets production-speed structured inference using llama-3.3-70b-versatile.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None
    ):
        self.api_key = api_key or settings.groq_api_key
        self.model = model or settings.groq_model
        self._client: Optional[Groq] = None

    def _get_client(self) -> Groq:
        if not self.api_key:
            raise ValueError(
                "GROQ_API_KEY is required to use the Groq provider. "
                "Please configure GROQ_API_KEY in your .env file or pass it to GroqClient."
            )
        if self._client is None:
            self._client = Groq(api_key=self.api_key)
        return self._client

    def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.0
    ) -> str:
        client = self._get_client()
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        response = client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature
        )
        choice = response.choices[0]
        return (choice.message.content or "").strip()

    def generate_structured(
        self,
        prompt: str,
        response_model: Type[T],
        system_prompt: Optional[str] = None,
        temperature: float = 0.0
    ) -> T:
        client = self._get_client()
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

        response = client.chat.completions.create(
            model=self.model,
            messages=messages,
            response_format={"type": "json_object"},
            temperature=temperature
        )
        choice = response.choices[0]
        raw_content = choice.message.content or "{}"
        return response_model.model_validate_json(raw_content)
