from typing import Any, List, Optional
from pydantic import BaseModel, Field


class ExecutionResult(BaseModel):
    """Encapsulates the structured output and diagnostics of a query execution (REQ-SGES-03)."""
    success: bool
    columns: List[str] = Field(default_factory=list)
    rows: List[List[Any]] = Field(default_factory=list)
    row_count: int = 0
    truncated: bool = False
    execution_time_ms: float = 0.0
    error_message: Optional[str] = None
    retry_count: int = 0
    executed_sql: str = ""
