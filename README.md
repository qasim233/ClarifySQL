# ClarifySQL 🔍

> **Intelligent Natural Language to SQL with Active Ambiguity Resolution**

[![Python 3.12](https://img.shields.io/badge/Python-3.12%2B-blue.svg)](https://www.python.org/)
[![Database](https://img.shields.io/badge/PostgreSQL-Supabase-3ECF8E.svg)](https://supabase.com)
[![Pydantic](https://img.shields.io/badge/Validation-Pydantic_v2-red.svg)](https://docs.pydantic.dev/)
[![SQL Safety](https://img.shields.io/badge/Guardrails-sqlglot-orange.svg)](https://github.com/tobymao/sqlglot)
[![Testing](https://img.shields.io/badge/Tests-pytest-green.svg)](https://docs.pytest.org/)

---

## 📌 Problem Statement: The "Tutorial AI" vs. Production Gap

Standard Text-to-SQL pipelines work well on trivial, explicit questions (e.g., *"How many users registered in March 2024?"*). However, enterprise production systems fail catastrophically when presented with naturally underspecified, semantic, or ambiguous business questions (e.g., *"Show me last month's best customers"*).

When an ambiguous query is received, naive engines make arbitrary internal assumptions (hallucinating specific metrics like order counts vs. net spend vs. transaction frequency) and generate syntactically valid SQL that produces **confidently incorrect business numbers**. This leads to:
* **Silent Data Corruption:** High-stakes decisions made on miscalculated metrics.
* **Loss of Trust:** Stakeholders abandon self-service data tools after experiencing conflicting numbers.
* **Engineering Overhead:** Data teams spend hours debugging why an AI query conflicts with official financial reports.

**ClarifySQL** solves this problem by embedding a proactive **Clarification Engine** between natural language understanding and SQL synthesis. It identifies ambiguities across 4 core dimensions, prompts the user with structured, plain-English business options, and synthesizes verified, guardrailed SQL.

---

## 🏛️ System Architecture

```mermaid
flowchart TD
    UserQuery([User Natural Language Query]) --> ADCE[Ambiguity Detection & Classification Engine]
    
    subgraph Ambiguity_Resolution [Active Clarification Loop]
        ADCE -->|is_ambiguous = True| ICDR[Interactive Clarification Dispatcher]
        ICDR --> Options[Structured Business Options A / B / C]
        Options --> UserResponse[User Selection / Free-text]
        UserResponse --> AugmentedPrompt[Augmented Unambiguous Prompt]
    end
    
    ADCE -->|is_ambiguous = False| AugmentedPrompt
    
    subgraph Schema_and_Semantics [Semantic Layer & Schema]
        Catalog[(metrics.yaml / metrics.json)] --> Retriever[Hybrid FK-Aware Retriever]
        DB[(Supabase PostgreSQL)] --> Extractor[Schema Extractor]
        Extractor --> Retriever
    end
    
    Retriever --> PromptAssembly[Prompt Context Assembly]
    AugmentedPrompt --> PromptAssembly
    
    PromptAssembly --> LLM[LLM Synthesis: Ollama / Groq]
    LLM --> ASTGuard[AST Guardrails: sqlglot read-only]
    ASTGuard --> ExecutionSandbox[Sandboxed DB Execution: 10s Timeout, 500 Rows]
    ExecutionSandbox --> FinalResult([Verified Tabular Output])
```

---

## 📚 Engineering Handbook & Module Architecture

This section is written for software and data engineers seeking to understand, maintain, and extend the ClarifySQL codebase.

```
Text-to-SQL/
├── config/
│   ├── settings.py             # Global Pydantic settings & environment configuration
│   ├── metrics.yaml            # Certified business metrics & table definitions (YAML)
│   └── metrics.json            # Certified business metrics & table definitions (JSON)
├── clarifysql/
│   ├── schema/
│   │   ├── semantic_layer.py   # Semantic layer parser, validator & prompt formatters
│   │   ├── extractor.py        # Database schema introspection & DDL caching
│   │   └── retriever.py        # Baseline Lexical & Hybrid FK-Aware schema retrievers
│   ├── ambiguity/
│   │   ├── models.py           # Ambiguity Pydantic schemas (4 dimensions, options, check results)
│   │   ├── prompts.py          # System prompts, few-shot examples & JSON output schemas
│   │   └── detector.py         # Ambiguity classifier, option resolver & prompt compiler
│   ├── llm/
│   │   ├── base.py             # Abstract base LLM interface (text & structured generation)
│   │   ├── ollama_client.py    # Local Ollama client with JSON schema enforcement (RTX 3070 8GB)
│   │   ├── groq_client.py      # Production Groq client (llama-3.3-70b-versatile)
│   │   └── factory.py          # Provider factory with dynamic toggle
│   ├── generator/              # SQL synthesis & AST guardrails (Module 5)
│   ├── execution/              # Sandboxed PostgreSQL execution & auto-retry (Module 6)
│   ├── pipeline/               # Comparative evaluation pipelines (Module 7)
│   └── cli/                    # Rich interactive terminal interface (Module 8)
├── tests/
│   ├── test_semantic_layer.py  # Unit tests for Module 1
│   ├── test_schema_retriever.py# Unit tests for Module 2
│   ├── test_ambiguity.py       # Unit tests for Module 3
│   └── test_llm_clients.py     # Unit tests for Module 4
```

---

### Module 1: Project Foundation, Configuration & Dual Semantic Layer (REQ-SISL-02)

The semantic layer bridges raw database column names and high-level enterprise business logic.

* **[`config/settings.py`](file:///home/tensor/Documents/Text-to-SQL/config/settings.py):**
  * Built using `pydantic-settings.BaseSettings`.
  * Loads from `.env` or system environment variables.
  * Configures PostgreSQL connection URL (`DATABASE_URL`), active LLM provider toggle (`LLM_PROVIDER`), Ollama host and model (`llama3.1:8b`), Groq API key and model (`llama-3.3-70b-versatile`), execution sandbox limits (`statement_timeout_ms = 10000`, `max_result_rows = 500`), and semantic catalog file path.
* **[`config/metrics.yaml`](file:///home/tensor/Documents/Text-to-SQL/config/metrics.yaml) & [`config/metrics.json`](file:///home/tensor/Documents/Text-to-SQL/config/metrics.json):**
  * Contains declared definitions for eCommerce tables (`customers`, `orders`, `payments`).
  * Maps business synonyms (e.g. `shoppers`, `purchases`, `revenue`, `spending`).
  * Declares certified business metric formulas: `gross_revenue`, `net_revenue`, `completed_orders`, `active_customer`, `average_order_value`, and `top_customers`.
* **[`clarifysql/schema/semantic_layer.py`](file:///home/tensor/Documents/Text-to-SQL/clarifysql/schema/semantic_layer.py):**
  * Defines Pydantic validation models: `TableMetadata`, `MetricDefinition`, and `SemanticCatalog`.
  * Seamlessly loads and auto-detects either YAML or JSON catalogs.
  * Exposes prompt helpers `format_metrics_for_prompt()` and `format_schema_for_prompt()` for direct LLM injection.
* **[`tests/test_semantic_layer.py`](file:///home/tensor/Documents/Text-to-SQL/tests/test_semantic_layer.py):**
  * Verifies YAML and JSON parsing, schema parity between formats, synonym lookups, prompt formatting, and configuration defaults.

---

### Module 2: Schema Extraction & Retrievers (REQ-SISL-01, REQ-SISL-03)

Ensures the LLM receives clean, accurate DDL without wasting context tokens or dropping critical join tables.

* **[`clarifysql/schema/extractor.py`](file:///home/tensor/Documents/Text-to-SQL/clarifysql/schema/extractor.py):**
  * Models: `ColumnSchema`, `TableSchema`, and `DatabaseSchema`.
  * Introspects live PostgreSQL databases by querying `information_schema.tables`, `columns`, `table_constraints`, `key_column_usage`, and `constraint_column_usage`.
  * Provides `from_semantic_catalog` factory for offline development/testing and `to_ddl_summary()` for DDL generation.
* **[`clarifysql/schema/retriever.py`](file:///home/tensor/Documents/Text-to-SQL/clarifysql/schema/retriever.py):**
  * `BaseSchemaRetriever`: Abstract base contract for table selection.
  * `LexicalSchemaRetriever` (Baseline): Tokenizes query and scans against table names, column names, and semantic layer synonyms/metrics.
  * `HybridFKSchemaRetriever` (Recommended):
    1. **Adaptive Threshold:** If total tables in the database $\le 10$ (e.g. our 3-table setup), all tables are automatically injected (zero risk of false-positive table pruning).
    2. **Foreign Key Graph Closure:** For larger schemas ($> 10$ tables), computes an undirected FK adjacency graph and uses Breadth-First Search (BFS) to find intermediate bridge tables between selected tables (e.g., ensuring `orders` is retained when a query mentions `customers` and `payments`).
* **[`tests/test_schema_retriever.py`](file:///home/tensor/Documents/Text-to-SQL/tests/test_schema_retriever.py):**
  * Tests DDL rendering, lexical keyword matching, synonym resolution, adaptive threshold auto-injection, and the multi-table FK bridge closure recovery test.

---

### Module 3: Ambiguity Detection & Classification Engine (ADCE) + Resolution Loop (ICDR)

Intercepts subjective, underspecified questions before SQL generation and interacts with the user.

* **[`clarifysql/ambiguity/models.py`](file:///home/tensor/Documents/Text-to-SQL/clarifysql/ambiguity/models.py):**
  * `AmbiguityDimension` Enum covering the 4 core dimensions:
    1. `METRIC`: Subjective business terms (*"best"*, *"top"*, *"active"*).
    2. `TEMPORAL`: Unanchored dates or multiple timestamp columns (`order_date` vs. `payment_date`).
    3. `SCHEMA_ENTITY`: Overlapping concepts (order count vs. payment monetary sum).
    4. `GRANULARITY`: Aggregation levels (summary total vs. line-item list).
  * `ClarificationOption`: Business-friendly `label` and `description` (strictly zero raw SQL in user-facing text) + `implied_sql_logic`.
  * `AmbiguityCheckResult`: Structured output model strictly validated with Pydantic v2. Enforces between 2 and 4 options with unique IDs when `is_ambiguous=True`, and empty options when `is_ambiguous=False`.
  * `ClarificationResolution`: Captures user choices or free-text preference.
* **[`clarifysql/ambiguity/prompts.py`](file:///home/tensor/Documents/Text-to-SQL/clarifysql/ambiguity/prompts.py):**
  * Provides `AMBIGUITY_SYSTEM_PROMPT` and comprehensive few-shot examples illustrating unambiguous queries, metric ambiguities, temporal ambiguities, and schema entity ambiguities.
* **[`clarifysql/ambiguity/detector.py`](file:///home/tensor/Documents/Text-to-SQL/clarifysql/ambiguity/detector.py):**
  * `AmbiguityDetector`:
    * `build_classification_prompt()`: Synthesizes schema DDL, metrics catalog, and few-shots.
    * `parse_classification_response()`: Robust JSON parser handling raw dicts, JSON strings, and Markdown-fenced responses.
    * `resolve_clarification()`: Resolves user choice by letter (`"A"`), numeric index (`"1"`), or custom free text.
    * `build_augmented_prompt()`: Compiles an augmented, unambiguous prompt for downstream SQL synthesis.
* **[`tests/test_ambiguity.py`](file:///home/tensor/Documents/Text-to-SQL/tests/test_ambiguity.py):**
  * Tests validation rules (2–4 options, unique IDs, explicit query compliance), prompt assembly, JSON parsing, option resolution, and prompt augmentation.

---

### Module 4: Dual LLM Client Abstraction (Ollama & Groq)

Provides a unified interface for local GPU testing and cloud production inference.

* **[`clarifysql/llm/base.py`](file:///home/tensor/Documents/Text-to-SQL/clarifysql/llm/base.py):**
  * `BaseLLMClient`: Abstract interface defining `generate()` for free text and `generate_structured()` for Pydantic schema validation.
* **[`clarifysql/llm/ollama_client.py`](file:///home/tensor/Documents/Text-to-SQL/clarifysql/llm/ollama_client.py):**
  * Connects to local Ollama via HTTP API (`/api/chat`).
  * Optimized for local GPU execution (e.g., RTX 3070 8GB VRAM with `llama3.1:8b` or `qwen2.5-coder:7b`).
  * Enforces structured JSON output via Ollama's native JSON schema parameter and provides clear diagnostics if the Ollama daemon is offline.
* **[`clarifysql/llm/groq_client.py`](file:///home/tensor/Documents/Text-to-SQL/clarifysql/llm/groq_client.py):**
  * Production cloud client using the `groq` SDK (`llama-3.3-70b-versatile`).
  * Enforces `response_format={"type": "json_object"}` and validates response strings with Pydantic schemas.
* **[`clarifysql/llm/factory.py`](file:///home/tensor/Documents/Text-to-SQL/clarifysql/llm/factory.py):**
  * `get_llm_client()`: Factory function reading `settings.llm_provider` or runtime override to return the appropriate client.
* **[`tests/test_llm_clients.py`](file:///home/tensor/Documents/Text-to-SQL/tests/test_llm_clients.py):**
  * Tests provider selection, mocked Ollama text and structured output, connection error handling, Groq API key validation, and mocked Groq completions.

---

## 🛠️ Setup & Installation

### 1. Clone & Set Up Virtual Environment
```bash
git clone https://github.com/qasim233/ClarifySQL.git
cd ClarifySQL

# Create and activate Python 3.12 virtual environment
python3.12 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Configure Environment Variables
```bash
cp .env.example .env
```
Edit `.env`:
* For local testing on an 8GB GPU machine (RTX 3070):
  ```env
  LLM_PROVIDER=ollama
  OLLAMA_BASE_URL=http://localhost:11434
  OLLAMA_MODEL=llama3.1:8b
  ```
* For cloud production with Groq:
  ```env
  LLM_PROVIDER=groq
  GROQ_API_KEY=gsk_your_api_key_here
  GROQ_MODEL=llama-3.3-70b-versatile
  ```

### 3. Run Test Suite
```bash
pytest -v tests/
```
