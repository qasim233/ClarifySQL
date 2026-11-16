from typing import List, Optional
from pydantic import BaseModel, Field
from clarifysql.execution.models import ExecutionResult
from clarifysql.execution.sandbox import SQLExecutionSandbox
from clarifysql.generator.sql_generator import SQLGenerator
from clarifysql.schema.extractor import DatabaseSchema
from clarifysql.schema.retriever import BaseSchemaRetriever
from clarifysql.schema.semantic_layer import SemanticCatalog


class DirectPipelineResult(BaseModel):
    """Result of Pipeline A (Baseline Direct Text-to-SQL without Ambiguity Resolution)."""
    query: str
    relevant_tables: List[str] = Field(default_factory=list)
    generated_sql: str = ""
    execution_result: Optional[ExecutionResult] = None


class DirectPipeline:
    """
    Pipeline A: Naive Text-to-SQL pipeline.
    Synthesizes SQL directly from the user query without ambiguity checks.
    """

    def __init__(
        self,
        sql_generator: SQLGenerator,
        retriever: BaseSchemaRetriever,
        schema: DatabaseSchema,
        sandbox: SQLExecutionSandbox
    ):
        self.generator = sql_generator
        self.retriever = retriever
        self.schema = schema
        self.sandbox = sandbox

    def run(self, query: str) -> DirectPipelineResult:
        # 1. Retrieve tables (lexical / hybrid)
        relevant_tables = self.retriever.retrieve_tables(query, self.schema)

        # 2. Directly generate SQL without clarification
        try:
            sql = self.generator.generate_sql(
                query=query,
                clarified_instruction=None,
                implied_sql=None,
                relevant_tables=relevant_tables
            )
        except Exception as gen_err:
            return DirectPipelineResult(
                query=query,
                relevant_tables=relevant_tables,
                generated_sql="",
                execution_result=ExecutionResult(
                    success=False,
                    error_message=f"Direct SQL generation failed: {gen_err}"
                )
            )

        # 3. Execute in sandbox
        exec_res = self.sandbox.execute(
            sql=sql,
            sql_generator=self.generator,
            original_query=query,
            relevant_tables=relevant_tables
        )

        return DirectPipelineResult(
            query=query,
            relevant_tables=relevant_tables,
            generated_sql=sql,
            execution_result=exec_res
        )
