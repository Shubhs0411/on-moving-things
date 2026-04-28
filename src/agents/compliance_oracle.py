from __future__ import annotations

import json
import os
from typing import Any

from src.knowledge.vectorstore import FreightKnowledgeBase
from src.knowledge.graph import get_graph
from .base import BaseComplianceAgent, ORACLE_MODEL


class ComplianceOracleAgent(BaseComplianceAgent):
    """
    Deep regulatory Q&A agent — GraphRAG architecture.
    Combines:
      - ChromaDB semantic search (what do regulations say?)
      - Knowledge graph traversal (what has this entity actually done?)
    Uses claude-opus-4-7 for reasoning over both sources.
    """

    name = "compliance_oracle"
    model = ORACLE_MODEL

    def __init__(self, kb: FreightKnowledgeBase | None = None) -> None:
        super().__init__()
        self._kb = kb or FreightKnowledgeBase()
        self._kb.ingest()
        self._graph = get_graph()

    @property
    def system_prompt(self) -> str:
        return """You are the RigCompass Compliance Oracle — an expert on FMCSA, DOT, and transportation compliance regulations.

Your role: Answer compliance questions with precision, cite the specific CFR section, and explain practical implications.

Rules:
- Always cite the specific 49 CFR section (e.g., 49 CFR 395.3(a)(1))
- Distinguish between federal requirements and state variations where relevant
- Flag when a situation may require legal counsel
- Use search_regulations to retrieve current regulatory text before answering
- If a question spans multiple domains (HOS + DQ + CSA), address each domain
- Be direct. The person asking this question is making a real decision under real pressure.

Output structure: Answer → Citation → Practical implication → Any caveats"""

    @property
    def tools(self) -> list[dict[str, Any]]:
        return [
            {
                "name": "search_regulations",
                "description": "Semantic search over FMCSA/DOT regulatory knowledge base. Returns relevant regulation excerpts with citations.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "The regulatory question or topic to search for",
                        },
                        "category": {
                            "type": "string",
                            "enum": ["HOS", "DQ", "CSA", "AUTHORITY", "all"],
                            "description": "Filter by regulatory category. Use 'all' if unsure.",
                        },
                        "n_results": {
                            "type": "integer",
                            "description": "Number of results to return (default 5)",
                            "default": 5,
                        },
                    },
                    "required": ["query", "category"],
                },
            },
            {
                "name": "get_cfr_section",
                "description": "Get the full text of a specific CFR section from the knowledge base.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "citation": {
                            "type": "string",
                            "description": "CFR citation, e.g. '49 CFR 395.3' or '395.1(g)'",
                        }
                    },
                    "required": ["citation"],
                },
            },
            {
                "name": "graph_query",
                "description": "Query the knowledge graph for relational facts about a carrier or driver: violation history, most-cited regulations, driver compliance chain. Use when a question involves a specific entity (DOT number or CDL).",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "entity_type": {
                            "type": "string",
                            "enum": ["carrier", "driver"],
                            "description": "Type of entity to query",
                        },
                        "entity_id": {
                            "type": "string",
                            "description": "DOT number for carriers, license number for drivers",
                        },
                    },
                    "required": ["entity_type", "entity_id"],
                },
            },
        ]

    def _dispatch_tool(self, tool_name: str, tool_input: dict[str, Any]) -> str:
        if tool_name == "search_regulations":
            category = tool_input.get("category")
            category_filter = None if category == "all" else category
            results = self._kb.search(
                query=tool_input["query"],
                n_results=tool_input.get("n_results", 5),
                category_filter=category_filter,
            )
            if not results:
                return "No relevant regulations found."
            output = []
            for r in results:
                output.append(
                    f"[Relevance: {r['relevance']:.2f}] [{r['citation']}]\n{r['content']}"
                )
            return "\n\n---\n\n".join(output)

        if tool_name == "get_cfr_section":
            citation = tool_input["citation"]
            results = self._kb.search(query=citation, n_results=3)
            if not results:
                return f"Section {citation} not found in knowledge base."
            return results[0]["content"]

        if tool_name == "graph_query":
            entity_type = tool_input.get("entity_type", "carrier")
            entity_id = tool_input.get("entity_id", "")
            if entity_type == "carrier":
                return self._graph.get_graph_context_for_carrier(entity_id)
            elif entity_type == "driver":
                return self._graph.get_graph_context_for_driver(entity_id)
            return f"Unknown entity type: {entity_type}"

        return f"Unknown tool: {tool_name}"
