from unittest.mock import MagicMock, patch
import psycopg2
import pytest
from clarifysql.execution.models import ExecutionResult
from clarifysql.execution.sandbox import SQLExecutionSandbox


def test_execution_result_model():
    res = ExecutionResult(
        success=True,
        columns=["id", "name"],
        rows=[[1, "Alice"], [2, "Bob"]],
        row_count=2,
        execution_time_ms=12.5,
        executed_sql="SELECT id, name FROM customers"
    )
    assert res.success is True
    assert res.row_count == 2
    assert res.truncated is False
    assert res.columns == ["id", "name"]


def test_missing_db_url():
    sandbox = SQLExecutionSandbox(connection_url=None)
    res = sandbox.execute("SELECT 1;")
    assert res.success is False
    assert "Database connection URL is not configured" in res.error_message


def test_pre_execution_guardrail_rejection():
    mock_connect = MagicMock()
    with patch("psycopg2.connect", mock_connect):
        sandbox = SQLExecutionSandbox(connection_url="postgresql://test:test@localhost:5432/test")
        res = sandbox.execute("DROP TABLE customers;")
        assert res.success is False
        assert "Guardrail violation" in res.error_message
        # Asserts DB connection was never even attempted
        mock_connect.assert_not_called()


def test_successful_sandboxed_execution():
    mock_cursor = MagicMock()
    mock_cursor.description = [("id",), ("name",)]
    mock_cursor.fetchmany.return_value = [[1, "Alice"], [2, "Bob"]]

    mock_conn = MagicMock()
    mock_conn.__enter__.return_value = mock_conn
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    with patch("psycopg2.connect", return_value=mock_conn):
        sandbox = SQLExecutionSandbox(
            connection_url="postgresql://test:test@localhost:5432/test",
            timeout_ms=5000,
            max_rows=100
        )
        res = sandbox.execute("SELECT id, name FROM customers;")

        assert res.success is True
        assert res.columns == ["id", "name"]
        assert len(res.rows) == 2
        assert res.row_count == 2
        assert res.truncated is False

        # Verify read-only and statement timeout setup
        mock_cursor.execute.assert_any_call("SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY;")
        mock_cursor.execute.assert_any_call("SET statement_timeout = 5000;")


def test_row_truncation():
    # Simulate database returning 101 rows when limit is 100
    fake_rows = [[i, f"User_{i}"] for i in range(101)]

    mock_cursor = MagicMock()
    mock_cursor.description = [("id",), ("name",)]
    mock_cursor.fetchmany.return_value = fake_rows

    mock_conn = MagicMock()
    mock_conn.__enter__.return_value = mock_conn
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    with patch("psycopg2.connect", return_value=mock_conn):
        sandbox = SQLExecutionSandbox(
            connection_url="postgresql://test:test@localhost:5432/test",
            max_rows=100
        )
        res = sandbox.execute("SELECT id, name FROM customers;")

        assert res.success is True
        assert len(res.rows) == 100
        assert res.row_count == 100
        assert res.truncated is True


def test_self_correction_retry_loop_success():
    mock_generator = MagicMock()
    mock_generator.correct_sql.return_value = "SELECT id, name FROM customers"

    # First attempt fails with ProgrammingError, second attempt succeeds
    mock_cursor_fail = MagicMock()
    mock_cursor_fail.execute.side_effect = [
        None,  # SET SESSION
        None,  # SET timeout
        psycopg2.ProgrammingError("column 'bad_col' does not exist")
    ]

    mock_cursor_success = MagicMock()
    mock_cursor_success.description = [("id",), ("name",)]
    mock_cursor_success.fetchmany.return_value = [[1, "Alice"]]

    mock_conn_fail = MagicMock()
    mock_conn_fail.__enter__.return_value = mock_conn_fail
    mock_conn_fail.cursor.return_value.__enter__.return_value = mock_cursor_fail

    mock_conn_success = MagicMock()
    mock_conn_success.__enter__.return_value = mock_conn_success
    mock_conn_success.cursor.return_value.__enter__.return_value = mock_cursor_success

    with patch("psycopg2.connect", side_effect=[mock_conn_fail, mock_conn_success]):
        sandbox = SQLExecutionSandbox(
            connection_url="postgresql://test:test@localhost:5432/test",
            max_retries=2
        )
        res = sandbox.execute(
            sql="SELECT id, bad_col FROM customers",
            sql_generator=mock_generator,
            original_query="Show customers"
        )

        assert res.success is True
        assert res.retry_count == 1
        assert res.rows == [[1, "Alice"]]
        mock_generator.correct_sql.assert_called_once()


def test_retry_exhaustion():
    mock_generator = MagicMock()
    mock_generator.correct_sql.return_value = "SELECT id FROM customers"

    mock_cursor_fail = MagicMock()
    mock_cursor_fail.execute.side_effect = [
        None, None, psycopg2.ProgrammingError("syntax error")
    ] * 3

    mock_conn = MagicMock()
    mock_conn.__enter__.return_value = mock_conn
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor_fail

    with patch("psycopg2.connect", return_value=mock_conn):
        sandbox = SQLExecutionSandbox(
            connection_url="postgresql://test:test@localhost:5432/test",
            max_retries=2
        )
        res = sandbox.execute(
            sql="SELECT syntax error",
            sql_generator=mock_generator,
            original_query="Test query"
        )

        assert res.success is False
        assert res.retry_count == 2
        assert "syntax error" in res.error_message
        assert mock_generator.correct_sql.call_count == 2
