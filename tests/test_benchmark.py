import json
from pathlib import Path
from unittest.mock import MagicMock
import pytest
from benchmark.metrics import BenchmarkSummary, QueryEvalResult, calculate_summary
from benchmark.runner import BenchmarkRunner
from clarifysql.execution.models import ExecutionResult
from clarifysql.pipeline.clarifysql_pipeline import ClarifySQLPipeline, ClarifySQLResult
from clarifysql.pipeline.direct_pipeline import DirectPipeline, DirectPipelineResult


def test_benchmark_dataset_integrity():
    path = Path("benchmark/dataset.json")
    assert path.is_file()

    dataset = json.loads(path.read_text(encoding="utf-8"))
    assert len(dataset) == 30

    unambig = [q for q in dataset if not q["is_ambiguous"]]
    ambig = [q for q in dataset if q["is_ambiguous"]]

    assert len(unambig) == 10
    assert len(ambig) == 20

    # Ensure all 4 dimensions are represented
    dimensions = {q["ambiguity_type"] for q in ambig}
    assert dimensions == {"METRIC", "TEMPORAL", "SCHEMA_ENTITY", "GRANULARITY"}

    # Verify ground truth and simulated choices
    for item in dataset:
        assert item["query"].strip()
        assert item["ground_truth_sql"].strip()
        if item["is_ambiguous"]:
            assert item["simulated_choice"] in ("A", "B", "C", "D")


def test_metrics_calculation():
    eval_results = [
        # Query 1: Unambiguous, correctly passed (TN)
        QueryEvalResult(
            id=1, query="q1",
            is_ambiguous_ground_truth=False, is_ambiguous_detected=False,
            pipeline_a_success=True, pipeline_b_success=True,
            pipeline_a_sql="SELECT 1", pipeline_b_sql="SELECT 1",
            semantic_diverged=False
        ),
        # Query 2: Ambiguous, correctly flagged (TP), diverged
        QueryEvalResult(
            id=2, query="q2",
            is_ambiguous_ground_truth=True, is_ambiguous_detected=True,
            pipeline_a_success=True, pipeline_b_success=True,
            pipeline_a_sql="SELECT sum(amount)", pipeline_b_sql="SELECT count(*)",
            semantic_diverged=True
        ),
        # Query 3: Ambiguous, correctly flagged (TP), matched
        QueryEvalResult(
            id=3, query="q3",
            is_ambiguous_ground_truth=True, is_ambiguous_detected=True,
            pipeline_a_success=True, pipeline_b_success=True,
            pipeline_a_sql="SELECT 3", pipeline_b_sql="SELECT 3",
            semantic_diverged=False
        ),
    ]

    summary = calculate_summary(eval_results)
    assert summary.total_queries == 3
    assert summary.total_ambiguous == 2
    assert summary.total_unambiguous == 1
    assert summary.true_positives == 2
    assert summary.false_positives == 0
    assert summary.true_negatives == 1
    assert summary.false_negatives == 0
    assert summary.ambiguity_recall == 100.0
    assert summary.ambiguity_precision == 100.0
    assert summary.false_interception_rate == 0.0
    assert summary.semantic_divergence_rate == 50.0

    # Check table output
    table_str = summary.render_summary_table()
    assert "Ambiguity Detection Recall" in table_str
    assert "100.0%" in table_str


def test_benchmark_runner_mocked():
    mock_pipe_a = MagicMock(spec=DirectPipeline)
    mock_pipe_a.run.return_value = DirectPipelineResult(
        query="Test query",
        generated_sql="SELECT 1",
        execution_result=ExecutionResult(success=True)
    )

    mock_pipe_b = MagicMock(spec=ClarifySQLPipeline)
    mock_pipe_b.run.return_value = ClarifySQLResult(
        query="Test query",
        is_ambiguous=False,
        generated_sql="SELECT 1",
        execution_result=ExecutionResult(success=True)
    )

    runner = BenchmarkRunner(
        pipeline_a=mock_pipe_a,
        pipeline_b=mock_pipe_b,
        dataset_path="benchmark/dataset.json"
    )

    results, summary = runner.run()
    assert len(results) == 30
    assert summary.total_queries == 30
    assert summary.pipeline_a_exec_count == 30
    assert summary.pipeline_b_exec_count == 30
