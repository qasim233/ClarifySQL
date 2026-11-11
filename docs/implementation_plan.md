# Implementation Plan: ClarifySQL MVP

ClarifySQL is an enterprise-grade Text-to-SQL system with active ambiguity resolution. It intercepts underspecified or ambiguous queries before SQL generation, resolves ambiguities via structured user interactions, guarantees AST-level read-only SQL safety, and measures effectiveness using a comparative evaluation framework (Baseline vs. ClarifySQL).

---

## User Review Required

> [!IMPORTANT]
> **LLM Provider Strategy**: The system will support **Ollama** for local execution (optimized for RTX 3070 8GB VRAM with models like `llama3.1:8b` or `qwen2.5-coder:7b`) and **Groq** (`llama-3.3-70b-versatile`) for production. The LLM client will be fully abstracted so you can switch with a single config flag or environment variable (`LLM_PROVIDER=ollama` or `LLM_PROVIDER=groq`).

> [!IMPORTANT]
> **Database**: Supabase PostgreSQL will be used as the target database. We will provide connection configuration via standard PostgreSQL environment variables (`DATABASE_URL` or `SUPABASE_DB_URL`). Additionally, we will provide a seed script with sample data for `customers`, `orders`, and `payments` with realistic edge cases (different order statuses, payment statuses, and timestamps) so ambiguity scenarios can be fully exercised.

---

## Recommendation & Analysis: Schema Filtering Strategy (PRD REQ-SISL-03)

You requested an explanation, trade-offs, and suggestion regarding **Schema Filtering / Table Pruning** (Vector vs. Keyword vs. Hybrid):

### Evaluation of Options

| Strategy | Advantages | Trade-offs & Risks | Recommendation |
| :--- | :--- | :--- | :--- |
| **Pure Vector Embeddings** (e.g., ChromaDB, sentence-transformers) | Captures semantic synonymy (e.g., "shopper" $\rightarrow$ `customers`). | Heavy dependencies (Torch/Chroma), 100–300ms latency overhead, and **Join Bridge Dropping**: for "total spend per customer", embeddings might pick `customers` and `payments`, but drop `orders` (the join bridge), breaking the query! | Not recommended as sole strategy |
| **Lexical / Keyword Matching** | Instant (<1ms), zero external dependencies, deterministic. | Fails if the user uses business terms not present in the table/column names unless backed by synonyms. | Good baseline, but incomplete alone |
| **Hybrid FK-Aware Retriever with Adaptive Threshold (Recommended)** | **1.** If total tables $\le 10$ (our 3-table Supabase setup), auto-injects all tables (0 risk of missed tables).<br>**2.** For larger schemas, combines keyword/synonym lookup from `metrics.yaml` with **Foreign-Key Graph Closure** (guaranteeing join bridges like `orders` are never pruned).<br>**3.** Pluggable vector store interface if scaling to 100+ tables. | Requires graph traversal for FK closure (already lightweight and native in Python). | **Recommended** |

---

## Architecture & Proposed File Structure

