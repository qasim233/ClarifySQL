from typing import List, Optional
from pydantic import BaseModel, Field
from clarifysql.ambiguity.detector import AmbiguityDetector
from clarifysql.ambiguity.models import (
    AmbiguityCheckResult,
    AmbiguityDimension,
    ClarificationResolution,
)
from clarifysql.execution.models import ExecutionResult
from clarifysql.execution.sandbox import SQLExecutionSandbox
from clarifysql.generator.sql_generator import SQLGenerator
from clarifysql.llm.base import BaseLLMClient
from clarifysql.schema.extractor import DatabaseSchema
from clarifysql.schema.retriever import BaseSchemaRetriever


class ClarifySQLResult(BaseModel):
    """Result of Pipeline B (ClarifySQL Active Ambiguity Resolution Pipeline)."""
    query: str
    relevant_tables: List[str] = Field(default_factory=list)
    is_ambiguous: bool = False
    ambiguity_type: Optional[AmbiguityDimension] = None
    ambiguity_check: Optional[AmbiguityCheckResult] = None
    resolution: Optional[ClarificationResolution] = None
    generated_sql: str = ""
    execution_result: Optional[ExecutionResult] = None
    needs_user_input: bool = False


class ClarifySQLPipeline:
    """
    Pipeline B: ClarifySQL Enterprise Text-to-SQL pipeline.
    Intercepts ambiguous queries, resolves business intent, and synthesizes safe SQL.
    """

    def __init__(
        self,
        llm_client: BaseLLMClient,
        detector: AmbiguityDetector,
        sql_generator: SQLGenerator,
        retriever: BaseSchemaRetriever,
        schema: DatabaseSchema,
        sandbox: SQLExecutionSandbox
    ):
        self.llm = llm_client
        self.detector = detector
        self.generator = sql_generator
        self.retriever = retriever
        self.schema = schema
        self.sandbox = sandbox

    def run(
        self,
        query: str,
        resolution_choice: Optional[str] = None
    ) -> ClarifySQLResult:
        """
        Execute the ClarifySQL pipeline.
        If query is ambiguous and resolution_choice is omitted, returns needs_user_input=True.
        """
        # 1. Retrieve relevant tables
        relevant_tables = self.retriever.retrieve_tables(query, self.schema)

        # 2. Check for ambiguity (ADCE)
        classification_prompt = self.detector.build_classification_prompt(
            query=query,
            relevant_tables=relevant_tables
        )
        ambiguity_res = self.llm.generate_structured(
            prompt=classification_prompt,
            response_model=AmbiguityCheckResult,
            temperature=0.0
        )

        # 3. Handle Ambiguous Queries
        if ambiguity_res.is_ambiguous:
            # If no choice provided, halt synthesis and request user input (REQ-ICDR-01)
            if resolution_choice is None:
                return ClarifySQLResult(
                    query=query,
                    relevant_tables=relevant_tables,
                    is_ambiguous=True,
                    ambiguity_type=ambiguity_res.ambiguity_type,
                    ambiguity_check=ambiguity_res,
                    needs_user_input=True
                )

            # Resolve user's selection (REQ-ICDR-02)
            resolution = self.detector.resolve_clarification(ambiguity_res, resolution_choice)

            # Synthesize unambiguous SQL (REQ-ICDR-03)
            try:
                sql = self.generator.generate_sql(
                    query=query,
                    clarified_instruction=resolution.resolved_instruction,
                    implied_sql=resolution.implied_sql_logic,
                    relevant_tables=relevant_tables
                )
            except Exception as gen_err:
                return ClarifySQLResult(
                    query=query,
                    relevant_tables=relevant_tables,
                    is_ambiguous=True,
                    ambiguity_type=ambiguity_res.ambiguity_type,
                    ambiguity_check=ambiguity_res,
                    resolution=resolution,
                    execution_result=ExecutionResult(
                        success=False,
                        error_message=f"SQL synthesis failed: {gen_err}"
                    )
                )

            # Execute in sandbox
            exec_res = self.sandbox.execute(
                sql=sql,
                sql_generator=self.generator,
                original_query=query,
                relevant_tables=relevant_tables
            )

            return ClarifySQLResult(
                query=query,
                relevant_tables=relevant_tables,
                is_ambiguous=True,
                ambiguity_type=ambiguity_res.ambiguity_type,
                ambiguity_check=ambiguity_res,
                resolution=resolution,
                generated_sql=sql,
                execution_result=exec_res,
                needs_user_input=False
            )

        # 4. Handle Unambiguous Queries directly
        try:
            sql = self.generator.generate_sql(
                query=query,
                clarified_instruction=None,
                implied_sql=None,
                relevant_tables=relevant_tables
            )
        except Exception as gen_err:
            return ClarifySQLResult(
                query=query,
                relevant_tables=relevant_tables,
                is_ambiguous=False,
                ambiguity_check=ambiguity_res,
                execution_result=ExecutionResult(
                    success=False,
                    error_message=f"SQL synthesis failed: {gen_err}"
                )
            )

        exec_res = self.sandbox.execute(
            sql=sql,
            sql_generator=self.generator,
            original_query=query,
            relevant_tables=relevant_tables
        )

        return ClarifySQLResult(
            query=query,
            relevant_tables=relevant_tables,
            is_ambiguous=False,
            ambiguity_check=ambiguity_res,
            generated_sql=sql,
            execution_result=exec_res,
            needs_user_input=False
        )
