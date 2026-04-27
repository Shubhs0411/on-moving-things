from __future__ import annotations

# Lazy imports — avoids hard-failing when optional deps (chromadb, sentence-transformers)
# are not installed. Tests that don't need the vector store can still import graph/fmcsa.

def __getattr__(name: str):
    if name == "FreightKnowledgeBase":
        from .vectorstore import FreightKnowledgeBase
        return FreightKnowledgeBase
    if name == "RegulationLoader":
        from .regulations import RegulationLoader
        return RegulationLoader
    if name in ("FreightKnowledgeGraph", "get_graph"):
        from .graph import FreightKnowledgeGraph, get_graph
        return FreightKnowledgeGraph if name == "FreightKnowledgeGraph" else get_graph
    if name == "DocumentIngester":
        from .ingester import DocumentIngester
        return DocumentIngester
    if name == "FMCSAClient":
        from .fmcsa_api import FMCSAClient
        return FMCSAClient
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "FreightKnowledgeBase",
    "RegulationLoader",
    "FreightKnowledgeGraph",
    "get_graph",
    "DocumentIngester",
    "FMCSAClient",
]
