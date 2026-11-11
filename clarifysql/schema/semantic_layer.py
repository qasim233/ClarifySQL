import json
from pathlib import Path
from typing import Dict, List, Optional, Union
import yaml
from pydantic import BaseModel, Field


class TableMetadata(BaseModel):
    """Metadata describing a database table in the semantic layer."""
    description: str
    synonyms: List[str] = Field(default_factory=list)
    primary_key: Optional[str] = None
    foreign_keys: Dict[str, str] = Field(default_factory=dict)
    columns: Dict[str, str] = Field(default_factory=dict)


class MetricDefinition(BaseModel):
    """Standardized business metric definition."""
    name: str
    description: str
    sql_expression: str
    filters: Optional[str] = None
    required_tables: List[str] = Field(default_factory=list)


class SemanticCatalog(BaseModel):
    """Semantic catalog containing certified metrics and table definitions."""
    version: str = "1.0.0"
    tables: Dict[str, TableMetadata] = Field(default_factory=dict)
    metrics: Dict[str, MetricDefinition] = Field(default_factory=dict)

    def get_metric(self, metric_key: str) -> Optional[MetricDefinition]:
        """Retrieve a certified metric definition by key."""
        return self.metrics.get(metric_key)

    def get_table(self, table_name: str) -> Optional[TableMetadata]:
        """Retrieve table metadata by name."""
        return self.tables.get(table_name)

    def find_tables_by_term(self, term: str) -> List[str]:
        """Find table names matching a search term or synonym."""
        term_clean = term.lower().strip()
        matched = set()

        for table_name, meta in self.tables.items():
            if term_clean == table_name.lower():
                matched.add(table_name)
            elif term_clean in [s.lower() for s in meta.synonyms]:
                matched.add(table_name)
            elif any(term_clean == col.lower() for col in meta.columns.keys()):
                matched.add(table_name)

        return sorted(list(matched))

    def format_metrics_for_prompt(self) -> str:
        """Format metrics into a clear markdown string for LLM prompts."""
        if not self.metrics:
            return "No certified business metrics defined."

        lines = ["### Certified Business Metrics Catalog:"]
        for key, m in self.metrics.items():
            filter_str = f" WHERE {m.filters}" if m.filters else ""
            lines.append(
                f"- **{m.name}** (`{key}`): {m.description}\n"
                f"  - Formula: `{m.sql_expression}{filter_str}`\n"
                f"  - Relevant Tables: {', '.join(m.required_tables)}"
            )
        return "\n".join(lines)

    def format_schema_for_prompt(self, table_names: Optional[List[str]] = None) -> str:
        """Format table schema descriptions for LLM prompts."""
        selected_tables = table_names if table_names is not None else list(self.tables.keys())
        lines = ["### Target Database Schema:"]

        for t_name in selected_tables:
            table = self.tables.get(t_name)
            if not table:
                continue
            lines.append(f"\nTable: `{t_name}` - {table.description}")
            if table.primary_key:
                lines.append(f"  - Primary Key: `{table.primary_key}`")
            if table.foreign_keys:
                fks = [f"`{col}` -> `{ref}`" for col, ref in table.foreign_keys.items()]
                lines.append(f"  - Foreign Keys: {', '.join(fks)}")
            lines.append("  - Columns:")
            for col, desc in table.columns.items():
                lines.append(f"    - `{col}`: {desc}")

        return "\n".join(lines)


def load_semantic_catalog(file_path: Union[str, Path]) -> SemanticCatalog:
    """
    Load and parse semantic catalog from YAML or JSON.
    Supports .yaml, .yml, and .json extensions.
    """
    path = Path(file_path)
    if not path.is_file():
        raise FileNotFoundError(f"Semantic catalog file not found: {path.resolve()}")

    content = path.read_text(encoding="utf-8")
    ext = path.suffix.lower()

    if ext in (".yaml", ".yml"):
        data = yaml.safe_load(content)
    elif ext == ".json":
        data = json.loads(content)
    else:
        raise ValueError(
            f"Unsupported file format '{ext}'. Semantic catalog must be YAML (.yaml, .yml) or JSON (.json)."
        )

    if not isinstance(data, dict):
        raise ValueError(f"Invalid catalog structure in {path}: root must be a mapping/dict.")

    return SemanticCatalog.model_validate(data)
