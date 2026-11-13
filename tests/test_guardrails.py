from unittest.mock import MagicMock
import pytest
from clarifysql.generator.guardrails import (
    ASTGuardrail,
    SQLSecurityError,
    SQLSyntaxError,
)
from clarifysql.generator.sql_generator import SQLGenerator
from clarifysql.schema.extractor import SchemaExtractor
from clarifysql.schema.semantic_layer import load_semantic_catalog


@pytest.fixture
def guardrail():
    return ASTGuardrail()


@pytest.fixture
def catalog():
    return load_semantic_catalog("config/metrics.yaml")


@pytest.fixture
def schema(catalog):
    return SchemaExtractor.from_semantic_catalog(catalog).get_schema()


# --- Test Safe Read-Only Queries ---

def test_safe_simple_select(guardrail):
    sql = "SELECT id, name FROM customers WHERE signup_date >= '2024-01-01';"
    res = guardrail.validate_sql(sql)
    assert "SELECT" in res
    assert "customers" in res


def test_safe_joins_and_aggregation(guardrail):
    sql = """
    SELECT c.name, SUM(p.amount) AS total_spend
    FROM customers c
    JOIN orders o ON c.id = o.customer_id
    JOIN payments p ON o.id = p.order_id
    WHERE p.payment_status = 'successful'
    GROUP BY c.name
    ORDER BY total_spend DESC;
    """
    res = guardrail.validate_sql(sql)
    assert "JOIN" in res
    assert "GROUP BY" in res


def test_safe_cte_query(guardrail):
    sql = """
    WITH completed AS (
        SELECT customer_id, COUNT(*) AS order_count
        FROM orders
        WHERE status = 'completed'
        GROUP BY customer_id
    )
    SELECT c.name, comp.order_count
    FROM customers c
    JOIN completed comp ON c.id = comp.customer_id;
    """
    res = guardrail.validate_sql(sql)
    assert "WITH" in res
    assert "SELECT" in res


def test_safe_union_query(guardrail):
    sql = "SELECT id FROM orders UNION ALL SELECT id FROM payments;"
    res = guardrail.validate_sql(sql)
    assert "UNION" in res


def test_markdown_codeblock_cleaning(guardrail):
    raw = """```sql
    SELECT * FROM payments WHERE amount > 100;
    ```"""
    res = guardrail.validate_sql(raw)
    assert "payments" in res
    assert "amount > 100" in res


# --- Test Mutating & Malicious Queries (Must Be Blocked) ---

@pytest.mark.parametrize("dangerous_sql", [
    "DROP TABLE customers;",
    "DELETE FROM orders WHERE id = 1;",
    "UPDATE payments SET amount = 0;",
    "INSERT INTO customers (name, email) VALUES ('hacker', 'h@ck.er');",
    "ALTER TABLE orders ADD COLUMN back_door TEXT;",
    "TRUNCATE TABLE payments;",
    "CREATE TABLE evil (id INT);",
])
def test_blocked_mutating_statements(guardrail, dangerous_sql):
    with pytest.raises(SQLSecurityError):
        guardrail.validate_sql(dangerous_sql)


def test_blocked_multi_statement_injection(guardrail):
    sql = "SELECT * FROM customers; DROP TABLE orders;"
    with pytest.raises(SQLSecurityError, match="Multi-statement execution rejected"):
        guardrail.validate_sql(sql)


def test_blocked_mutating_cte(guardrail):
    # Data-modifying CTE attempting to delete inside a SELECT
    sql = """
    WITH deleted_orders AS (
        DELETE FROM orders WHERE status = 'cancelled'
        RETURNING id
    )
    SELECT * FROM deleted_orders;
    """
    with pytest.raises(SQLSecurityError, match="DELETE"):
        guardrail.validate_sql(sql)


def test_syntax_error_handling(guardrail):
    with pytest.raises(SQLSyntaxError):
        guardrail.validate_sql("SELECT FROM WHERE ;")

    with pytest.raises(SQLSyntaxError):
        guardrail.validate_sql("")


def test_is_safe_helper(guardrail):
    safe, err = guardrail.is_safe("SELECT COUNT(*) FROM orders;")
    assert safe is True
    assert err is None

    safe, err = guardrail.is_safe("DROP TABLE orders;")
    assert safe is False
    assert "DROP" in err


# --- Test SQLGenerator Integration ---

def test_sql_generator_prompt_and_generation(catalog, schema):
    mock_llm = MagicMock()
    mock_llm.generate.return_value = "SELECT id, name FROM customers;"

    generator = SQLGenerator(llm_client=mock_llm, catalog=catalog, schema=schema)
    prompt = generator.build_generation_prompt("Show all customers")
    assert "Target PostgreSQL Database Schema" in prompt
    assert "Original Request: Show all customers" in prompt

    sql = generator.generate_sql("Show all customers")
    assert sql == "SELECT id, name FROM customers"
    mock_llm.generate.assert_called_once()


def test_sql_generator_blocks_unsafe_llm_output(catalog, schema):
    mock_llm = MagicMock()
    # LLM hallucinates an unsafe mutating statement
    mock_llm.generate.return_value = "DELETE FROM customers;"

    generator = SQLGenerator(llm_client=mock_llm, catalog=catalog, schema=schema)
    with pytest.raises(SQLSecurityError):
        generator.generate_sql("Remove old customers")


def test_sql_generator_correction(catalog, schema):
    mock_llm = MagicMock()
    mock_llm.generate.return_value = "SELECT id, email FROM customers;"

    generator = SQLGenerator(llm_client=mock_llm, catalog=catalog, schema=schema)
    corrected = generator.correct_sql(
        original_query="Show emails",
        failed_sql="SELECT emails FROM customers;",
        error_message="column 'emails' does not exist"
    )
    assert corrected == "SELECT id, email FROM customers"
