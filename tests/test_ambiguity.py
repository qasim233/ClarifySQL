import pytest
from clarifysql.ambiguity.models import (
    AmbiguityCheckResult,
    AmbiguityDimension,
    ClarificationOption,
    ClarificationResolution,
)
from clarifysql.ambiguity.detector import AmbiguityDetector
from clarifysql.schema.extractor import SchemaExtractor
from clarifysql.schema.semantic_layer import load_semantic_catalog


@pytest.fixture
def catalog():
    return load_semantic_catalog("config/metrics.yaml")


@pytest.fixture
def schema(catalog):
    return SchemaExtractor.from_semantic_catalog(catalog).get_schema()


@pytest.fixture
def detector(catalog, schema):
    return AmbiguityDetector(catalog=catalog, schema=schema)


def test_unambiguous_model_valid():
    res = AmbiguityCheckResult(is_ambiguous=False)
    assert res.is_ambiguous is False
    assert res.options == []
    assert res.ambiguity_type is None


def test_ambiguous_model_valid():
    res = AmbiguityCheckResult(
        is_ambiguous=True,
        ambiguity_type=AmbiguityDimension.METRIC,
        explanation="Metric 'best' has multiple interpretations.",
        options=[
            ClarificationOption(
                id="A",
                label="By Total Spend",
                description="Highest monetary value",
                implied_sql_logic="SUM(payments.amount)"
            ),
            ClarificationOption(
                id="B",
                label="By Order Count",
                description="Most completed orders",
                implied_sql_logic="COUNT(orders.id)"
            )
        ]
    )
    assert res.is_ambiguous is True
    assert len(res.options) == 2


def test_ambiguous_model_requires_options():
    # Only 1 option provided -> must fail (minimum 2 required)
    with pytest.raises(ValueError, match="between 2 and 4 options"):
        AmbiguityCheckResult(
            is_ambiguous=True,
            ambiguity_type=AmbiguityDimension.METRIC,
            explanation="Test explanation",
            options=[
                ClarificationOption(
                    id="A",
                    label="Option 1",
                    description="Only one option",
                    implied_sql_logic="SELECT 1"
                )
            ]
        )


def test_ambiguous_model_max_options():
    # 5 options provided -> must fail (maximum 4 allowed)
    options = [
        ClarificationOption(id=str(i), label=f"Opt {i}", description=f"Desc {i}", implied_sql_logic="SELECT 1")
        for i in range(5)
    ]
    with pytest.raises(ValueError, match="between 2 and 4 options"):
        AmbiguityCheckResult(
            is_ambiguous=True,
            ambiguity_type=AmbiguityDimension.TEMPORAL,
            explanation="Test",
            options=options
        )


def test_ambiguous_model_unique_option_ids():
    # Duplicate IDs ("A", "A") -> must fail
    with pytest.raises(ValueError, match="Option IDs must be unique"):
        AmbiguityCheckResult(
            is_ambiguous=True,
            ambiguity_type=AmbiguityDimension.SCHEMA_ENTITY,
            explanation="Test",
            options=[
                ClarificationOption(id="A", label="Opt 1", description="Desc 1", implied_sql_logic="SELECT 1"),
                ClarificationOption(id="A", label="Opt 2", description="Desc 2", implied_sql_logic="SELECT 2"),
            ]
        )


def test_build_classification_prompt(detector):
    prompt = detector.build_classification_prompt("Who are our top customers?")
    assert "ADCE" in prompt
    assert "CREATE TABLE customers" in prompt
    assert "Gross Revenue" in prompt
    assert "Who are our top customers?" in prompt


def test_parse_classification_response_with_markdown(detector):
    raw_response = """
    Here is your ambiguity check result:
    ```json
    {
      "is_ambiguous": true,
      "ambiguity_type": "METRIC",
      "explanation": "Subjective term 'top' is not specified.",
      "options": [
        {
          "id": "A",
          "label": "Total Spend",
          "description": "Rank by total payment amount",
          "implied_sql_logic": "SUM(payments.amount)"
        },
        {
          "id": "B",
          "label": "Order Count",
          "description": "Rank by order frequency",
          "implied_sql_logic": "COUNT(orders.id)"
        }
      ]
    }
    ```
    """
    result = detector.parse_classification_response(raw_response)
    assert result.is_ambiguous is True
    assert result.ambiguity_type == AmbiguityDimension.METRIC
    assert len(result.options) == 2


def test_resolve_clarification_by_id(detector):
    check_result = AmbiguityCheckResult(
        is_ambiguous=True,
        ambiguity_type=AmbiguityDimension.TEMPORAL,
        explanation="Date ambiguity",
        options=[
            ClarificationOption(
                id="A",
                label="By Order Date",
                description="Orders created timestamp",
                implied_sql_logic="orders.order_date"
            ),
            ClarificationOption(
                id="B",
                label="By Payment Date",
                description="Payment processed timestamp",
                implied_sql_logic="payments.payment_date"
            )
        ]
    )

    # Resolve by letter "A"
    res_a = detector.resolve_clarification(check_result, "a")
    assert res_a.selected_option_id == "A"
    assert "By Order Date" in res_a.resolved_instruction
    assert res_a.implied_sql_logic == "orders.order_date"

    # Resolve by index "2" (maps to B)
    res_b = detector.resolve_clarification(check_result, "2")
    assert res_b.selected_option_id == "B"
    assert "By Payment Date" in res_b.resolved_instruction


def test_resolve_clarification_custom_text(detector):
    check_result = AmbiguityCheckResult(
        is_ambiguous=True,
        ambiguity_type=AmbiguityDimension.METRIC,
        explanation="Metric ambiguity",
        options=[
            ClarificationOption(id="A", label="A", description="A", implied_sql_logic="A"),
            ClarificationOption(id="B", label="B", description="B", implied_sql_logic="B")
        ]
    )
    res = detector.resolve_clarification(check_result, "Only include customers with orders over $1000")
    assert res.selected_option_id is None
    assert res.custom_clarification == "Only include customers with orders over $1000"
    assert "User clarified preference:" in res.resolved_instruction


def test_build_augmented_prompt(detector):
    resolution = ClarificationResolution(
        selected_option_id="A",
        resolved_instruction="Highest Total Spend: Rank customers by sum of successful payments",
        implied_sql_logic="SUM(payments.amount) WHERE payment_status = 'successful'"
    )
    augmented = detector.build_augmented_prompt("Who are our top customers?", resolution)
    assert "User Goal: Who are our top customers?" in augmented
    assert "Highest Total Spend" in augmented
    assert "SUM(payments.amount)" in augmented
