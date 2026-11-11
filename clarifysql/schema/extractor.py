from typing import Dict, List, Optional
import psycopg2
from psycopg2.extras import RealDictCursor
from pydantic import BaseModel, Field
from clarifysql.schema.semantic_layer import SemanticCatalog


class ColumnSchema(BaseModel):
    name: str
    data_type: str
    is_nullable: bool = True
    comment: Optional[str] = None


class TableSchema(BaseModel):
    name: str
    columns: Dict[str, ColumnSchema] = Field(default_factory=dict)
    primary_key: Optional[str] = None
    foreign_keys: Dict[str, str] = Field(
        default_factory=dict,
        description="Maps foreign key column name to referenced table.column, e.g. customer_id -> customers.id"
    )
    description: Optional[str] = None


class DatabaseSchema(BaseModel):
    tables: Dict[str, TableSchema] = Field(default_factory=dict)

    def get_table(self, name: str) -> Optional[TableSchema]:
        return self.tables.get(name)

    def table_names(self) -> List[str]:
        return sorted(list(self.tables.keys()))

    def to_ddl_summary(self, table_names: Optional[List[str]] = None) -> str:
        """Render a concise DDL-style schema summary for LLM prompt context."""
        targets = table_names if table_names is not None else self.table_names()
        chunks = []
        for t_name in targets:
            table = self.tables.get(t_name)
            if not table:
                continue
            lines = [f"CREATE TABLE {t_name} ("]
            col_lines = []
            for col_name, col in table.columns.items():
                pk_suffix = " PRIMARY KEY" if table.primary_key == col_name else ""
                fk_suffix = f" REFERENCES {table.foreign_keys[col_name]}" if col_name in table.foreign_keys else ""
                col_lines.append(f"    {col_name} {col.data_type}{pk_suffix}{fk_suffix}")
            lines.append(",\n".join(col_lines))
            lines.append(");")
            chunks.append("\n".join(lines))
        return "\n\n".join(chunks)


class SchemaExtractor:
    """Extracts and caches PostgreSQL database schema."""

    def __init__(self, connection_url: Optional[str] = None):
        self.connection_url = connection_url
        self._cached_schema: Optional[DatabaseSchema] = None

    @classmethod
    def from_semantic_catalog(cls, catalog: SemanticCatalog) -> "SchemaExtractor":
        """Build a SchemaExtractor backed by a SemanticCatalog (useful for testing or offline dev)."""
        extractor = cls()
        tables: Dict[str, TableSchema] = {}
        for t_name, t_meta in catalog.tables.items():
            cols = {
                col_name: ColumnSchema(name=col_name, data_type="varchar", comment=col_desc)
                for col_name, col_desc in t_meta.columns.items()
            }
            tables[t_name] = TableSchema(
                name=t_name,
                columns=cols,
                primary_key=t_meta.primary_key,
                foreign_keys=t_meta.foreign_keys,
                description=t_meta.description
            )
        extractor._cached_schema = DatabaseSchema(tables=tables)
        return extractor

    def extract_from_postgres(self, connection_url: Optional[str] = None) -> DatabaseSchema:
        """Introspect active PostgreSQL information_schema."""
        url = connection_url or self.connection_url
        if not url:
            raise ValueError("No PostgreSQL connection URL provided.")

        tables: Dict[str, TableSchema] = {}

        with psycopg2.connect(url) as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # 1. Fetch tables
                cur.execute("""
                    SELECT table_name 
                    FROM information_schema.tables 
                    WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
                    ORDER BY table_name;
                """)
                for row in cur.fetchall():
                    t_name = row["table_name"]
                    tables[t_name] = TableSchema(name=t_name)

                # 2. Fetch columns and data types
                cur.execute("""
                    SELECT table_name, column_name, data_type, is_nullable
                    FROM information_schema.columns
                    WHERE table_schema = 'public'
                    ORDER BY table_name, ordinal_position;
                """)
                for row in cur.fetchall():
                    t_name = row["table_name"]
                    if t_name in tables:
                        tables[t_name].columns[row["column_name"]] = ColumnSchema(
                            name=row["column_name"],
                            data_type=row["data_type"],
                            is_nullable=(row["is_nullable"] == "YES")
                        )

                # 3. Fetch Primary Keys
                cur.execute("""
                    SELECT kcu.table_name, kcu.column_name
                    FROM information_schema.table_constraints tc
                    JOIN information_schema.key_column_usage kcu
                        ON tc.constraint_name = kcu.constraint_name
                        AND tc.table_schema = kcu.table_schema
                    WHERE tc.constraint_type = 'PRIMARY KEY'
                        AND tc.table_schema = 'public';
                """)
                for row in cur.fetchall():
                    t_name = row["table_name"]
                    if t_name in tables:
                        tables[t_name].primary_key = row["column_name"]

                # 4. Fetch Foreign Keys
                cur.execute("""
                    SELECT
                        kcu.table_name AS src_table,
                        kcu.column_name AS src_col,
                        ccu.table_name AS ref_table,
                        ccu.column_name AS ref_col
                    FROM information_schema.table_constraints AS tc
                    JOIN information_schema.key_column_usage AS kcu
                        ON tc.constraint_name = kcu.constraint_name
                        AND tc.table_schema = kcu.table_schema
                    JOIN information_schema.constraint_column_usage AS ccu
                        ON ccu.constraint_name = tc.constraint_name
                        AND ccu.table_schema = tc.table_schema
                    WHERE tc.constraint_type = 'FOREIGN KEY'
                        AND tc.table_schema = 'public';
                """)
                for row in cur.fetchall():
                    src_t = row["src_table"]
                    if src_t in tables:
                        tables[src_t].foreign_keys[row["src_col"]] = f"{row['ref_table']}.{row['ref_col']}"

        self._cached_schema = DatabaseSchema(tables=tables)
        return self._cached_schema

    def get_schema(self) -> DatabaseSchema:
        """Return cached schema or introspect if needed."""
        if self._cached_schema:
            return self._cached_schema
        if self.connection_url:
            return self.extract_from_postgres(self.connection_url)
        raise ValueError("Schema not extracted and no connection URL configured.")
