import re
import time
from typing import List, Optional
import psycopg2
from clarifysql.execution.models import ExecutionResult
from clarifysql.generator.guardrails import ASTGuardrail, SQLSecurityError, SQLSyntaxError
from clarifysql.generator.sql_generator import SQLGenerator
from config.settings import settings


class SQLExecutionSandbox:
    """
    Sandboxed PostgreSQL execution environment (REQ-SGES-03, REQ-SGES-04).
    Enforces read-only sessions, 10-second timeouts, 500-row caps, and self-correction retries.
    """

    def __init__(
        self,
        connection_url: Optional[str] = None,
        timeout_ms: Optional[int] = None,
        max_rows: Optional[int] = None,
        max_retries: Optional[int] = None,
        guardrail: Optional[ASTGuardrail] = None
    ):
        self.connection_url = connection_url or settings.database_url
        self.timeout_ms = timeout_ms if timeout_ms is not None else settings.statement_timeout_ms
        self.max_rows = max_rows if max_rows is not None else settings.max_result_rows
        self.max_retries = max_retries if max_retries is not None else settings.max_correction_retries
        self.guardrail = guardrail or ASTGuardrail()

    def _sanitize_error(self, error_str: str) -> str:
        """Strip sensitive credentials or connection URIs from error traces."""
        sanitized = re.sub(r"://[^@]+@", "://***:***@", error_str)
        return sanitized.strip()

    def _execute_single(self, sql: str) -> ExecutionResult:
        """Execute a single query in a read-only sandboxed connection."""
        if not self.connection_url:
            return ExecutionResult(
                success=False,
                error_message="Database connection URL is not configured.",
                executed_sql=sql
            )

        start_time = time.perf_counter()

        try:
            with psycopg2.connect(self.connection_url) as conn:
                with conn.cursor() as cur:
                    # Enforce strict read-only session characteristics
                    cur.execute("SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY;")
                    # Enforce statement execution timeout
                    cur.execute(f"SET statement_timeout = {int(self.timeout_ms)};")

                    cur.execute(sql)

                    # Determine columns
                    columns = [desc[0] for desc in cur.description] if cur.description else []

                    # Fetch rows up to max_rows + 1 to detect truncation
                    raw_rows = cur.fetchmany(self.max_rows + 1)
                    truncated = len(raw_rows) > self.max_rows
                    rows = [list(r) for r in raw_rows[:self.max_rows]]

                    duration_ms = (time.perf_counter() - start_time) * 1000.0

                    return ExecutionResult(
                        success=True,
                        columns=columns,
                        rows=rows,
                        row_count=len(rows),
                        truncated=truncated,
                        execution_time_ms=round(duration_ms, 2),
                        executed_sql=sql
                    )

        except (psycopg2.Error, Exception) as err:
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            return ExecutionResult(
                success=False,
                error_message=self._sanitize_error(str(err)),
                execution_time_ms=round(duration_ms, 2),
                executed_sql=sql
            )

    def execute(
        self,
        sql: str,
        sql_generator: Optional[SQLGenerator] = None,
        original_query: Optional[str] = None,
        relevant_tables: Optional[List[str]] = None
    ) -> ExecutionResult:
        """
        Execute SQL query with AST guardrails and automatic self-correction loop (max 2 retries).
        """
        current_sql = sql
        retry_count = 0

        while True:
            # 1. Pre-execution AST guardrail verification
            try:
                current_sql = self.guardrail.validate_sql(current_sql)
            except (SQLSecurityError, SQLSyntaxError) as guardrail_err:
                # If guardrail fails and self-correction is available, attempt correction
                if sql_generator and original_query and retry_count < self.max_retries:
                    retry_count += 1
                    current_sql = sql_generator.correct_sql(
                        original_query=original_query,
                        failed_sql=current_sql,
                        error_message=str(guardrail_err),
                        relevant_tables=relevant_tables
                    )
                    continue

                return ExecutionResult(
                    success=False,
                    error_message=f"Guardrail violation: {guardrail_err}",
                    retry_count=retry_count,
                    executed_sql=current_sql
                )

            # 2. Execute on database
            res = self._execute_single(current_sql)
            res.retry_count = retry_count

            # If successful, return immediately
            if res.success:
                return res

            # 3. Handle execution error with self-correction loop
            if sql_generator and original_query and retry_count < self.max_retries:
                retry_count += 1
                try:
                    current_sql = sql_generator.correct_sql(
                        original_query=original_query,
                        failed_sql=current_sql,
                        error_message=res.error_message or "Execution failed",
                        relevant_tables=relevant_tables
                    )
                    continue
                except Exception as corr_err:
                    res.error_message = (
                        f"{res.error_message} | Self-correction failed: {corr_err}"
                    )
                    return res

            # Retries exhausted or no generator provided
            return res
