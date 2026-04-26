from __future__ import annotations

import os
import time
import uuid
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

import anthropic

from src.models.domain import AgentTrace, QueryIntent
from src.observability.tracer import get_tracer


AGENT_MODEL = os.getenv("AGENT_MODEL", "claude-sonnet-4-6")
ORACLE_MODEL = os.getenv("ORACLE_MODEL", "claude-opus-4-7")


class BaseComplianceAgent(ABC):
    """
    Base class for all FreightMind compliance agents.
    Handles tracing, token accounting, and structured tool-use loops with Claude.
    """

    name: str = "base"
    model: str = AGENT_MODEL

    def __init__(self) -> None:
        self._client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        self._tracer = get_tracer()

    @property
    @abstractmethod
    def system_prompt(self) -> str: ...

    @property
    @abstractmethod
    def tools(self) -> list[dict[str, Any]]: ...

    @abstractmethod
    def _dispatch_tool(self, tool_name: str, tool_input: dict[str, Any]) -> str: ...

    def run(self, query: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        trace = AgentTrace(
            trace_id=str(uuid.uuid4()),
            agent_name=self.name,
            query=query,
            model_used=self.model,
            started_at=datetime.utcnow(),
        )
        t0 = time.perf_counter()

        try:
            result = self._agentic_loop(query, context or {}, trace)
            trace.completed_at = datetime.utcnow()
            trace.latency_ms = (time.perf_counter() - t0) * 1000
            self._tracer.record(trace)
            return result
        except Exception as e:
            trace.error = str(e)
            trace.completed_at = datetime.utcnow()
            trace.latency_ms = (time.perf_counter() - t0) * 1000
            self._tracer.record(trace)
            raise

    def _agentic_loop(
        self,
        query: str,
        context: dict[str, Any],
        trace: AgentTrace,
        max_iterations: int = 10,
    ) -> dict[str, Any]:
        messages: list[dict[str, Any]] = [{"role": "user", "content": query}]

        for _ in range(max_iterations):
            response = self._client.messages.create(
                model=self.model,
                max_tokens=4096,
                system=self.system_prompt,
                tools=self.tools,
                messages=messages,
            )
            trace.input_tokens += response.usage.input_tokens
            trace.output_tokens += response.usage.output_tokens

            if response.stop_reason == "end_turn":
                text = next(
                    (b.text for b in response.content if hasattr(b, "text")), ""
                )
                return {"response": text, "trace": trace}

            if response.stop_reason == "tool_use":
                tool_results = []
                for block in response.content:
                    if block.type == "tool_use":
                        trace.tools_called.append(block.name)
                        result_str = self._dispatch_tool(block.name, block.input)
                        trace.tool_results.append(
                            {"tool": block.name, "input": block.input, "result": result_str[:500]}
                        )
                        tool_results.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": result_str,
                            }
                        )

                messages.append({"role": "assistant", "content": response.content})
                messages.append({"role": "user", "content": tool_results})

        return {"response": "Max iterations reached", "trace": trace}
