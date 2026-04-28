from __future__ import annotations

import os
import time
import uuid
from datetime import datetime
from typing import Any, Annotated, Literal

import anthropic
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langgraph.types import Command, interrupt
from typing_extensions import TypedDict

from src.agents import (
    ComplianceOracleAgent,
    CarrierVettingAgent,
    DriverQualificationAgent,
    CSAScoringAgent,
)
from src.knowledge.vectorstore import FreightKnowledgeBase
from src.models.domain import QueryIntent
from src.observability.tracer import get_tracer


ROUTER_MODEL = os.getenv("AGENT_MODEL", "claude-sonnet-4-6")


class FreightState(TypedDict):
    query: str
    intent: QueryIntent | None
    agent_response: str
    metadata: dict[str, Any]
    messages: Annotated[list[dict[str, Any]], add_messages]


class RigCompassOrchestrator:
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
        self._hitl_checkpointer = MemorySaver()
        self._hitl_graph = self._build_hitl_graph()

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

    def _build_hitl_graph(self) -> Any:
        """Graph variant with an explicit human approval interrupt gate."""
        builder = StateGraph(FreightState)

        builder.add_node("router", self._router_node)
        builder.add_node("approval_gate", self._approval_gate_node)
        builder.add_node("carrier_vetting", self._carrier_node)
        builder.add_node("driver_qualification", self._driver_node)
        builder.add_node("csa_scoring", self._csa_node)
        builder.add_node("compliance_oracle", self._oracle_node)
        builder.add_node("synthesizer", self._synthesizer_node)
        builder.add_node("halted", self._halted_node)

        builder.set_entry_point("router")
        builder.add_edge("router", "approval_gate")
        builder.add_conditional_edges(
            "approval_gate",
            self._route_after_approval,
            {
                "carrier_vetting": "carrier_vetting",
                "driver_qualification": "driver_qualification",
                "csa_scoring": "csa_scoring",
                "compliance_oracle": "compliance_oracle",
                "multi_domain": "compliance_oracle",
                "halted": "halted",
            },
        )
        for agent_node in ["carrier_vetting", "driver_qualification", "csa_scoring", "compliance_oracle"]:
            builder.add_edge(agent_node, "synthesizer")
        builder.add_edge("synthesizer", END)
        builder.add_edge("halted", END)

        return builder.compile(checkpointer=self._hitl_checkpointer)

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

    def _approval_gate_node(self, state: FreightState) -> FreightState:
        """Interrupt execution until a human explicitly approves sensitive flows."""
        intent = state.get("intent")
        requires_approval = intent in {
            QueryIntent.CARRIER_VETTING,
            QueryIntent.DRIVER_QUALIFICATION,
            QueryIntent.MULTI_DOMAIN,
        }
        metadata = {**state.get("metadata", {})}
        metadata["requires_human_approval"] = requires_approval

        if not requires_approval:
            return {**state, "metadata": metadata}

        decision = interrupt(
            {
                "type": "human_approval",
                "intent": intent.value if intent else None,
                "query": state.get("query", ""),
                "reason": "Sensitive compliance recommendation path requires human approval.",
                "allowed_actions": ["approve", "reject"],
            }
        )

        approved = self._is_approved(decision)
        metadata["human_review"] = {
            "approved": approved,
            "decision_payload": decision,
        }
        if not approved:
            metadata["halted_by_human"] = True
        return {**state, "metadata": metadata}

    def _route_after_approval(self, state: FreightState) -> str:
        if state.get("metadata", {}).get("halted_by_human"):
            return "halted"
        return self._route_to_agent(state)

    def _halted_node(self, state: FreightState) -> FreightState:
        decision_payload = state.get("metadata", {}).get("human_review", {}).get("decision_payload")
        reviewer_note = None
        if isinstance(decision_payload, dict):
            reviewer_note = decision_payload.get("reviewer_note")
        note_line = f" Reviewer note: {reviewer_note}" if reviewer_note else ""
        return {
            **state,
            "agent_response": (
                "Execution stopped by human reviewer before specialist agent execution."
                f"{note_line}"
            ),
        }

    def _is_approved(self, decision: Any) -> bool:
        if isinstance(decision, dict):
            raw = decision.get("approved")
            if isinstance(raw, bool):
                return raw
            if isinstance(raw, str):
                return raw.strip().lower() in {"true", "1", "yes", "approve", "approved"}
        if isinstance(decision, bool):
            return decision
        if isinstance(decision, str):
            return decision.strip().lower() in {"true", "1", "yes", "approve", "approved"}
        return False

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
            system="""You are the final output formatter for RigCompass, a transportation compliance AI.

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
        """Main entry point with node-level timeline metadata for observability."""
        state: FreightState = {
            "query": query,
            "intent": None,
            "agent_response": "",
            "metadata": {},
            "messages": [],
        }

        timeline: list[dict[str, Any]] = []

        def run_node(name: str, fn: Any, current_state: FreightState) -> FreightState:
            t0 = time.perf_counter()
            started_at = datetime.utcnow().isoformat()
            updated = fn(current_state)
            ended_at = datetime.utcnow().isoformat()
            latency_ms = round((time.perf_counter() - t0) * 1000, 2)
            timeline.append(
                {
                    "node": name,
                    "started_at": started_at,
                    "ended_at": ended_at,
                    "latency_ms": latency_ms,
                    "status": "ok",
                }
            )
            return updated

        state = run_node("router", self._router_node, state)
        route = self._route_to_agent(state)
        route_map = {
            "carrier_vetting": self._carrier_node,
            "driver_qualification": self._driver_node,
            "csa_scoring": self._csa_node,
            "compliance_oracle": self._oracle_node,
            "multi_domain": self._oracle_node,
        }
        agent_fn = route_map.get(route, self._oracle_node)
        state = run_node(route, agent_fn, state)
        state = run_node("synthesizer", self._synthesizer_node, state)

        metadata = state.get("metadata", {})
        metadata = {**metadata, "route": route, "timeline": timeline}

        trace_id = metadata.get("trace")
        if trace_id:
            get_tracer().record_timeline(
                trace_id,
                {
                    "query": query,
                    "intent": state.get("intent").value if state.get("intent") else None,
                    "route": route,
                    "nodes": timeline,
                },
            )

        return {
            "query": query,
            "intent": state.get("intent"),
            "response": state.get("agent_response", ""),
            "metadata": metadata,
        }

    def invoke_optimized(self, query: str) -> dict[str, Any]:
        """
        Evaluator-optimizer loop MVP:
        1) Run standard orchestration.
        2) Ask evaluator prompt to keep or rewrite for clarity/actionability/citations.
        """
        base = self.invoke(query)
        response_text = base.get("response", "")
        eval_resp = self._client.messages.create(
            model=ROUTER_MODEL,
            max_tokens=1024,
            system=(
                "You are a strict compliance-response evaluator. "
                "Assess if the response is clear, actionable, and grounded. "
                "If good enough, return exactly: DECISION: KEEP\nREWRITE_RESPONSE: <original response>. "
                "If weak, return exactly: DECISION: REWRITE\nREWRITE_RESPONSE: <improved response>."
            ),
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"QUERY:\n{query}\n\n"
                        f"RESPONSE:\n{response_text}\n\n"
                        "Use status -> findings -> recommendations format."
                    ),
                }
            ],
        )
        eval_text = eval_resp.content[0].text if eval_resp.content else ""
        decision = "KEEP" if "DECISION: KEEP" in eval_text else "REWRITE"
        marker = "REWRITE_RESPONSE:"
        if marker in eval_text:
            optimized = eval_text.split(marker, 1)[1].strip()
        else:
            optimized = response_text
        if not optimized:
            optimized = response_text

        metadata = {**base.get("metadata", {})}
        metadata["optimizer"] = {
            "enabled": True,
            "decision": decision,
            "applied": decision == "REWRITE",
        }
        return {
            **base,
            "response": optimized,
            "metadata": metadata,
        }

    def invoke_hitl(self, query: str, thread_id: str | None = None) -> dict[str, Any]:
        """Start HITL flow and pause at approval gate when required."""
        thread_id = thread_id or str(uuid.uuid4())
        config = {"configurable": {"thread_id": thread_id}}
        initial_state: FreightState = {
            "query": query,
            "intent": None,
            "agent_response": "",
            "metadata": {},
            "messages": [],
        }
        result = self._hitl_graph.invoke(initial_state, config=config)
        if "__interrupt__" in result:
            interrupts = result.get("__interrupt__", [])
            payloads = []
            for i in interrupts:
                payloads.append({"id": getattr(i, "id", None), "value": getattr(i, "value", None)})
            return {
                "status": "waiting_for_human",
                "thread_id": thread_id,
                "interrupts": payloads,
                "query": query,
            }
        return self._format_hitl_result(result, thread_id=thread_id)

    def resume_hitl(self, thread_id: str, approved: bool, reviewer_note: str | None = None) -> dict[str, Any]:
        """Resume a paused HITL flow with explicit human approval decision."""
        config = {"configurable": {"thread_id": thread_id}}
        result = self._hitl_graph.invoke(
            Command(resume={"approved": approved, "reviewer_note": reviewer_note}),
            config=config,
        )
        if "__interrupt__" in result:
            interrupts = result.get("__interrupt__", [])
            payloads = []
            for i in interrupts:
                payloads.append({"id": getattr(i, "id", None), "value": getattr(i, "value", None)})
            return {
                "status": "waiting_for_human",
                "thread_id": thread_id,
                "interrupts": payloads,
            }
        return self._format_hitl_result(result, thread_id=thread_id)

    def hitl_state(self, thread_id: str) -> dict[str, Any]:
        """Return current checkpoint state for a HITL thread."""
        config = {"configurable": {"thread_id": thread_id}}
        snapshot = self._hitl_graph.get_state(config)
        values = snapshot.values or {}
        intent = values.get("intent")
        return {
            "thread_id": thread_id,
            "next": list(snapshot.next),
            "has_interrupts": bool(snapshot.interrupts),
            "interrupts": [
                {"id": getattr(i, "id", None), "value": getattr(i, "value", None)}
                for i in snapshot.interrupts
            ],
            "query": values.get("query"),
            "intent": intent.value if intent else None,
            "metadata": values.get("metadata", {}),
            "response": values.get("agent_response", ""),
        }

    def _format_hitl_result(self, result: dict[str, Any], thread_id: str) -> dict[str, Any]:
        intent = result.get("intent")
        metadata = {**result.get("metadata", {})}
        metadata["thread_id"] = thread_id
        return {
            "status": "completed",
            "thread_id": thread_id,
            "query": result.get("query"),
            "intent": intent,
            "response": result.get("agent_response", ""),
            "metadata": metadata,
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
