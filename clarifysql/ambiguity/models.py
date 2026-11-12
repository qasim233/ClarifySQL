from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field, model_validator


class AmbiguityDimension(str, Enum):
    """The four core dimensions of business ambiguity defined in REQ-ADCE-02."""
    METRIC = "METRIC"                      # Subjective metrics ("best", "top", "active", "churned")
    TEMPORAL = "TEMPORAL"                  # Ambiguous timestamp references (order_date vs payment_date)
    SCHEMA_ENTITY = "SCHEMA_ENTITY"        # Multiple interpretations of entity/column (orders vs payments)
    GRANULARITY = "GRANULARITY"            # Aggregation level (summary vs transaction line-item)


class ClarificationOption(BaseModel):
    """A single mutually exclusive business interpretation presented to the user."""
    id: str = Field(description="Structured identifier, e.g., 'A', 'B', 'C', 'D'")
    label: str = Field(description="Plain English summary of the option")
    description: str = Field(description="Detailed business explanation without raw SQL syntax")
    implied_sql_logic: str = Field(description="Explicit underlying SQL formula or filter for generation")


class AmbiguityCheckResult(BaseModel):
    """Pydantic model representing structured output from ambiguity classification (REQ-ADCE-03)."""
    is_ambiguous: bool = Field(
        description="True if query is underspecified, subjective, or has multiple interpretations; False if explicit."
    )
    ambiguity_type: Optional[AmbiguityDimension] = Field(
        default=None,
        description="Dimension of ambiguity when is_ambiguous=True"
    )
    explanation: Optional[str] = Field(
        default=None,
        description="Plain business English explanation of what is ambiguous and why clarification is needed"
    )
    options: List[ClarificationOption] = Field(
        default_factory=list,
        description="Between 2 and 4 distinct, mutually exclusive business interpretations"
    )

    @model_validator(mode="after")
    def validate_ambiguity_consistency(self) -> "AmbiguityCheckResult":
        if self.is_ambiguous:
            if not self.ambiguity_type:
                raise ValueError("ambiguity_type must be provided when is_ambiguous is True")
            if not self.explanation or not self.explanation.strip():
                raise ValueError("explanation must be provided when is_ambiguous is True")
            if len(self.options) < 2 or len(self.options) > 4:
                raise ValueError(
                    f"Ambiguous query must provide between 2 and 4 options, got {len(self.options)}"
                )
            option_ids = [opt.id.strip().upper() for opt in self.options]
            if len(option_ids) != len(set(option_ids)):
                raise ValueError("Option IDs must be unique (e.g., A, B, C)")
        else:
            # If not ambiguous, options must be empty
            self.options = []
            self.ambiguity_type = None
        return self


class ClarificationResolution(BaseModel):
    """The outcome of user resolving an ambiguity (REQ-ICDR-02, REQ-ICDR-03)."""
    selected_option_id: Optional[str] = None
    custom_clarification: Optional[str] = None
    resolved_instruction: str = Field(description="Unambiguous instruction for prompt augmentation")
    implied_sql_logic: Optional[str] = Field(
        default=None,
        description="Specific SQL formula / condition chosen"
    )
