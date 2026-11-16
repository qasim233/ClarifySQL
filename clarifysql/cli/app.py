from typing import Any, List, Optional
import typer
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.syntax import Syntax
from rich.table import Table

from benchmark.runner import BenchmarkRunner
from clarifysql.ambiguity.detector import AmbiguityDetector
from clarifysql.execution.models import ExecutionResult
from clarifysql.execution.sandbox import SQLExecutionSandbox
from clarifysql.generator.sql_generator import SQLGenerator
from clarifysql.llm.factory import get_llm_client
from clarifysql.pipeline.clarifysql_pipeline import ClarifySQLPipeline
from clarifysql.pipeline.direct_pipeline import DirectPipeline
from clarifysql.schema.extractor import SchemaExtractor
from clarifysql.schema.retriever import HybridFKSchemaRetriever
from clarifysql.schema.semantic_layer import load_semantic_catalog
from config.settings import settings

app = typer.Typer(
    name="clarifysql",
    help="ClarifySQL: Intelligent Natural Language to SQL with Active Ambiguity Resolution."
)
console = Console()


def _get_pipeline_context(provider: Optional[str] = None):
    """Factory helper to wire up ClarifySQL components."""
    active_provider = provider or settings.llm_provider
    catalog = load_semantic_catalog(settings.semantic_metrics_path)
    extractor = SchemaExtractor.from_semantic_catalog(catalog)
    schema = extractor.get_schema()

    llm = get_llm_client(provider=active_provider)
    retriever = HybridFKSchemaRetriever(catalog=catalog, max_auto_inject_tables=10)
    detector = AmbiguityDetector(catalog=catalog, schema=schema)
    sql_generator = SQLGenerator(llm_client=llm, catalog=catalog, schema=schema)
    sandbox = SQLExecutionSandbox(connection_url=settings.database_url)

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

    return catalog, schema, pipeline_a, pipeline_b


def _render_execution_result(res: ExecutionResult):
    """Render query results cleanly in a terminal table."""
    if not res.success:
        console.print(f"[bold red]Execution Error:[/bold red] {res.error_message}")
        return

    if not res.rows:
        console.print("[dim]Query returned 0 rows.[/dim]")
        return

    table = Table(
        title=f"Query Output ({res.row_count} rows in {res.execution_time_ms}ms)",
        header_style="bold cyan",
        show_lines=True
    )

    for col in res.columns:
        table.add_column(str(col))

    for row in res.rows:
        table.add_row(*[str(val) if val is not None else "[dim]NULL[/dim]" for val in row])

    console.print(table)
    if res.truncated:
        console.print("[yellow]Note: Result truncated to max limit (500 rows).[/yellow]")


@app.command()
def ask(
    query: str = typer.Argument(..., help="The natural language data query to ask"),
    choice: Optional[str] = typer.Option(None, "--choice", "-c", help="Pre-select an ambiguity resolution option (e.g. 'A')"),
    provider: Optional[str] = typer.Option(None, "--provider", "-p", help="LLM Provider: 'ollama' or 'groq'")
):
    """
    Run ClarifySQL pipeline on a user query with interactive ambiguity resolution.
    """
    console.print(Panel(f"[bold white]{query}[/bold white]", title="[bold green]ClarifySQL Request[/bold green]", expand=False))

    catalog, schema, _, pipeline_b = _get_pipeline_context(provider)

    try:
        with console.status("[bold cyan]Analyzing query ambiguity & database schema...[/bold cyan]"):
            result = pipeline_b.run(query=query, resolution_choice=choice)
    except Exception as err:
        console.print(f"\n[bold red]Error running ClarifySQL:[/bold red] {err}")
        raise typer.Exit(code=1)

    # If ambiguous and user choice is needed
    if result.needs_user_input and result.ambiguity_check:
        ambig = result.ambiguity_check
        console.print(f"\n[bold yellow]⚠️ Ambiguity Detected ({ambig.ambiguity_type.value}):[/bold yellow] {ambig.explanation}\n")

        # Build options table
        options_table = Table(title="Select Business Interpretation", show_header=True, header_style="bold magenta")
        options_table.add_column("Option", style="bold green", width=8)
        options_table.add_column("Title", style="bold white", width=30)
        options_table.add_column("Business Definition", style="dim", width=45)

        for opt in ambig.options:
            options_table.add_row(opt.id, opt.label, opt.description)

        console.print(options_table)
        console.print("\n[dim]You can type an option letter (e.g. 'A') or enter a custom business preference.[/dim]")

        user_input = Prompt.ask("\nYour choice", default="A")

        try:
            with console.status("[bold cyan]Synthesizing SQL with clarified business intent...[/bold cyan]"):
                result = pipeline_b.run(query=query, resolution_choice=user_input)
        except Exception as err:
            console.print(f"\n[bold red]Error during synthesis:[/bold red] {err}")
            raise typer.Exit(code=1)

    # Display generated SQL
    if result.generated_sql:
        console.print("\n[bold green]Generated PostgreSQL Query:[/bold green]")
        console.print(Syntax(result.generated_sql, "sql", theme="monokai", line_numbers=False))
        console.print()

    # Display Execution Results
    if result.execution_result:
        _render_execution_result(result.execution_result)


