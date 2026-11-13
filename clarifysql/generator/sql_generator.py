from typing import List, Optional
from clarifysql.generator.guardrails import ASTGuardrail
from clarifysql.llm.base import BaseLLMClient
from clarifysql.schema.extractor import DatabaseSchema
from clarifysql.schema.semantic_layer import SemanticCatalog


SQL_SYSTEM_PROMPT = """You are an expert PostgreSQL DBA and SQL synthesizer.

Your objective is to generate accurate, optimal, strictly read-only PostgreSQL queries targeting PostgreSQL 15+ standards.

### Strict Generation Rules:
1. READ-ONLY SELECT: Generate ONLY a single `SELECT` or `WITH ... SELECT` query. Never use INSERT, UPDATE, DELETE, DROP, ALTER, TRUNCATE, or CREATE.
2. DIALECT COMPLIANCE: Use standard PostgreSQL syntax (e.g. `DATE_TRUNC('month', ...)`, `CURRENT_DATE - INTERVAL '30 days'`, `COALESCE`, `NULLS LAST`).
3. JOIN INTEGRITY: Always use explicit INNER JOIN or LEFT JOIN with qualified table column names (e.g., `customers.id = orders.customer_id`).
4. CERTIFIED METRICS: When a certified business metric is mentioned, use its exact formula and filters as specified in the catalog.
5. CLEAN OUTPUT: Return ONLY the raw SQL query. Do NOT include markdown code blocks, explanations, backticks, or notes.
"""


class SQLGenerator:
    """
    Synthesizes and self-corrects PostgreSQL queries using schema context,
    certified business metrics, and AST guardrails.
    """

    def __init__(
        self,
        llm_client: BaseLLMClient,
        catalog: SemanticCatalog,
        schema: DatabaseSchema,
        guardrail: Optional[ASTGuardrail] = None
    ):
        self.llm = llm_client
        self.catalog = catalog
        self.schema = schema
        self.guardrail = guardrail or ASTGuardrail()

    def build_generation_prompt(
        self,
        query: str,
        clarified_instruction: Optional[str] = None,
        implied_sql: Optional[str] = None,
        relevant_tables: Optional[List[str]] = None
    ) -> str:
        target_tables = relevant_tables if relevant_tables is not None else self.schema.table_names()
        ddl_summary = self.schema.to_ddl_summary(target_tables)
        metrics_summary = self.catalog.format_metrics_for_prompt()

        parts = [
            metrics_summary,
            "\n### Target PostgreSQL Database Schema:",
            ddl_summary,
            "\n### User Request Details:",
            f"Original Request: {query}"
        ]

        if clarified_instruction:
            parts.append(f"Clarified Business Requirement: {clarified_instruction}")
        if implied_sql:
            parts.append(f"Prescribed SQL Metric/Condition: {implied_sql}")

        parts.append("\nGenerate the PostgreSQL SELECT query now:")
        return "\n".join(parts)

    def generate_sql(
        self,
        query: str,
        clarified_instruction: Optional[str] = None,
        implied_sql: Optional[str] = None,
        relevant_tables: Optional[List[str]] = None
    ) -> str:
        prompt = self.build_generation_prompt(
            query=query,
            clarified_instruction=clarified_instruction,
            implied_sql=implied_sql,
            relevant_tables=relevant_tables
        )
        raw_sql = self.llm.generate(prompt=prompt, system_prompt=SQL_SYSTEM_PROMPT, temperature=0.0)
        # Validate through AST guardrail to guarantee read-only compliance
        validated_sql = self.guardrail.validate_sql(raw_sql)
        return validated_sql

    def correct_sql(
        self,
        original_query: str,
        failed_sql: str,
        error_message: str,
        relevant_tables: Optional[List[str]] = None
    ) -> str:
        target_tables = relevant_tables if relevant_tables is not None else self.schema.table_names()
        ddl_summary = self.schema.to_ddl_summary(target_tables)

        prompt = f"""### Database Schema:
{ddl_summary}

### Problem:
The following SQL query was generated for the user's request, but execution failed with a PostgreSQL error.

User Request: {original_query}
Failed SQL Query:
{failed_sql}

PostgreSQL Error Message:
{error_message}

Fix the SQL query to resolve the error while answering the user's request. Output ONLY the corrected PostgreSQL SELECT query."""

        raw_corrected = self.llm.generate(prompt=prompt, system_prompt=SQL_SYSTEM_PROMPT, temperature=0.0)
        return self.guardrail.validate_sql(raw_corrected)
