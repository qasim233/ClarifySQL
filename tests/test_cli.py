from unittest.mock import MagicMock, patch
import pytest
from typer.testing import CliRunner
from clarifysql.ambiguity.models import (
    AmbiguityCheckResult,
    AmbiguityDimension,
    ClarificationOption,
)
from clarifysql.cli.app import app
from clarifysql.execution.models import ExecutionResult

runner = CliRunner()


def test_cli_help():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "ClarifySQL" in result.output
    assert "ask" in result.output
    assert "compare" in result.output
    assert "benchmark" in result.output
    assert "schema" in result.output


def test_cli_schema():
    result = runner.invoke(app, ["schema"])
    assert result.exit_code == 0
    assert "Target Database Schema" in result.output
    assert "CREATE TABLE customers" in result.output
    assert "Certified Metrics Catalog" in result.output
    assert "Gross Revenue" in result.output


def test_cli_ask_unambiguous():
    mock_llm = MagicMock()
    mock_llm.generate_structured.return_value = AmbiguityCheckResult(is_ambiguous=False)
    mock_llm.generate.return_value = "SELECT COUNT(*) FROM customers;"

    mock_sandbox = MagicMock()
    mock_sandbox.execute.return_value = ExecutionResult(
        success=True,
        columns=["count"],
        rows=[[10]],
        row_count=1,
        execution_time_ms=8.5,
        executed_sql="SELECT COUNT(*) FROM customers"
    )

    with patch("clarifysql.cli.app.get_llm_client", return_value=mock_llm), \
         patch("clarifysql.cli.app.SQLExecutionSandbox", return_value=mock_sandbox):

        result = runner.invoke(app, ["ask", "Count all customers"])
        assert result.exit_code == 0
        assert "Generated PostgreSQL Query" in result.output
        assert "SELECT COUNT(*) FROM customers" in result.output
        assert "count" in result.output and "10" in result.output


def test_cli_ask_ambiguous_interactive():
    mock_llm = MagicMock()
    # 1. Ambiguity check: returns ambiguous result with 2 options
    mock_llm.generate_structured.return_value = AmbiguityCheckResult(
        is_ambiguous=True,
        ambiguity_type=AmbiguityDimension.METRIC,
        explanation="Metric 'best' is subjective",
        options=[
            ClarificationOption(id="A", label="By Total Spend", description="Rank by spend", implied_sql_logic="SUM(payments.amount)"),
            ClarificationOption(id="B", label="By Order Count", description="Rank by count", implied_sql_logic="COUNT(orders.id)")
        ]
    )
    # 2. Valid SQL synthesis
    mock_llm.generate.return_value = "SELECT c.name, SUM(p.amount) FROM customers c JOIN orders o ON c.id = o.customer_id JOIN payments p ON o.id = p.order_id GROUP BY c.name;"

    mock_sandbox = MagicMock()
    mock_sandbox.execute.return_value = ExecutionResult(
        success=True,
        columns=["name", "spend"],
        rows=[["Alice", 500.0]],
        row_count=1,
        execution_time_ms=15.0,
        executed_sql="SELECT c.name, SUM(p.amount) FROM customers c JOIN orders o ON c.id = o.customer_id JOIN payments p ON o.id = p.order_id GROUP BY c.name"
    )

    with patch("clarifysql.cli.app.get_llm_client", return_value=mock_llm), \
         patch("clarifysql.cli.app.SQLExecutionSandbox", return_value=mock_sandbox):

        # Pass "A\n" as interactive user selection
        result = runner.invoke(app, ["ask", "Who are our best customers?"], input="A\n")
        assert result.exit_code == 0
        assert "Ambiguity Detected (METRIC)" in result.output
        assert "Select Business Interpretation" in result.output
        assert "By Total Spend" in result.output
        assert "Generated PostgreSQL Query" in result.output


def test_cli_compare():
    mock_llm = MagicMock()
    mock_llm.generate_structured.return_value = AmbiguityCheckResult(
        is_ambiguous=True,
        ambiguity_type=AmbiguityDimension.METRIC,
        explanation="Metric ambiguous",
        options=[
            ClarificationOption(id="A", label="Option A", description="Desc A", implied_sql_logic="SELECT 1"),
            ClarificationOption(id="B", label="Option B", description="Desc B", implied_sql_logic="SELECT 2")
        ]
    )
    # Pipeline A returns arbitrary count query, Pipeline B returns clarified sum query
    mock_llm.generate.side_effect = [
        "SELECT COUNT(*) FROM orders;",           # Pipeline A
        "SELECT SUM(amount) FROM payments;"       # Pipeline B
    ]

    mock_sandbox = MagicMock()
    mock_sandbox.execute.return_value = ExecutionResult(
        success=True,
        columns=["val"],
        rows=[[100]],
        row_count=1,
        execution_time_ms=5.0
    )

    with patch("clarifysql.cli.app.get_llm_client", return_value=mock_llm), \
         patch("clarifysql.cli.app.SQLExecutionSandbox", return_value=mock_sandbox):

        result = runner.invoke(app, ["compare", "What is our sales volume?"])
        assert result.exit_code == 0
        assert "Pipeline A: Baseline Direct" in result.output
        assert "Pipeline B: ClarifySQL" in result.output
        assert "CRITICAL DATA DIVERGENCE DETECTED" in result.output


def test_cli_benchmark():
    mock_llm = MagicMock()
    mock_llm.generate_structured.return_value = AmbiguityCheckResult(is_ambiguous=False)
    mock_llm.generate.return_value = "SELECT 1;"

    mock_sandbox = MagicMock()
    mock_sandbox.execute.return_value = ExecutionResult(success=True)

    with patch("clarifysql.cli.app.get_llm_client", return_value=mock_llm), \
         patch("clarifysql.cli.app.SQLExecutionSandbox", return_value=mock_sandbox):

        result = runner.invoke(app, ["benchmark"])
        assert result.exit_code == 0
        assert "ClarifySQL Benchmark Evaluation Results" in result.output
        assert "Ambiguity Detection Recall" in result.output
