import re
from abc import ABC, abstractmethod
from collections import deque
from typing import Dict, List, Optional, Set
from clarifysql.schema.extractor import DatabaseSchema
from clarifysql.schema.semantic_layer import SemanticCatalog


class BaseSchemaRetriever(ABC):
    """Abstract base retriever for schema pruning and table selection."""

    @abstractmethod
    def retrieve_tables(self, query: str, schema: DatabaseSchema) -> List[str]:
        """Given a natural language query and database schema, return relevant table names."""
        pass


class LexicalSchemaRetriever(BaseSchemaRetriever):
    """
    Baseline schema retriever using lexical keyword matching and synonym expansion.
    Scans query tokens against table names, column names, and semantic layer synonyms.
    """

    def __init__(self, catalog: Optional[SemanticCatalog] = None):
        self.catalog = catalog

    def _tokenize(self, text: str) -> Set[str]:
        tokens = re.findall(r"\b[a-zA-Z0-9_]+\b", text.lower())
        return set(tokens)

    def retrieve_tables(self, query: str, schema: DatabaseSchema) -> List[str]:
        q_lower = query.lower()
        tokens = self._tokenize(query)
        matched_tables: Set[str] = set()

        for t_name, table in schema.tables.items():
            t_lower = t_name.lower()
            # 1. Direct table name match
            if t_lower in tokens:
                matched_tables.add(t_name)
                continue

            # 2. Column name match
            for col_name in table.columns.keys():
                if col_name.lower() in tokens:
                    matched_tables.add(t_name)
                    break

            # 3. Semantic layer synonym match
            if self.catalog:
                cat_table = self.catalog.get_table(t_name)
                if cat_table:
                    for syn in cat_table.synonyms:
                        if syn.lower() in tokens:
                            matched_tables.add(t_name)
                            break

        # 4. Semantic metrics match: check if full metric phrase or metric key appears in query
        if self.catalog:
            for metric_key, metric in self.catalog.metrics.items():
                if metric_key.lower() in q_lower or metric.name.lower() in q_lower:
                    for req_t in metric.required_tables:
                        if req_t in schema.tables:
                            matched_tables.add(req_t)

        # Fallback: if no tables matched, return all tables to prevent empty prompt
        if not matched_tables:
            return schema.table_names()

        return sorted(list(matched_tables))


class HybridFKSchemaRetriever(BaseSchemaRetriever):
    """
    Recommended hybrid retriever combining adaptive threshold, lexical matching,
    and Foreign Key (FK) Graph Closure to guarantee join bridges are preserved.
    """

    def __init__(
        self,
        catalog: Optional[SemanticCatalog] = None,
        max_auto_inject_tables: int = 10
    ):
        self.catalog = catalog
        self.max_auto_inject_tables = max_auto_inject_tables
        self.lexical_retriever = LexicalSchemaRetriever(catalog=catalog)

    def _build_fk_adjacency(self, schema: DatabaseSchema) -> Dict[str, Set[str]]:
        """Construct an undirected graph of tables connected by foreign keys."""
        adj: Dict[str, Set[str]] = {t: set() for t in schema.tables.keys()}
        for t_name, table in schema.tables.items():
            for _, ref_target in table.foreign_keys.items():
                ref_table = ref_target.split(".")[0]
                if ref_table in adj and ref_table != t_name:
                    adj[t_name].add(ref_table)
                    adj[ref_table].add(t_name)
        return adj

    def _find_shortest_path(self, start: str, target: str, adj: Dict[str, Set[str]]) -> List[str]:
        """BFS shortest path between two tables in the FK graph."""
        if start == target:
            return [start]
        queue = deque([[start]])
        visited = {start}

        while queue:
            path = queue.popleft()
            node = path[-1]
            for neighbor in adj.get(node, []):
                if neighbor == target:
                    return path + [neighbor]
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append(path + [neighbor])
        return []

    def retrieve_tables(self, query: str, schema: DatabaseSchema) -> List[str]:
        total_tables = len(schema.tables)

        # 1. Adaptive Threshold: For small schemas (<= threshold, e.g. 3-10 tables),
        # always inject all tables. Pruning here risks dropping join paths with zero token savings.
        if total_tables <= self.max_auto_inject_tables:
            return schema.table_names()

        # 2. Run lexical & synonym retrieval to find initial candidate tables
        matched = self.lexical_retriever.retrieve_tables(query, schema)
        if len(matched) <= 1:
            return matched

        # 3. Foreign Key Graph Closure: Connect matched tables via bridge tables
        adj = self._build_fk_adjacency(schema)
        closure: Set[str] = set(matched)

        matched_list = list(matched)
        for i in range(len(matched_list)):
            for j in range(i + 1, len(matched_list)):
                t1, t2 = matched_list[i], matched_list[j]
                path = self._find_shortest_path(t1, t2, adj)
                if path:
                    closure.update(path)

        return sorted(list(closure))
