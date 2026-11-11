import pytest
from pathlib import Path
from clarifysql.schema.semantic_layer import load_semantic_catalog, SemanticCatalog
from config.settings import Settings


def test_load_yaml_catalog():
    catalog = load_semantic_catalog("config/metrics.yaml")
    assert isinstance(catalog, SemanticCatalog)
    assert catalog.version == "1.0.0"
    assert "customers" in catalog.tables
    assert "orders" in catalog.tables
    assert "payments" in catalog.tables
    assert "gross_revenue" in catalog.metrics
    assert "net_revenue" in catalog.metrics


def test_load_json_catalog():
    catalog = load_semantic_catalog("config/metrics.json")
    assert isinstance(catalog, SemanticCatalog)
    assert catalog.version == "1.0.0"
    assert "customers" in catalog.tables
    assert "orders" in catalog.tables
    assert "payments" in catalog.tables
    assert "gross_revenue" in catalog.metrics


def test_yaml_and_json_parity():
    yaml_cat = load_semantic_catalog("config/metrics.yaml")
    json_cat = load_semantic_catalog("config/metrics.json")

    assert set(yaml_cat.tables.keys()) == set(json_cat.tables.keys())
    assert set(yaml_cat.metrics.keys()) == set(json_cat.metrics.keys())

    for metric_name in yaml_cat.metrics:
        assert yaml_cat.metrics[metric_name].sql_expression == json_cat.metrics[metric_name].sql_expression
        assert yaml_cat.metrics[metric_name].filters == json_cat.metrics[metric_name].filters


def test_find_tables_by_synonym():
    catalog = load_semantic_catalog("config/metrics.yaml")
    assert "customers" in catalog.find_tables_by_term("shoppers")
    assert "customers" in catalog.find_tables_by_term("users")
    assert "orders" in catalog.find_tables_by_term("purchases")
    assert "payments" in catalog.find_tables_by_term("revenue")


def test_prompt_formatting():
    catalog = load_semantic_catalog("config/metrics.yaml")
    metrics_prompt = catalog.format_metrics_for_prompt()
    schema_prompt = catalog.format_schema_for_prompt()

    assert "Gross Revenue" in metrics_prompt
    assert "Net Revenue" in metrics_prompt
    assert "Table: `customers`" in schema_prompt
    assert "Table: `orders`" in schema_prompt
    assert "Table: `payments`" in schema_prompt


def test_invalid_extension():
    with pytest.raises(ValueError, match="Unsupported file format"):
        load_semantic_catalog("docs/project_requirement_document.md")


def test_nonexistent_file():
    with pytest.raises(FileNotFoundError):
        load_semantic_catalog("config/nonexistent.yaml")


def test_settings_defaults():
    s = Settings()
    assert s.llm_provider in ("ollama", "groq")
    assert s.statement_timeout_ms == 10000
    assert s.max_result_rows == 500
    assert s.max_correction_retries == 2
