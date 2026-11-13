import re
from typing import Optional, Set, Tuple, Type
import sqlglot
from sqlglot import exp


class SQLSecurityError(Exception):
    """Raised when generated SQL contains mutating or prohibited operations."""
    pass


class SQLSyntaxError(Exception):
    """Raised when generated SQL cannot be parsed as valid PostgreSQL."""
    pass


# Disallowed AST expression types that modify state, structure, or permissions
DISALLOWED_EXPRESSION_TYPES: Set[Type[exp.Expression]] = {
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Drop,
    exp.Alter,
    exp.Create,
    exp.TruncateTable,
    exp.Command,
    exp.Pragma,
    exp.Grant,
    exp.Revoke,
}


class ASTGuardrail:
    """
    AST-level SQL guardrail powered by sqlglot (REQ-SGES-02).
    Enforces that queries are strictly read-only SELECT statements targeting PostgreSQL dialect.
    """

    def clean_sql(self, sql: str) -> str:
        """Strip markdown fences, leading/trailing whitespace, and semicolons."""
        cleaned = sql.strip()
        # Remove markdown code blocks (```sql ... ``` or ``` ...)
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```[a-zA-Z]*\n?", "", cleaned)
            cleaned = re.sub(r"\n?```$", "", cleaned)
        cleaned = cleaned.strip()
        # Strip trailing semicolons for consistent single-statement parsing
        cleaned = re.sub(r";+\s*$", "", cleaned)
        return cleaned

    def validate_sql(self, sql: str) -> str:
        """
        Parse and validate SQL AST.
        Returns the formatted PostgreSQL query if valid, or raises SQLSecurityError / SQLSyntaxError.
        """
        cleaned_sql = self.clean_sql(sql)
        if not cleaned_sql:
            raise SQLSyntaxError("Generated SQL is empty.")

        # 1. Parse into AST targeting PostgreSQL dialect
        try:
            parsed_statements = sqlglot.parse(cleaned_sql, read="postgres")
        except sqlglot.errors.ParseError as err:
            raise SQLSyntaxError(f"PostgreSQL syntax parsing failed: {err}") from err

        if not parsed_statements:
            raise SQLSyntaxError("No executable SQL statements found.")

        # 2. Hard check: Strict single-statement constraint (blocks multi-statement injection)
        if len(parsed_statements) > 1:
            raise SQLSecurityError(
                f"Multi-statement execution rejected ({len(parsed_statements)} statements found). "
                "Only a single read-only query is permitted."
            )

        root = parsed_statements[0]
        if root is None:
            raise SQLSyntaxError("Parsed statement is null.")

        # 3. Verify root expression is a read-only query (Select, Union, or CTE wrapping Select/Union)
        is_select_or_union = isinstance(root, (exp.Select, exp.Union))
        if not is_select_or_union:
            raise SQLSecurityError(
                f"Non-read-only root statement type detected: {root.key.upper()}. "
                "Only SELECT or UNION queries are permitted."
            )

        # 4. Deep AST scan: Ensure NO nested node contains mutating expressions
        # This catches data-modifying CTEs, e.g.: WITH del AS (DELETE FROM ...) SELECT ...
        for node in root.walk():
            node_type = type(node)
            for disallowed in DISALLOWED_EXPRESSION_TYPES:
                if issubclass(node_type, disallowed):
                    raise SQLSecurityError(
                        f"Prohibited operation '{disallowed.__name__.upper()}' detected in query AST."
                    )

        # 5. Transpile back into formatted PostgreSQL SQL
        return root.sql(dialect="postgres")

    def is_safe(self, sql: str) -> Tuple[bool, Optional[str]]:
        """Convenience method returning (is_safe, error_message)."""
        try:
            self.validate_sql(sql)
            return True, None
        except (SQLSecurityError, SQLSyntaxError) as err:
            return False, str(err)