```
Text-to-SQL/
├── config/
│   ├── settings.py             # Pydantic BaseSettings (DB URL, LLM Provider, timeouts)
│   ├── metrics.yaml            # Semantic layer formulas and definitions (YAML)
│   └── metrics.json            # Semantic layer mirror / alternative (JSON)
├── clarifysql/
│   ├── __init__.py
│   ├── llm/
│   │   ├── base.py             # Abstract LLM client interface
│   │   ├── ollama_client.py    # Local Ollama client (structured output support)
│   │   ├── groq_client.py      # Groq client (using llama-3.3-70b)
│   │   └── factory.py          # Provider factory (Ollama vs. Groq)
│   ├── schema/
│   │   ├── extractor.py        # Supabase PostgreSQL schema & constraint introspection
│   │   ├── semantic_layer.py   # Loader for metrics.yaml and metrics.json
│   │   └── retriever.py        # Hybrid schema pruner with FK-graph closure
│   ├── ambiguity/
│   │   ├── models.py           # Pydantic models: AmbiguityCheckResult, ClarificationOption
│   │   └── detector.py         # 4-dimension ambiguity classifier (Metric, Temporal, Entity, Granularity)
│   ├── generator/
│   │   ├── sql_generator.py    # Prompt synthesis & PostgreSQL generation
│   │   └── guardrails.py       # AST validator using sqlglot (read-only enforcement)
│   ├── execution/
│   │   ├── sandbox.py          # Sandboxed PostgreSQL execution (timeout, row limit, auto-retry)
│   │   └── models.py           # ExecutionResult model
│   ├── pipeline/
│   │   ├── direct_pipeline.py  # Pipeline A (Baseline naive text-to-SQL)
│   │   └── clarifysql_pipeline.py # Pipeline B (Ambiguity detection + Resolution + SQL)
│   └── cli/
│       └── app.py              # Rich terminal interface (Typer/Rich) with interactive tables & menus
├── benchmark/
│   ├── dataset.json            # 30-query verified benchmark (clean vs. ambiguous queries)
│   ├── runner.py               # Comparative evaluation runner (Pipeline A vs. Pipeline B)
│   └── metrics.py              # Execution Accuracy (EX), Ambiguity Precision/Recall, Divergence
├── scripts/
│   ├── seed_supabase.py        # DDL and sample data seed script for Supabase
│   └── run_benchmark.py        # CLI entry point to run comparative benchmark
├── tests/
│   ├── test_ambiguity.py       # Unit tests for ambiguity classification
│   ├── test_guardrails.py      # Unit tests for AST sqlglot read-only blocking
│   ├── test_semantic_layer.py  # Tests for YAML/JSON metric loader
│   └── test_execution.py       # Tests for execution sandbox and self-correction
├── pyproject.toml / requirements.txt
└── .env.example
```

---

## Proposed Changes Component by Component

### 1. Configuration & Dependency Layer
#### [NEW] [requirements.txt](file:///home/tensor/Documents/Text-to-SQL/requirements.txt) / [pyproject.toml](file:///home/tensor/Documents/Text-to-SQL/pyproject.toml)
* Core libraries: `pydantic>=2.0`, `pydantic-settings`, `sqlglot>=20.0`, `psycopg2-binary>=2.9`, `rich>=13.0`, `typer>=0.9`, `pyyaml>=6.0`, `httpx>=0.25`, `groq>=0.9`, `tabulate>=0.9`, `pytest>=7.4`.

#### [NEW] [.env.example](file:///home/tensor/Documents/Text-to-SQL/.env.example) & [config/settings.py](file:///home/tensor/Documents/Text-to-SQL/config/settings.py)
* Environment parameters:
  * `DATABASE_URL`: Supabase connection URI (`postgresql://postgres:[password]@[host]:5432/postgres`)
  * `LLM_PROVIDER`: `ollama` or `groq` (default: `ollama`)
  * `OLLAMA_BASE_URL`: default `http://localhost:11434`
  * `OLLAMA_MODEL`: default `llama3.1:8b` (or `qwen2.5-coder:7b`)
  * `GROQ_API_KEY`: Groq API key for production
  * `GROQ_MODEL`: default `llama-3.3-70b-versatile`
  * `STATEMENT_TIMEOUT_MS`: 10000 (10 seconds)
  * `MAX_RESULT_ROWS`: 500

---

### 2. LLM Abstraction Module
#### [NEW] [clarifysql/llm/base.py](file:///home/tensor/Documents/Text-to-SQL/clarifysql/llm/base.py)
* Abstract base class defining `generate(prompt: str) -> str` and `generate_structured(prompt: str, response_model: Type[BaseModel]) -> BaseModel`.

#### [NEW] [clarifysql/llm/ollama_client.py](file:///home/tensor/Documents/Text-to-SQL/clarifysql/llm/ollama_client.py)
* Uses HTTP API (`/api/chat`) with `format="json"` or Ollama SDK, passing Pydantic JSON schema to guarantee structured outputs on RTX 3070 local inference.