@app.command()
def compare(
    query: str = typer.Argument(..., help="The natural language data query to compare across pipelines"),
    choice: Optional[str] = typer.Option("A", "--choice", "-c", help="Simulated clarification choice for Pipeline B"),
    provider: Optional[str] = typer.Option(None, "--provider", "-p", help="LLM Provider: 'ollama' or 'groq'")
):
    """
    Compare Pipeline A (Baseline Direct) vs. Pipeline B (ClarifySQL Active) side-by-side.
    Exposes silent data corruption and metric hallucinations.
    """
    console.print(Panel(f"[bold white]{query}[/bold white]", title="[bold cyan]Comparative Pipeline Analysis[/bold cyan]", expand=False))

    catalog, schema, pipeline_a, pipeline_b = _get_pipeline_context(provider)

    try:
        with console.status("[bold cyan]Running Pipeline A (Direct) and Pipeline B (ClarifySQL)...[/bold cyan]"):
            res_a = pipeline_a.run(query)
            res_b = pipeline_b.run(query, resolution_choice=choice)
    except Exception as err:
        console.print(f"\n[bold red]Error running comparative analysis:[/bold red] {err}")
        raise typer.Exit(code=1)

    # 1. Pipeline A Output
    console.print("\n[bold red]Pipeline A: Baseline Direct (Naive Guessing)[/bold red]")
    if res_a.generated_sql:
        console.print(Syntax(res_a.generated_sql, "sql", theme="monokai", line_numbers=False))
    if res_a.execution_result:
        _render_execution_result(res_a.execution_result)

    # 2. Pipeline B Output
    console.print("\n[bold green]Pipeline B: ClarifySQL (Active Ambiguity Resolution)[/bold green]")
    if res_b.is_ambiguous:
        console.print(f"[yellow]Resolved Ambiguity ({res_b.ambiguity_type.value}):[/yellow] {res_b.resolution.resolved_instruction if res_b.resolution else ''}")
    else:
        console.print("[green]Query was completely explicit and executed directly.[/green]")

    if res_b.generated_sql:
        console.print(Syntax(res_b.generated_sql, "sql", theme="monokai", line_numbers=False))
    if res_b.execution_result:
        _render_execution_result(res_b.execution_result)

    # Divergence analysis
    sql_a = (res_a.generated_sql or "").strip().lower()
    sql_b = (res_b.generated_sql or "").strip().lower()
    if res_b.is_ambiguous and sql_a != sql_b:
        console.print(Panel(
            "[bold red]CRITICAL DATA DIVERGENCE DETECTED:[/bold red]\n"
            "Pipeline A hallucinated an arbitrary metric without user consent.\n"
            "Pipeline B resolved semantic clarity, preventing silent reporting errors.",
            title="Integrity Audit",
            border_style="red"
        ))


@app.command()
def benchmark(
    provider: Optional[str] = typer.Option(None, "--provider", "-p", help="LLM Provider: 'ollama' or 'groq'"),
    dataset: str = typer.Option("benchmark/dataset.json", "--dataset", "-d", help="Path to benchmark JSON dataset")
):
    """
    Execute the 30-query verified benchmark suite and print comparative accuracy metrics.
    """
    catalog, schema, pipeline_a, pipeline_b = _get_pipeline_context(provider)

    runner = BenchmarkRunner(pipeline_a=pipeline_a, pipeline_b=pipeline_b, dataset_path=dataset)

    with console.status("[bold cyan]Executing 30-query verified benchmark suite...[/bold cyan]"):
        results, summary = runner.run()

    console.print("\n[bold green]ClarifySQL Benchmark Evaluation Results[/bold green]\n")
    console.print(summary.render_summary_table())


@app.command()
def schema():
    """
    Display the target PostgreSQL database schema and certified business metrics catalog.
    """
    catalog = load_semantic_catalog(settings.semantic_metrics_path)
    extractor = SchemaExtractor.from_semantic_catalog(catalog)
    db_schema = extractor.get_schema()

    console.print(Panel(db_schema.to_ddl_summary(), title="[bold green]Target Database Schema (DDL)[/bold green]"))
    console.print(Panel(catalog.format_metrics_for_prompt(), title="[bold cyan]Certified Metrics Catalog[/bold cyan]"))


def main():
    app()


if __name__ == "__main__":
    main()
