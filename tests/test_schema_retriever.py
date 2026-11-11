import pytest
from clarifysql.schema.extractor import (
    ColumnSchema,
    DatabaseSchema,
    SchemaExtractor,
    TableSchema,
)
from clarifysql.schema.retriever import (
    HybridFKSchemaRetriever,
    LexicalSchemaRetriever,
)
from clarifysql.schema.semantic_layer import load_semantic_catalog


@pytest.fixture
def catalog():
    return load_semantic_catalog("config/metrics.yaml")


@pytest.fixture
def base_schema(catalog):
    extractor = SchemaExtractor.from_semantic_catalog(catalog)
    return extractor.get_schema()


def test_schema_extractor_ddl(base_schema):
    ddl = base_schema.to_ddl_summary()
    assert "CREATE TABLE customers" in ddl
    assert "CREATE TABLE orders" in ddl
    assert "CREATE TABLE payments" in ddl
    assert "PRIMARY KEY" in ddl
    assert "REFERENCES" in ddl


def test_lexical_retriever_direct_match(catalog, base_schema):
    retriever = LexicalSchemaRetriever(catalog=catalog)
    matched = retriever.retrieve_tables("Show all customers", base_schema)
    assert matched == ["customers"]


def test_lexical_retriever_synonym_match(catalog, base_schema):
    retriever = LexicalSchemaRetriever(catalog=catalog)
    # 'shoppers' matches customers synonym, 'purchases' matches orders synonym
    matched = retriever.retrieve_tables("Find shoppers who made purchases", base_schema)
    assert "customers" in matched
    assert "orders" in matched


def test_lexical_retriever_metric_match(catalog, base_schema):
    retriever = LexicalSchemaRetriever(catalog=catalog)
    matched = retriever.retrieve_tables("Calculate our gross revenue", base_schema)
    assert "payments" in matched


def test_lexical_retriever_fallback(catalog, base_schema):
    retriever = LexicalSchemaRetriever(catalog=catalog)
    # Query with no overlapping vocabulary
    matched = retriever.retrieve_tables("Quantum teleportation dynamics", base_schema)
    assert sorted(matched) == ["customers", "orders", "payments"]


def test_hybrid_fk_adaptive_threshold_small_schema(catalog, base_schema):
    # Schema has 3 tables, threshold is 10 -> should auto-inject all 3 tables
    retriever = HybridFKSchemaRetriever(catalog=catalog, max_auto_inject_tables=10)
    matched = retriever.retrieve_tables("Show all customers", base_schema)
    assert sorted(matched) == ["customers", "orders", "payments"]


def test_hybrid_fk_graph_closure_on_large_schema(catalog):
    # Construct a 12-table enterprise schema to exceed threshold of 10
    tables = {
        "customers": TableSchema(name="customers", primary_key="id"),
        "orders": TableSchema(
            name="orders",
            primary_key="id",
            foreign_keys={"customer_id": "customers.id"}
        ),
        "payments": TableSchema(
            name="payments",
            primary_key="id",
            foreign_keys={"order_id": "orders.id"}
        ),
        "audit_logs": TableSchema(name="audit_logs"),
        "categories": TableSchema(name="categories"),
        "coupons": TableSchema(name="coupons"),
        "inventory": TableSchema(name="inventory"),
        "reviews": TableSchema(name="reviews"),
        "shippers": TableSchema(name="shippers"),
        "suppliers": TableSchema(name="suppliers"),
        "tags": TableSchema(name="tags"),
        "warehouses": TableSchema(name="warehouses"),
    }
    large_schema = DatabaseSchema(tables=tables)

    # 1. Test Baseline Lexical Retriever:
    # A query mentioning only customer and payments misses the intermediate 'orders' table!
    lexical = LexicalSchemaRetriever(catalog=catalog)
    lexical_matched = lexical.retrieve_tables("Show customer payments amount", large_schema)
    assert "customers" in lexical_matched
    assert "payments" in lexical_matched
    assert "orders" not in lexical_matched  # Baseline fails to capture the join bridge!

    # 2. Test Recommended Hybrid FK Retriever:
    # With threshold 10, it triggers FK graph closure and includes 'orders' bridge table
    hybrid = HybridFKSchemaRetriever(catalog=catalog, max_auto_inject_tables=10)
    hybrid_matched = hybrid.retrieve_tables("Show customer payments amount", large_schema)
    assert "customers" in hybrid_matched
    assert "payments" in hybrid_matched
    assert "orders" in hybrid_matched  # Hybrid FK closure successfully recovers the join bridge!
    assert "warehouses" not in hybrid_matched
    assert "audit_logs" not in hybrid_matched
