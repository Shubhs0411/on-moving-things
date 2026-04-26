from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from src.graph.orchestrator import FreightMindOrchestrator
from src.eval.harness import EvalHarness
from src.eval.test_cases import EVAL_SUITE
from src.observability.tracer import get_tracer
from src.models.domain import QueryIntent


app = FastAPI(
    title="FreightMind AI",
    description="Multi-agent transportation compliance intelligence. FMCSA · DOT · CSA · 49 CFR.",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_orchestrator: FreightMindOrchestrator | None = None


def get_orchestrator() -> FreightMindOrchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = FreightMindOrchestrator()
    return _orchestrator


# ── Request/Response Models ───────────────────────────────────────────────────

class ComplianceQuery(BaseModel):
    query: str
    context: dict[str, Any] | None = None


class ComplianceResponse(BaseModel):
    query: str
    intent: str | None
    response: str
    trace_id: str | None = None
    latency_ms: float | None = None
    timestamp: str = ""

    def model_post_init(self, __context: Any) -> None:
        if not self.timestamp:
            self.timestamp = datetime.utcnow().isoformat()


class EvalRequest(BaseModel):
    category: str | None = None
    n_cases: int | None = None


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "service": "FreightMind AI", "version": "0.1.0"}


@app.post("/v1/compliance/query", response_model=ComplianceResponse)
def compliance_query(request: ComplianceQuery):
    """
    Main compliance intelligence endpoint.
    Routes queries to the appropriate specialist agent via LangGraph orchestrator.
    """
    import time
    t0 = time.perf_counter()
    try:
        orchestrator = get_orchestrator()
        result = orchestrator.invoke(request.query)
        latency_ms = (time.perf_counter() - t0) * 1000
        return ComplianceResponse(
            query=request.query,
            intent=result.get("intent").value if result.get("intent") else None,
            response=result["response"],
            trace_id=result.get("metadata", {}).get("trace"),
            latency_ms=round(latency_ms, 1),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/v1/carrier/vet")
def vet_carrier(dot_number: str):
    """Direct carrier vetting endpoint."""
    orchestrator = get_orchestrator()
    result = orchestrator.invoke(
        f"Run a full safety and compliance check on carrier with DOT number {dot_number}"
    )
    return result


@app.post("/v1/driver/qualify")
def qualify_driver(license_number: str):
    """Direct driver qualification check."""
    orchestrator = get_orchestrator()
    result = orchestrator.invoke(
        f"Check driver qualification status for CDL license {license_number}. "
        f"Are they qualified to drive today? Check DQ file, medical cert, and Clearinghouse."
    )
    return result


@app.get("/v1/observability/stats")
def observability_stats():
    """Real-time session observability — agent call stats, latency, token usage."""
    tracer = get_tracer()
    return tracer.session_stats()


@app.get("/v1/observability/traces")
def recent_traces(n: int = 10):
    """Return recent agent traces for debugging/monitoring."""
    tracer = get_tracer()
    traces = tracer.recent_traces(n=n)
    return [t.model_dump() for t in traces]


@app.post("/v1/eval/run")
def run_eval(request: EvalRequest):
    """
    Run the eval harness against the live system.
    Returns pass rate, per-category breakdown, and failing cases.
    """
    orchestrator = get_orchestrator()

    category_filter = None
    if request.category:
        try:
            category_filter = QueryIntent(request.category)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Unknown category: {request.category}")

    harness = EvalHarness(invoke_fn=orchestrator.invoke)
    summary = harness.run(
        category_filter=category_filter,
        n_cases=request.n_cases,
    )
    return summary


@app.get("/v1/eval/cases")
def list_eval_cases(category: str | None = None):
    """List all eval test cases."""
    cases = EVAL_SUITE
    if category:
        cases = [c for c in cases if c.category.value == category]
    return [c.model_dump() for c in cases]


@app.get("/v1/knowledge/stats")
def knowledge_stats():
    """Knowledge base stats — how many regulation chunks are indexed."""
    from src.knowledge.vectorstore import FreightKnowledgeBase
    kb = FreightKnowledgeBase()
    return {"chunks_indexed": kb.count, "collections": ["freight_regulations"]}


@app.post("/v1/knowledge/search")
def search_knowledge(query: str, category: str | None = None, n_results: int = 5):
    """Direct semantic search over the regulation knowledge base."""
    from src.knowledge.vectorstore import FreightKnowledgeBase
    kb = FreightKnowledgeBase()
    kb.ingest()
    results = kb.search(query=query, n_results=n_results, category_filter=category)
    return results
