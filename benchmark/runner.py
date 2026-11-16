import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union
from benchmark.metrics import BenchmarkSummary, QueryEvalResult, calculate_summary
from clarifysql.pipeline.clarifysql_pipeline import ClarifySQLPipeline
from clarifysql.pipeline.direct_pipeline import DirectPipeline


class BenchmarkRunner:
    """
    Automated comparative evaluation runner executing the 30-query verified benchmark
    across Pipeline A (Baseline Direct) and Pipeline B (ClarifySQL Active Clarification).
    """

    def __init__(
        self,
        pipeline_a: DirectPipeline,
        pipeline_b: ClarifySQLPipeline,
        dataset_path: Union[str, Path] = "benchmark/dataset.json"
    ):
        self.pipeline_a = pipeline_a
        self.pipeline_b = pipeline_b
        self.dataset_path = Path(dataset_path)

    def load_dataset(self) -> List[Dict]:
        if not self.dataset_path.is_file():
            raise FileNotFoundError(f"Benchmark dataset not found at {self.dataset_path.resolve()}")
        content = self.dataset_path.read_text(encoding="utf-8")
        return json.loads(content)

    def evaluate_query(self, item: Dict) -> QueryEvalResult:
        query_id = item["id"]
        query_text = item["query"]
        is_ambig_gt = item.get("is_ambiguous", False)
        ambig_type_gt = item.get("ambiguity_type")
        simulated_choice = item.get("simulated_choice")

        # 1. Execute Pipeline A (Direct)
        res_a = self.pipeline_a.run(query_text)
        success_a = res_a.execution_result.success if res_a.execution_result else False
        time_a = res_a.execution_result.execution_time_ms if res_a.execution_result else 0.0

        # 2. Execute Pipeline B (ClarifySQL with simulated choice for ambiguous queries)
        res_b = self.pipeline_b.run(query_text, resolution_choice=simulated_choice)
        success_b = res_b.execution_result.success if res_b.execution_result else False
        time_b = res_b.execution_result.execution_time_ms if res_b.execution_result else 0.0

        # 3. Check for Semantic Divergence
        # For ambiguous queries, if Pipeline A's hallucinated SQL does not match Pipeline B's
        # clarified SQL, a semantic divergence (silent data deviation) has occurred.
        semantic_diverged = False
        if is_ambig_gt:
            # Compare generated SQL
            sql_a = (res_a.generated_sql or "").strip().lower()
            sql_b = (res_b.generated_sql or "").strip().lower()
            semantic_diverged = (sql_a != sql_b)

        return QueryEvalResult(
            id=query_id,
            query=query_text,
            is_ambiguous_ground_truth=is_ambig_gt,
            is_ambiguous_detected=res_b.is_ambiguous,
            ambiguity_type_ground_truth=ambig_type_gt,
            ambiguity_type_detected=str(res_b.ambiguity_type.value) if res_b.ambiguity_type else None,
            pipeline_a_success=success_a,
            pipeline_b_success=success_b,
            pipeline_a_sql=res_a.generated_sql,
            pipeline_b_sql=res_b.generated_sql,
            semantic_diverged=semantic_diverged,
            execution_time_a_ms=time_a,
            execution_time_b_ms=time_b
        )

    def run(self) -> Tuple[List[QueryEvalResult], BenchmarkSummary]:
        dataset = self.load_dataset()
        results: List[QueryEvalResult] = []

        for item in dataset:
            result = self.evaluate_query(item)
            results.append(result)

        summary = calculate_summary(results)
        return results, summary
