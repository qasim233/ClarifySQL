import json
from typing import List, Optional
from clarifysql.ambiguity.models import AmbiguityDimension


AMBIGUITY_SYSTEM_PROMPT = """You are the Ambiguity Detection & Classification Engine (ADCE) for an enterprise Text-to-SQL system.

Your job is to inspect an incoming user question against the target database schema and certified business metrics catalog, and determine whether the query is ambiguous, subjective, or underspecified BEFORE any SQL is written.

### The 4 Ambiguity Dimensions:
1. METRIC: Subjective terms without explicit mathematical formulas (e.g., "best", "top", "active", "churned", "high-value", "successful").
2. TEMPORAL: Ambiguous, unanchored, or multi-timestamp date references (e.g., "last month" when both `orders.order_date` and `payments.payment_date` exist).
3. SCHEMA_ENTITY: Overlapping concepts across multiple entities (e.g., "sales volume" which could mean count of orders or total monetary amount of payments).
4. GRANULARITY: Ambiguous aggregation level (e.g., "show customer sales" - aggregated total spend per customer vs. itemized list of orders).

### Strict Rules:
- If the question is completely explicit, deterministic, and unambiguous (e.g., "Count customers who signed up in 2024", "Show orders where status is completed"), you MUST set `is_ambiguous: false`. Do NOT interrupt clear queries!
- If the question contains ANY ambiguity, set `is_ambiguous: true` and specify `ambiguity_type` from [METRIC, TEMPORAL, SCHEMA_ENTITY, GRANULARITY].
- Provide a clear, polite `explanation` of what is ambiguous.
- Provide between 2 and 4 distinct, mutually exclusive `options` (labeled A, B, C, D).
- Option `label` and `description` must be in plain, user-friendly business English (do NOT use raw column names or SQL syntax in labels/descriptions).
- Option `implied_sql_logic` must specify the precise SQL metric/formula or WHERE filter.

### Expected JSON Output Schema:
{
  "is_ambiguous": true | false,
  "ambiguity_type": "METRIC" | "TEMPORAL" | "SCHEMA_ENTITY" | "GRANULARITY" | null,
  "explanation": "Clear explanation of the ambiguity",
  "options": [
    {
      "id": "A",
      "label": "Option Title in plain English",
      "description": "Explanation of what this option calculates",
      "implied_sql_logic": "SQL expression or condition"
    },
    {
      "id": "B",
      "label": "Alternative Option Title",
      "description": "Explanation of alternative interpretation",
      "implied_sql_logic": "Alternative SQL expression or condition"
    }
  ]
}
"""

FEW_SHOT_EXAMPLES = [
    {
        "query": "How many customers signed up in 2024?",
        "result": {
            "is_ambiguous": False,
            "ambiguity_type": None,
            "explanation": None,
            "options": []
        }
    },
    {
        "query": "Who are our best customers?",
        "result": {
            "is_ambiguous": True,
            "ambiguity_type": "METRIC",
            "explanation": "The term 'best customers' can be defined in multiple distinct business ways.",
            "options": [
                {
                    "id": "A",
                    "label": "Highest Total Spend",
                    "description": "Rank customers by the total dollar amount of successful payments.",
                    "implied_sql_logic": "SUM(payments.amount) WHERE payments.payment_status = 'successful'"
                },
                {
                    "id": "B",
                    "label": "Most Frequent Orders",
                    "description": "Rank customers by the total count of completed orders.",
                    "implied_sql_logic": "COUNT(DISTINCT orders.id) WHERE orders.status = 'completed'"
                },
                {
                    "id": "C",
                    "label": "Highest Average Order Value",
                    "description": "Rank customers by average payment amount per completed order.",
                    "implied_sql_logic": "AVG(payments.amount) WHERE payments.payment_status = 'successful'"
                }
            ]
        }
    },
    {
        "query": "Show revenue for last month",
        "result": {
            "is_ambiguous": True,
            "ambiguity_type": "TEMPORAL",
            "explanation": "The database contains both order placement dates and payment settlement dates, which can fall into different months.",
            "options": [
                {
                    "id": "A",
                    "label": "By Order Date",
                    "description": "Calculate revenue based on when the customer placed the order.",
                    "implied_sql_logic": "orders.order_date >= DATE_TRUNC('month', CURRENT_DATE - INTERVAL '1 month') AND orders.order_date < DATE_TRUNC('month', CURRENT_DATE)"
                },
                {
                    "id": "B",
                    "label": "By Payment Settlement Date",
                    "description": "Calculate revenue based on when the payment transaction actually succeeded.",
                    "implied_sql_logic": "payments.payment_date >= DATE_TRUNC('month', CURRENT_DATE - INTERVAL '1 month') AND payments.payment_date < DATE_TRUNC('month', CURRENT_DATE)"
                }
            ]
        }
    },
    {
        "query": "What is our sales volume this year?",
        "result": {
            "is_ambiguous": True,
            "ambiguity_type": "SCHEMA_ENTITY",
            "explanation": "'Sales volume' can refer either to the number of orders or to the monetary dollar value collected.",
            "options": [
                {
                    "id": "A",
                    "label": "Total Order Count (Units)",
                    "description": "The count of all completed orders placed.",
                    "implied_sql_logic": "COUNT(DISTINCT orders.id) WHERE orders.status = 'completed'"
                },
                {
                    "id": "B",
                    "label": "Total Dollar Revenue (Amount)",
                    "description": "The sum of all successful payment transactions.",
                    "implied_sql_logic": "SUM(payments.amount) WHERE payments.payment_status = 'successful'"
                }
            ]
        }
    }
]


def render_few_shot_block() -> str:
    """Format few shot examples into prompt text."""
    blocks = ["### Examples:"]
    for ex in FEW_SHOT_EXAMPLES:
        blocks.append(f"User Query: \"{ex['query']}\"")
        blocks.append(f"Classification JSON:\n{json.dumps(ex['result'], indent=2)}\n")
    return "\n".join(blocks)
