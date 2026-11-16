#!/usr/bin/env python3
"""
CLI entry point to execute the ClarifySQL comparative evaluation benchmark (Pipeline A vs. Pipeline B).
"""
import argparse
import sys
from pathlib import Path

# Ensure project root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from benchmark.runner import BenchmarkRunner
from clarifysql.ambiguity.detector import AmbiguityDetector
from clarifysql.execution.sandbox import SQLExecutionSandbox
from clarifysql.generator.sql_generator import SQLGenerator
from clarifysql.llm.factory import get_llm_client
from clarifysql.pipeline.clarifysql_pipeline import ClarifySQLPipeline
from clarifysql.pipeline.direct_pipeline import DirectPipeline
from clarifysql.schema.extractor import SchemaExtractor
from clarifysql.schema.retriever import HybridFKSchemaRetriever
from clarifysql.schema.semantic_layer import load_semantic_catalog
from config.settings import settings


def main():
    parser = argparse.ArgumentParser(description="Run ClarifySQL comparative evaluation benchmark.")
    parser.add_argument("--provider", type=str, default=None, help="LLM Provider: 'ollama' or 'groq'")
    parser.add_argument("--dataset", type=str, default="benchmark/dataset.json", help="Path to benchmark dataset")
    args = parser.parse_args()

    provider = args.provider or settings.llm_provider
    print(f"Initializing ClarifySQL Benchmark Suite [LLM Provider: {provider}]...")

    # 1. Load Semantic Catalog and Extract Schema
    catalog = load_semantic_catalog(settings.semantic_metrics_path)
    extractor = SchemaExtractor.from_semantic_catalog(catalog)
    schema = extractor.get_schema()

    # 2. Initialize Components
    llm = get_llm_client(provider=provider)
    retriever = HybridFKSchemaRetriever(catalog=catalog, max_auto_inject_tables=10)
    detector = AmbiguityDetector(catalog=catalog, schema=schema)
    sql_generator = SQLGenerator(llm_client=llm, catalog=catalog, schema=schema)
    sandbox = SQLExecutionSandbox(connection_url=settings.database_url)

    # 3. Initialize Pipelines
    pipeline_a = DirectPipeline(
        sql_generator=sql_generator,
        retriever=retriever,
        schema=schema,
        sandbox=sandbox
    )

    pipeline_b = ClarifySQLPipeline(
        llm_client=llm,
        detector=detector,
        sql_generator=sql_generator,
        retriever=retriever,
        schema=schema,
        sandbox=sandbox
    )

    runner = BenchmarkRunner(
        pipeline_a=pipeline_a,
        pipeline_b=pipeline_b,
        dataset_path=args.dataset
    )

    print(f"Executing 30-query verified benchmark from {args.dataset}...")
    results, summary = runner.run()

    print("\n" + "=" * 60)
    print("CLARIFYSQL COMPARATIVE EVALUATION RESULTS (Pipeline A vs. Pipeline B)")
    print("=" * 60 + "\n")
    print(summary.render_summary_table())
    print("\n")


if __name__ == "__main__":
    main()
