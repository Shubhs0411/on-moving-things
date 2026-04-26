from __future__ import annotations

import json
import os
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from src.models.domain import AgentTrace


TRACE_DIR = os.getenv("TRACE_DIR", "./evals/results")
TRACE_ENABLED = os.getenv("TRACE_ENABLED", "true").lower() == "true"

_global_tracer: AgentTracer | None = None


class AgentTracer:
    """
    Lightweight observability layer. Persists every agent trace to JSONL,
    maintains in-memory session stats, and provides aggregate metrics.

    Embodies the 'nervous system' — continuous feedback on whether the system
    is working and what to change when it isn't.
    """

    def __init__(self, trace_dir: str = TRACE_DIR) -> None:
        self._dir = Path(trace_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._session_traces: list[AgentTrace] = []
        self._enabled = TRACE_ENABLED

    def record(self, trace: AgentTrace) -> None:
        self._session_traces.append(trace)
        if self._enabled:
            self._persist(trace)

    def _persist(self, trace: AgentTrace) -> None:
        date_str = datetime.utcnow().strftime("%Y%m%d")
        path = self._dir / f"traces_{date_str}.jsonl"
        with path.open("a") as f:
            f.write(trace.model_dump_json() + "\n")

    def session_stats(self) -> dict[str, Any]:
        if not self._session_traces:
            return {"total_calls": 0}

        total = len(self._session_traces)
        errors = sum(1 for t in self._session_traces if t.error)
        avg_latency = sum(t.latency_ms for t in self._session_traces) / total
        total_input_tokens = sum(t.input_tokens for t in self._session_traces)
        total_output_tokens = sum(t.output_tokens for t in self._session_traces)

        by_agent: dict[str, list[float]] = defaultdict(list)
        for t in self._session_traces:
            by_agent[t.agent_name].append(t.latency_ms)

        tool_freq: dict[str, int] = defaultdict(int)
        for t in self._session_traces:
            for tool in t.tools_called:
                tool_freq[tool] += 1

        return {
            "total_calls": total,
            "error_rate": f"{errors / total * 100:.1f}%",
            "avg_latency_ms": round(avg_latency, 1),
            "total_input_tokens": total_input_tokens,
            "total_output_tokens": total_output_tokens,
            "by_agent": {
                agent: {
                    "calls": len(latencies),
                    "avg_latency_ms": round(sum(latencies) / len(latencies), 1),
                }
                for agent, latencies in by_agent.items()
            },
            "top_tools": sorted(tool_freq.items(), key=lambda x: x[1], reverse=True)[:5],
        }

    def recent_traces(self, n: int = 10) -> list[AgentTrace]:
        return self._session_traces[-n:]

    def load_historical(self, date_str: str | None = None) -> list[dict[str, Any]]:
        """Load traces from a specific date's JSONL file."""
        date_str = date_str or datetime.utcnow().strftime("%Y%m%d")
        path = self._dir / f"traces_{date_str}.jsonl"
        if not path.exists():
            return []
        traces = []
        with path.open() as f:
            for line in f:
                line = line.strip()
                if line:
                    traces.append(json.loads(line))
        return traces

    def clear_session(self) -> None:
        self._session_traces.clear()


def get_tracer() -> AgentTracer:
    global _global_tracer
    if _global_tracer is None:
        _global_tracer = AgentTracer()
    return _global_tracer
