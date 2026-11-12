import json
from unittest.mock import MagicMock, patch
import httpx
import pytest
from pydantic import BaseModel
from clarifysql.ambiguity.models import AmbiguityCheckResult, AmbiguityDimension, ClarificationOption
from clarifysql.llm.base import BaseLLMClient
from clarifysql.llm.factory import get_llm_client
from clarifysql.llm.groq_client import GroqClient
from clarifysql.llm.ollama_client import OllamaClient


class DummyModel(BaseModel):
    name: str
    score: int


def test_factory_selection():
    ollama = get_llm_client("ollama")
    assert isinstance(ollama, OllamaClient)
    assert isinstance(ollama, BaseLLMClient)

    groq = get_llm_client("groq")
    assert isinstance(groq, GroqClient)
    assert isinstance(groq, BaseLLMClient)

    with pytest.raises(ValueError, match="Unsupported LLM provider"):
        get_llm_client("openai_unsupported")


def test_ollama_generate_text():
    client = OllamaClient(base_url="http://mock-ollama:11434", model="llama3.1:8b")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "message": {"content": "SELECT * FROM customers;"}
    }

    with patch("httpx.Client.post", return_value=mock_resp) as mock_post:
        result = client.generate("Write SQL query", system_prompt="You are a SQL writer")
        assert result == "SELECT * FROM customers;"
        mock_post.assert_called_once()


def test_ollama_generate_structured():
    client = OllamaClient(base_url="http://mock-ollama:11434", model="llama3.1:8b")

    expected_data = {
        "is_ambiguous": True,
        "ambiguity_type": "METRIC",
        "explanation": "Subjective term 'best'",
        "options": [
            {
                "id": "A",
                "label": "By Spend",
                "description": "Total spend",
                "implied_sql_logic": "SUM(payments.amount)"
            },
            {
                "id": "B",
                "label": "By Count",
                "description": "Order count",
                "implied_sql_logic": "COUNT(orders.id)"
            }
        ]
    }

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "message": {"content": json.dumps(expected_data)}
    }

    with patch("httpx.Client.post", return_value=mock_resp):
        res = client.generate_structured("Check ambiguity", AmbiguityCheckResult)
        assert isinstance(res, AmbiguityCheckResult)
        assert res.is_ambiguous is True
        assert res.ambiguity_type == AmbiguityDimension.METRIC
        assert len(res.options) == 2


def test_ollama_connection_error():
    client = OllamaClient(base_url="http://localhost:11434")

    with patch("httpx.Client.post", side_effect=httpx.ConnectError("Connection refused")):
        with pytest.raises(RuntimeError, match="Cannot connect to Ollama"):
            client.generate("Hello")


def test_groq_missing_api_key():
    client = GroqClient(api_key=None)
    with pytest.raises(ValueError, match="GROQ_API_KEY is required"):
        client.generate("Hello")


def test_groq_generate_text():
    client = GroqClient(api_key="mock_key", model="llama-3.3-70b-versatile")

    mock_choice = MagicMock()
    mock_choice.message.content = "SELECT COUNT(*) FROM orders;"
    mock_completion = MagicMock()
    mock_completion.choices = [mock_choice]

    with patch.object(client, "_get_client") as mock_get_client:
        mock_groq_instance = MagicMock()
        mock_groq_instance.chat.completions.create.return_value = mock_completion
        mock_get_client.return_value = mock_groq_instance

        res = client.generate("Count orders")
        assert res == "SELECT COUNT(*) FROM orders;"


def test_groq_generate_structured():
    client = GroqClient(api_key="mock_key", model="llama-3.3-70b-versatile")

    dummy_json = json.dumps({"name": "Test Query", "score": 95})
    mock_choice = MagicMock()
    mock_choice.message.content = dummy_json
    mock_completion = MagicMock()
    mock_completion.choices = [mock_choice]

    with patch.object(client, "_get_client") as mock_get_client:
        mock_groq_instance = MagicMock()
        mock_groq_instance.chat.completions.create.return_value = mock_completion
        mock_get_client.return_value = mock_groq_instance

        res = client.generate_structured("Get score", DummyModel)
        assert isinstance(res, DummyModel)
        assert res.name == "Test Query"
        assert res.score == 95
