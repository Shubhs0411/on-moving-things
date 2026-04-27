from __future__ import annotations

import os
from typing import Any, Annotated, Literal

import anthropic
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict

from src.agents import (
    ComplianceOracleAgent,
    CarrierVettingAgent,
    DriverQualificationAgent,
    CSAScoringAgent,
)
from src.knowledge.vectorstore import FreightKnowledgeBase
from src.models.domain import QueryIntent


ROUTER_MODEL = os.getenv("AGENT_MODEL", "claude-sonnet-4-6")


class FreightState(TypedDict):
    query: str
    intent: QueryIntent | None
    agent_response: str
    metadata: dict[str, Any]
    messages: Annotated[list[dict[str, Any]], add_messages]


class FreightMindOrchestrator:
    """
    LangGraph-based multi-agent orchestrator.
    Routes incoming compliance queries to the right specialist agent.

    Graph topology:
        user_query → router → [carrier_vetting | driver_qual | csa_scoring | compliance_oracle] → synthesizer → END
    """

    _GRAPH_NODES = [
        "router",
        "carrier_vetting",
        "driver_qualification",
        "csa_scoring",
        "compliance_oracle",
        "synthesizer",
    ]
    _GRAPH_EDGES = [
        ("router", "carrier_vetting", "intent=carrier_vetting"),
        ("router", "driver_qualification", "intent=driver_qualification"),
        ("router", "csa_scoring", "intent=csa_scoring"),
        ("router", "compliance_oracle", "intent=regulation_lookup|risk_assessment"),
        ("router", "compliance_oracle", "intent=multi_domain"),
        ("carrier_vetting", "synthesizer", ""),
        ("driver_qualification", "synthesizer", ""),
        ("csa_scoring", "synthesizer", ""),
        ("compliance_oracle", "synthesizer", ""),
        ("synthesizer", "END", ""),
    ]

    def __init__(self) -> None:
        self._client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        self._kb = FreightKnowledgeBase()
        self._kb.ingest()

        self._carrier_agent = CarrierVettingAgent()
        self._driver_agent = DriverQualificationAgent()
        self._csa_agent = CSAScoringAgent()
        self._oracle_agent = ComplianceOracleAgent(kb=self._kb)

        self._graph = self._build_graph()

    def _build_graph(self) -> Any:
        builder = StateGraph(FreightState)

        builder.add_node("router", self._router_node)
        builder.add_node("carrier_vetting", self._carrier_node)
        builder.add_node("driver_qualification", self._driver_node)
        builder.add_node("csa_scoring", self._csa_node)
        builder.add_node("compliance_oracle", self._oracle_node)
        builder.add_node("synthesizer", self._synthesizer_node)

        builder.set_entry_point("router")
        builder.add_conditional_edges(
            "router",
            self._route_to_agent,
            {
                "carrier_vetting": "carrier_vetting",
                "driver_qualification": "driver_qualification",
                "csa_scoring": "csa_scoring",
                "compliance_oracle": "compliance_oracle",
                "multi_domain": "compliance_oracle",
            },
        )
        for agent_node in ["carrier_vetting", "driver_qualification", "csa_scoring", "compliance_oracle"]:
            builder.add_edge(agent_node, "synthesizer")
        builder.add_edge("synthesizer", END)

        return builder.compile()

    def _router_node(self, state: FreightState) -> FreightState:
        """Classify query intent using Claude with structured output."""
        query = state["query"]
        response = self._client.messages.create(
            model=ROUTER_MODEL,
            max_tokens=256,
            system="""You are a query router for a transportation compliance system.
Classify the user query into exactly one intent category.

Categories:
- carrier_vetting: Questions about a specific carrier's safety, authority, insurance, SAFER lookup
- driver_qualification: Questions about a specific driver's CDL, medical cert, DQ file, clearinghouse
- csa_scoring: Questions about CSA BASIC scores, SMS percentiles, score improvement
- regulation_lookup: General questions about FMCSA/DOT regulations, HOS rules, CFR citations
- risk_assessment: General risk questions not tied to a specific carrier or driver
- multi_domain: Query spans multiple categories

Respond with ONLY the category name, nothing else.""",
            messages=[{"role": "user", "content": query}],
        )
        intent_str = response.content[0].text.strip().lower()
        intent_map = {
            "carrier_vetting": QueryIntent.CARRIER_VETTING,
            "driver_qualification": QueryIntent.DRIVER_QUALIFICATION,
            "csa_scoring": QueryIntent.CSA_SCORING,
            "regulation_lookup": QueryIntent.REGULATION_LOOKUP,
            "risk_assessment": QueryIntent.RISK_ASSESSMENT,
            "multi_domain": QueryIntent.MULTI_DOMAIN,
        }
        intent = intent_map.get(intent_str, QueryIntent.REGULATION_LOOKUP)
        return {**state, "intent": intent}

    def _route_to_agent(self, state: FreightState) -> str:
        intent = state.get("intent")
        if intent == QueryIntent.CARRIER_VETTING:
            return "carrier_vetting"
        if intent == QueryIntent.DRIVER_QUALIFICATION:
            return "driver_qualification"
        if intent == QueryIntent.CSA_SCORING:
            return "csa_scoring"
        if intent == QueryIntent.MULTI_DOMAIN:
            return "multi_domain"
        return "compliance_oracle"

    def _carrier_node(self, state: FreightState) -> FreightState:
        result = self._carrier_agent.run(state["query"])
        return {**state, "agent_response": result["response"], "metadata": {"agent": "carrier_vetting", "trace": result["trace"].trace_id}}

    def _driver_node(self, state: FreightState) -> FreightState:
        result = self._driver_agent.run(state["query"])
        return {**state, "agent_response": result["response"], "metadata": {"agent": "driver_qualification", "trace": result["trace"].trace_id}}

    def _csa_node(self, state: FreightState) -> FreightState:
        result = self._csa_agent.run(state["query"])
        return {**state, "agent_response": result["response"], "metadata": {"agent": "csa_scoring", "trace": result["trace"].trace_id}}

    def _oracle_node(self, state: FreightState) -> FreightState:
        result = self._oracle_agent.run(state["query"])
        return {**state, "agent_response": result["response"], "metadata": {"agent": "compliance_oracle", "trace": result["trace"].trace_id}}

    def _synthesizer_node(self, state: FreightState) -> FreightState:
        """Final polish pass — ensures response is actionable and well-structured."""
        response = self._client.messages.create(
            model=ROUTER_MODEL,
            max_tokens=1024,
            system="""You are the final output formatter for FreightMind, a transportation compliance AI.

Your job: Take the agent's response and ensure it is:
1. Clearly structured (status → findings → recommendations)
2. Cites specific CFR sections where relevant
3. Actionable — gives the person a clear next step
4. Appropriately urgent — if something is CRITICAL, make that clear

Do NOT add new information. Do NOT remove critical findings. Only improve clarity and structure.""",
            messages=[
                {
                    "role": "user",
                    "content": f"Original query: {state['query']}\n\nAgent response:\n{state['agent_response']}\n\nPlease format this response.",
                }
            ],
        )
        final_response = response.content[0].text
        return {**state, "agent_response": final_response}

    def invoke(self, query: str) -> dict[str, Any]:
        """Main entry point. Returns final response and metadata."""
        initial_state: FreightState = {
            "query": query,
            "intent": None,
            "agent_response": "",
            "metadata": {},
            "messages": [],
        }
        final_state = self._graph.invoke(initial_state)
        return {
            "query": query,
            "intent": final_state.get("intent"),
            "response": final_state.get("agent_response", ""),
            "metadata": final_state.get("metadata", {}),
        }

    @classmethod
    def graph_mermaid(cls) -> str:
        """Return a Mermaid flowchart representation of the LangGraph topology."""
        node_ids = {
            "router": "R",
            "carrier_vetting": "CV",
            "driver_qualification": "DQ",
            "csa_scoring": "CSA",
            "compliance_oracle": "CO",
            "synthesizer": "S",
            "END": "E",
        }
        lines = [
            "flowchart LR",
            "  U[\"User Query\"] --> R[\"router\"]",
            "  E((END))",
        ]
        for src, dst, label in cls._GRAPH_EDGES:
            if src == "synthesizer" and dst == "END":
                lines.append("  S[\"synthesizer\"] --> E")
                continue
            src_node = f"{node_ids[src]}[\"{src}\"]"
            dst_node = f"{node_ids[dst]}[\"{dst}\"]"
            if label:
                lines.append(f"  {src_node} -- \"{label}\" --> {dst_node}")
            else:
                lines.append(f"  {src_node} --> {dst_node}")
        return "\n".join(lines)
