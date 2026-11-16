from unittest.mock import MagicMock
import pytest
from clarifysql.ambiguity.detector import AmbiguityDetector
from clarifysql.ambiguity.models import (
    AmbiguityCheckResult,
    AmbiguityDimension,
    ClarificationOption,
)
from clarifysql.execution.models import ExecutionResult
from clarifysql.execution.sandbox import SQLExecutionSandbox
from clarifysql.generator.sql_generator import SQLGenerator
from clarifysql.pipeline.clarifysql_pipeline import ClarifySQLPipeline
from clarifysql.pipeline.direct_pipeline import DirectPipeline
from clarifysql.schema.extractor import SchemaExtractor
from clarifysql.schema.retriever import HybridFKSchemaRetriever
from clarifysql.schema.semantic_layer import load_semantic_catalog


@pytest.fixture
def catalog():
    return load_semantic_catalog("config/metrics.yaml")


@pytest.fixture
def schema(catalog):
    return SchemaExtractor.from_semantic_catalog(catalog).get_schema()


@pytest.fixture
def mock_sandbox():
    sandbox = MagicMock(spec=SQLExecutionSandbox)
    sandbox.execute.return_value = ExecutionResult(
        success=True,
        columns=["count"],
        rows=[[10]],
        row_count=1,
        executed_sql="SELECT COUNT(*) FROM customers"
    )
    return sandbox


def test_direct_pipeline_execution(catalog, schema, mock_sandbox):
    mock_llm = MagicMock()
    mock_llm.generate.return_value = "SELECT COUNT(*) FROM customers;"

    generator = SQLGenerator(llm_client=mock_llm, catalog=catalog, schema=schema)
    retriever = HybridFKSchemaRetriever(catalog=catalog)

    pipeline = DirectPipeline(
        sql_generator=generator,
        retriever=retriever,
        schema=schema,
        sandbox=mock_sandbox
    )

    res = pipeline.run("Count registered customers")
    assert res.query == "Count registered customers"
    assert "customers" in res.generated_sql
    assert res.execution_result.success is True
    mock_sandbox.execute.assert_called_once()


def test_clarifysql_pipeline_unambiguous_query(catalog, schema, mock_sandbox):
    mock_llm = MagicMock()
    # Mock ambiguity check: clean query
    mock_llm.generate_structured.return_value = AmbiguityCheckResult(is_ambiguous=False)
    mock_llm.generate.return_value = "SELECT * FROM orders WHERE status = 'completed';"

    detector = AmbiguityDetector(catalog=catalog, schema=schema)
    generator = SQLGenerator(llm_client=mock_llm, catalog=catalog, schema=schema)
    retriever = HybridFKSchemaRetriever(catalog=catalog)

    pipeline = ClarifySQLPipeline(
        llm_client=mock_llm,
        detector=detector,
        sql_generator=generator,
        retriever=retriever,
        schema=schema,
        sandbox=mock_sandbox
    )

    res = pipeline.run("Show completed orders")
    assert res.is_ambiguous is False
    assert res.needs_user_input is False
    assert res.execution_result.success is True


def test_clarifysql_pipeline_ambiguous_pauses_without_choice(catalog, schema, mock_sandbox):
    mock_llm = MagicMock()
    # Mock ambiguity check: ambiguous query
    mock_llm.generate_structured.return_value = AmbiguityCheckResult(
        is_ambiguous=True,
        ambiguity_type=AmbiguityDimension.METRIC,
        explanation="Subjective term 'best'",
        options=[
            ClarificationOption(id="A", label="Spend", description="By spend", implied_sql_logic="SUM(amount)"),
            ClarificationOption(id="B", label="Count", description="By count", implied_sql_logic="COUNT(id)")
        ]
    )

    detector = AmbiguityDetector(catalog=catalog, schema=schema)
    generator = SQLGenerator(llm_client=mock_llm, catalog=catalog, schema=schema)
    retriever = HybridFKSchemaRetriever(catalog=catalog)

    pipeline = ClarifySQLPipeline(
        llm_client=mock_llm,
        detector=detector,
        sql_generator=generator,
        retriever=retriever,
        schema=schema,
        sandbox=mock_sandbox
    )

    res = pipeline.run("Who are our best customers?")
    assert res.is_ambiguous is True
    assert res.needs_user_input is True
    assert res.resolution is None
    # Verifies SQL was NOT generated or executed yet
    mock_sandbox.execute.assert_not_called()


def test_clarifysql_pipeline_ambiguous_resolves_with_choice(catalog, schema, mock_sandbox):
    mock_llm = MagicMock()
    mock_llm.generate_structured.return_value = AmbiguityCheckResult(
        is_ambiguous=True,
        ambiguity_type=AmbiguityDimension.METRIC,
        explanation="Subjective term 'best'",
        options=[
            ClarificationOption(id="A", label="Spend", description="By spend", implied_sql_logic="SUM(payments.amount)"),
            ClarificationOption(id="B", label="Count", description="By count", implied_sql_logic="COUNT(orders.id)")
        ]
    )
    mock_llm.generate.return_value = "SELECT c.name, SUM(p.amount) FROM customers c JOIN orders o ON c.id = o.customer_id JOIN payments p ON o.id = p.order_id GROUP BY c.name;"

    detector = AmbiguityDetector(catalog=catalog, schema=schema)
    generator = SQLGenerator(llm_client=mock_llm, catalog=catalog, schema=schema)
    retriever = HybridFKSchemaRetriever(catalog=catalog)

    pipeline = ClarifySQLPipeline(
        llm_client=mock_llm,
        detector=detector,
        sql_generator=generator,
        retriever=retriever,
        schema=schema,
        sandbox=mock_sandbox
    )

    res = pipeline.run("Who are our best customers?", resolution_choice="A")
    assert res.is_ambiguous is True
    assert res.needs_user_input is False
    assert res.resolution.selected_option_id == "A"
    assert res.execution_result.success is True
    mock_sandbox.execute.assert_called_once()
