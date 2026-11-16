from typing import Any, List, Optional
from pydantic import BaseModel, Field
from tabulate import tabulate


class QueryEvalResult(BaseModel):
    """Evaluation result for an individual benchmark test query."""
    id: int
    query: str
    is_ambiguous_ground_truth: bool
    is_ambiguous_detected: bool
    ambiguity_type_ground_truth: Optional[str] = None
    ambiguity_type_detected: Optional[str] = None
    pipeline_a_success: bool = False
    pipeline_b_success: bool = False
    pipeline_a_sql: str = ""
    pipeline_b_sql: str = ""
    semantic_diverged: bool = False
    execution_time_a_ms: float = 0.0
    execution_time_b_ms: float = 0.0


class BenchmarkSummary(BaseModel):
    """Aggregate comparative evaluation summary metrics (REQ-EVAL-02)."""
    total_queries: int = 0
    total_ambiguous: int = 0
    total_unambiguous: int = 0

    # Pipeline A Metrics
    pipeline_a_exec_count: int = 0
    pipeline_a_exec_accuracy: float = 0.0

    # Pipeline B Metrics
    pipeline_b_exec_count: int = 0
    pipeline_b_exec_accuracy: float = 0.0

    # Ambiguity Detection Metrics
    true_positives: int = 0   # Ambiguous and flagged as ambiguous
    false_positives: int = 0  # Unambiguous but flagged as ambiguous
    true_negatives: int = 0   # Unambiguous and passed directly
    false_negatives: int = 0  # Ambiguous but missed

    ambiguity_precision: float = 0.0
    ambiguity_recall: float = 0.0
    false_interception_rate: float = 0.0

    # Divergence
    semantic_divergence_count: int = 0
    semantic_divergence_rate: float = 0.0

    def render_summary_table(self) -> str:
        """Render a formatted comparative summary table for reports."""
        table = [
            ["Total Benchmark Queries", self.total_queries],
            ["- Unambiguous Queries", self.total_unambiguous],
            ["- Deliberately Ambiguous Queries", self.total_ambiguous],
            ["", ""],
            ["Pipeline A (Baseline Direct) Execution Accuracy", f"{self.pipeline_a_exec_accuracy:.1f}%"],
            ["Pipeline B (ClarifySQL Active) Execution Accuracy", f"{self.pipeline_b_exec_accuracy:.1f}%"],
            ["", ""],
            ["Ambiguity Detection Recall (Target >= 90%)", f"{self.ambiguity_recall:.1f}%"],
            ["Ambiguity Detection Precision", f"{self.ambiguity_precision:.1f}%"],
            ["False Interception Rate (Target <= 5%)", f"{self.false_interception_rate:.1f}%"],
            ["", ""],
            ["Semantic Divergence Rate (A vs. B)", f"{self.semantic_divergence_rate:.1f}%"],
        ]
        return tabulate(table, headers=["Benchmark Metric", "Value"], tablefmt="github")


def calculate_summary(results: List[QueryEvalResult]) -> BenchmarkSummary:
    """Calculate aggregate metrics across all query results."""
    summary = BenchmarkSummary(total_queries=len(results))

    tp = fp = tn = fn = 0
    pipe_a_ok = pipe_b_ok = 0
    divergence_count = 0

    for r in results:
        # Ambiguity confusion matrix
        if r.is_ambiguous_ground_truth:
            summary.total_ambiguous += 1
            if r.is_ambiguous_detected:
                tp += 1
            else:
                fn += 1
        else:
            summary.total_unambiguous += 1
            if r.is_ambiguous_detected:
                fp += 1
            else:
                tn += 1

        # Execution success
        if r.pipeline_a_success:
            pipe_a_ok += 1
        if r.pipeline_b_success:
            pipe_b_ok += 1

        # Semantic divergence on ambiguous queries
        if r.is_ambiguous_ground_truth and r.semantic_diverged:
            divergence_count += 1

    summary.true_positives = tp
    summary.false_positives = fp
    summary.true_negatives = tn
    summary.false_negatives = fn

    total = summary.total_queries
    ambig_total = summary.total_ambiguous
    unambig_total = summary.total_unambiguous

    summary.pipeline_a_exec_count = pipe_a_ok
    summary.pipeline_b_exec_count = pipe_b_ok
    summary.pipeline_a_exec_accuracy = (pipe_a_ok / total * 100.0) if total else 0.0
    summary.pipeline_b_exec_accuracy = (pipe_b_ok / total * 100.0) if total else 0.0

    summary.ambiguity_precision = (tp / (tp + fp) * 100.0) if (tp + fp) else 100.0
    summary.ambiguity_recall = (tp / (tp + fn) * 100.0) if (tp + fn) else 100.0
    summary.false_interception_rate = (fp / unambig_total * 100.0) if unambig_total else 0.0

    summary.semantic_divergence_count = divergence_count
    summary.semantic_divergence_rate = (divergence_count / ambig_total * 100.0) if ambig_total else 0.0

    return summary