#### [NEW] [clarifysql/llm/groq_client.py](file:///home/tensor/Documents/Text-to-SQL/clarifysql/llm/groq_client.py)
* Uses Groq SDK with JSON mode / tool calling for structured JSON output enforcement using `llama-3.3-70b-versatile`.

---

### 3. Database & Semantic Schema Layer
#### [NEW] [scripts/seed_supabase.py](file:///home/tensor/Documents/Text-to-SQL/scripts/seed_supabase.py)
* DDL statements and realistic seed dataset for Supabase with the three tables:
  * `customers`: `id`, `name`, `email`, `signup_date`
  * `orders`: `id`, `customer_id`, `order_date`, `status` (`pending`, `completed`, `cancelled`, `refunded`)
  * `payments`: `id`, `order_id`, `amount`, `payment_status` (`successful`, `failed`, `refunded`), `payment_date`
* Realistic timestamp and amount distributions designed to trigger temporal, metric, and join ambiguities.

#### [NEW] [config/metrics.yaml](file:///home/tensor/Documents/Text-to-SQL/config/metrics.yaml) & [config/metrics.json](file:///home/tensor/Documents/Text-to-SQL/config/metrics.json)
* Canonical certified enterprise metrics, e.g.:
  * `gross_revenue`: `SUM(payments.amount) WHERE payments.payment_status = 'successful'`
  * `net_revenue`: `SUM(payments.amount) WHERE payments.payment_status = 'successful' AND orders.status != 'refunded'`
  * `active_customer`: `customers with at least 1 completed order in the last 90 days`
  * `churned_customer`: `customers with no orders in over 180 days`

#### [NEW] [clarifysql/schema/extractor.py](file:///home/tensor/Documents/Text-to-SQL/clarifysql/schema/extractor.py)
* Introspects tables, columns, data types, primary keys, foreign keys, and comments from Supabase PostgreSQL information schema, caching results.

#### [NEW] [clarifysql/schema/retriever.py](file:///home/tensor/Documents/Text-to-SQL/clarifysql/schema/retriever.py)
* Implements the **Hybrid FK-Aware Retriever**: auto-includes all tables if $\le 10$, and for large schemas retains queried tables + foreign key paths.

---

### 4. Ambiguity Detection & Clarification Loop
#### [NEW] [clarifysql/ambiguity/models.py](file:///home/tensor/Documents/Text-to-SQL/clarifysql/ambiguity/models.py)
* Strict Pydantic models:
  * `AmbiguityDimension`: Enum (`METRIC`, `TEMPORAL`, `SCHEMA_ENTITY`, `GRANULARITY`)
  * `ClarificationOption`: `id` (e.g. "A"), `label`, `description`, `implied_sql_logic`
  * `AmbiguityCheckResult`: `is_ambiguous: bool`, `ambiguity_type: Optional[AmbiguityDimension]`, `explanation: Optional[str]`, `options: List[ClarificationOption]` (2 to 4 options)

#### [NEW] [clarifysql/ambiguity/detector.py](file:///home/tensor/Documents/Text-to-SQL/clarifysql/ambiguity/detector.py)
* Evaluates incoming prompt against cached schema + semantic metrics catalog using structured LLM inference.

---

### 5. SQL Generation & Guardrailed Execution Sandbox
#### [NEW] [clarifysql/generator/guardrails.py](file:///home/tensor/Documents/Text-to-SQL/clarifysql/generator/guardrails.py)
* Uses `sqlglot` to parse generated SQL AST:
  * Ensures expression is strictly a `Select` or `Union` of `Select`s.
  * Rejects statements containing `Insert`, `Update`, `Delete`, `Drop`, `Alter`, `Truncate`, `Create`, `Execute`.
  * Verifies dialect compatibility with PostgreSQL.

