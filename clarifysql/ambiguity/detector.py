import json
import re
from typing import Dict, List, Optional, Union
from clarifysql.ambiguity.models import (
    AmbiguityCheckResult,
    ClarificationOption,
    ClarificationResolution,
)
from clarifysql.ambiguity.prompts import (
    AMBIGUITY_SYSTEM_PROMPT,
    render_few_shot_block,
)
from clarifysql.schema.extractor import DatabaseSchema
from clarifysql.schema.semantic_layer import SemanticCatalog


class AmbiguityDetector:
    """
    Ambiguity Detection & Classification Engine (ADCE) and Clarification Dispatcher.
    Inspects queries, builds LLM prompts, parses classifications, and resolves user responses.
    """

    def __init__(self, catalog: SemanticCatalog, schema: DatabaseSchema):
        self.catalog = catalog
        self.schema = schema

    def build_classification_prompt(
        self,
        query: str,
        relevant_tables: Optional[List[str]] = None
    ) -> str:
        """Construct the prompt sent to the LLM to classify query ambiguity."""
        target_tables = relevant_tables if relevant_tables is not None else self.schema.table_names()
        ddl_summary = self.schema.to_ddl_summary(target_tables)
        metrics_summary = self.catalog.format_metrics_for_prompt()
        few_shots = render_few_shot_block()

        prompt = f"""{AMBIGUITY_SYSTEM_PROMPT}

{metrics_summary}

### Target Database Schema:
{ddl_summary}

{few_shots}

### Current User Query to Analyze:
User Query: "{query}"

Output the AmbiguityCheckResult JSON object now:"""
        return prompt.strip()

    def parse_classification_response(
        self,
        raw_output: Union[str, dict]
    ) -> AmbiguityCheckResult:
        """Parse structured output from the LLM into a validated AmbiguityCheckResult."""
        if isinstance(raw_output, dict):
            return AmbiguityCheckResult.model_validate(raw_output)

        cleaned = raw_output.strip()
        # Strip potential markdown fences
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```[a-zA-Z]*\n?", "", cleaned)
            cleaned = re.sub(r"\n?```$", "", cleaned)
        cleaned = cleaned.strip()

        # Find first { and last }
        start_idx = cleaned.find("{")
        end_idx = cleaned.rfind("}")
        if start_idx != -1 and end_idx != -1:
            json_str = cleaned[start_idx : end_idx + 1]
            data = json.loads(json_str)
            return AmbiguityCheckResult.model_validate(data)

        raise ValueError(f"Could not parse valid JSON from LLM output: {raw_output[:200]}")

    def resolve_clarification(
        self,
        check_result: AmbiguityCheckResult,
        user_choice: str
    ) -> ClarificationResolution:
        """
        Resolve user response via structured choice (e.g. 'A', '1') or free-text (REQ-ICDR-02).
        """
        choice_clean = user_choice.strip()
        choice_upper = choice_clean.upper()

        # Check by ID (e.g., 'A', 'B', 'C')
        option_map: Dict[str, ClarificationOption] = {
            opt.id.strip().upper(): opt for opt in check_result.options
        }

        # Check by 1-indexed number (e.g., '1', '2')
        num_map: Dict[str, ClarificationOption] = {
            str(idx + 1): opt for idx, opt in enumerate(check_result.options)
        }

        selected_opt: Optional[ClarificationOption] = None

        if choice_upper in option_map:
            selected_opt = option_map[choice_upper]
        elif choice_clean in num_map:
            selected_opt = num_map[choice_clean]

        if selected_opt:
            return ClarificationResolution(
                selected_option_id=selected_opt.id,
                resolved_instruction=f"{selected_opt.label}: {selected_opt.description}",
                implied_sql_logic=selected_opt.implied_sql_logic
            )

        # Free-text clarification
        return ClarificationResolution(
            custom_clarification=choice_clean,
            resolved_instruction=f"User clarified preference: {choice_clean}",
            implied_sql_logic=None
        )

    def build_augmented_prompt(
        self,
        original_query: str,
        resolution: Optional[ClarificationResolution] = None
    ) -> str:
        """
        Compile augmented, unambiguous prompt for SQL synthesis (REQ-ICDR-03).
        """
        if not resolution:
            return original_query

        parts = [
            f"User Goal: {original_query}",
            f"Clarified Business Requirement: {resolution.resolved_instruction}"
        ]
        if resolution.implied_sql_logic:
            parts.append(f"Specified Metric / Filter Logic: {resolution.implied_sql_logic}")

        return "\n".join(parts)
