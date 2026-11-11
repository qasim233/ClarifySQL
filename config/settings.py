from typing import Literal, Optional
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    """Application settings for ClarifySQL."""
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # Supabase / PostgreSQL Database Connection
    database_url: Optional[str] = Field(
        default=None,
        description="PostgreSQL connection string (e.g., Supabase direct or pooler URI)"
    )

    # LLM Provider Configuration
    llm_provider: Literal["ollama", "groq"] = Field(
        default="ollama",
        description="Active LLM provider: 'ollama' for local GPU or 'groq' for production"
    )

    # Ollama settings (Local testing)
    ollama_base_url: str = Field(
        default="http://localhost:11434",
        description="Base URL for local Ollama daemon"
    )
    ollama_model: str = Field(
        default="llama3.1:8b",
        description="Ollama model tag suitable for 8GB VRAM (e.g. llama3.1:8b, qwen2.5-coder:7b)"
    )

    # Groq settings (Production)
    groq_api_key: Optional[str] = Field(
        default=None,
        description="API key for Groq Cloud inference"
    )
    groq_model: str = Field(
        default="llama-3.3-70b-versatile",
        description="Groq model ID"
    )

    # Safety & Execution Sandbox Settings
    statement_timeout_ms: int = Field(
        default=10000,
        description="Maximum SQL execution statement timeout in milliseconds (10s cap)"
    )
    max_result_rows: int = Field(
        default=500,
        description="Maximum rows returned by SQL queries before truncation"
    )
    max_correction_retries: int = Field(
        default=2,
        description="Maximum self-correction retries when a SQL query encounters a runtime error"
    )

    # Semantic Layer Configuration (supports YAML or JSON)
    semantic_metrics_path: str = Field(
        default="config/metrics.yaml",
        description="Path to semantic metrics catalog file (.yaml, .yml, or .json)"
    )


settings = Settings()