#### [NEW] [clarifysql/execution/sandbox.py](file:///home/tensor/Documents/Text-to-SQL/clarifysql/execution/sandbox.py)
* Executes via `psycopg2` using read-only session:
  * `SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY;`
  * `SET statement_timeout = 10000;` (10s limit)
  * Truncates rows to 500 max.
  * Auto-retry self-correction loop (max 2 retries) on SQL error.

---

### 6. Interactive Rich CLI & Pipelines
#### [NEW] [clarifysql/pipeline/direct_pipeline.py](file:///home/tensor/Documents/Text-to-SQL/clarifysql/pipeline/direct_pipeline.py)
* Baseline pipeline: User Query $\rightarrow$ Direct SQL $\rightarrow$ Execution (does not resolve ambiguities).

#### [NEW] [clarifysql/pipeline/clarifysql_pipeline.py](file:///home/tensor/Documents/Text-to-SQL/clarifysql/pipeline/clarifysql_pipeline.py)
* ClarifySQL pipeline: User Query $\rightarrow$ Ambiguity Check $\rightarrow$ Resolution (interactive or pre-selected) $\rightarrow$ Synthesized SQL $\rightarrow$ Guardrail $\rightarrow$ Execution.

#### [NEW] [clarifysql/cli/app.py](file:///home/tensor/Documents/Text-to-SQL/clarifysql/cli/app.py)
* Rich terminal UI:
  * Beautiful spinners and status messages.
  * Formatted tables for ambiguity clarification options with options A, B, C, D and custom input prompt.
  * Clean result tables rendered with column types, row counts, and execution latency.

---

### 7. 30-Query Benchmark & Evaluation Framework
#### [NEW] [benchmark/dataset.json](file:///home/tensor/Documents/Text-to-SQL/benchmark/dataset.json)
* 30 authored verified queries covering:
  * 10 Unambiguous explicit queries (e.g. *"Show all customers who signed up in 2024"*, *"Count orders with status completed"*)
  * 7 Metric ambiguities (e.g. *"Who are our top customers?"*, *"Show high-value orders"*)
  * 5 Temporal ambiguities (e.g. *"Show revenue last month"* — order_date vs payment_date)
  * 4 Schema & Entity ambiguities (e.g. *"What was the sales volume?"* — order count vs payment amount sum)
  * 4 Granularity ambiguities (e.g. *"Show sales by customer"* — total amount vs order list)
* Contains ground-truth SQL, simulated canonical resolution, and expected outcome for both pipelines.

#### [NEW] [benchmark/runner.py](file:///home/tensor/Documents/Text-to-SQL/benchmark/runner.py) & [scripts/run_benchmark.py](file:///home/tensor/Documents/Text-to-SQL/scripts/run_benchmark.py)
* Runs both Pipeline A and Pipeline B across all 30 queries, calculating:
  * Execution Accuracy (EX)
  * Ambiguity Detection Precision, Recall, and False-Positive Interception Rate
  * Semantic Divergence Rate (quantifying where Pipeline A hallucinated vs. Pipeline B verified truth)
  * Renders a comparative summary table.

---

## Verification Plan

### Automated Tests
* Unit tests: `pytest tests/`
  * `test_guardrails.py`: Test AST validator against malicious or modifying SQL (`DROP TABLE`, `UPDATE`, `INSERT`, `SELECT ...; DELETE FROM ...`).
  * `test_semantic_layer.py`: Test parsing both `metrics.yaml` and `metrics.json`.
  * `test_models.py`: Test Pydantic schema validation for `AmbiguityCheckResult`.
* Comparative Evaluation Benchmark:
  * `python scripts/run_benchmark.py --provider ollama` (or `--provider groq`) to verify all 30 benchmark queries.

### Manual Verification
* Run interactive CLI:
  * Test clean query: `clarifysql ask "List all customers signed up after 2024-01-01"` (verifies 0 false positive interruption).
  * Test ambiguous query: `clarifysql ask "Who are our best customers?"` (verifies clarification prompt with options A/B/C, option selection, and final SQL execution).
