from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any

import chromadb
from chromadb.config import Settings

from .regulations import RegulationLoader, RegulationChunk


CHROMA_DIR = os.getenv("CHROMA_PERSIST_DIR", "./data/chroma")


class FreightKnowledgeBase:
    """
    ChromaDB-backed knowledge base for FMCSA/DOT regulations.
    Provides semantic search over ~4 regulatory domains with metadata filtering.
    """

    COLLECTION_NAME = "freight_regulations"

    def __init__(self, persist_dir: str = CHROMA_DIR) -> None:
        Path(persist_dir).mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(
            path=persist_dir,
            settings=Settings(anonymized_telemetry=False),
        )
        self._collection = self._client.get_or_create_collection(
            name=self.COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )
        self._loader = RegulationLoader()

    def ingest(self, force: bool = False) -> int:
        """Load regulations into ChromaDB. Returns number of chunks ingested."""
        if not force and self._collection.count() > 0:
            return self._collection.count()

        chunks = self._loader.load_all()
        if not chunks:
            return 0

        ids = [c.id for c in chunks]
        documents = [c.content for c in chunks]
        metadatas = [
            {
                "title": c.title,
                "citation": c.citation,
                "category": c.category,
                "keywords": ", ".join(c.keywords),
            }
            for c in chunks
        ]

        self._collection.upsert(ids=ids, documents=documents, metadatas=metadatas)
        return len(chunks)

    def search(
        self,
        query: str,
        n_results: int = 5,
        category_filter: str | None = None,
    ) -> list[dict[str, Any]]:
        """Semantic search over regulations. Returns ranked list of relevant chunks."""
        where: dict[str, Any] | None = None
        if category_filter:
            where = {"category": {"$eq": category_filter}}

        results = self._collection.query(
            query_texts=[query],
            n_results=min(n_results, max(1, self._collection.count())),
            where=where,
            include=["documents", "metadatas", "distances"],
        )

        hits = []
        for i, doc in enumerate(results["documents"][0]):
            metadata = results["metadatas"][0][i]
            distance = results["distances"][0][i]
            relevance = round(1.0 - distance, 4)
            hits.append(
                {
                    "content": doc,
                    "title": metadata.get("title", ""),
                    "citation": metadata.get("citation", ""),
                    "category": metadata.get("category", ""),
                    "relevance": relevance,
                }
            )
        return sorted(hits, key=lambda x: x["relevance"], reverse=True)

    def get_context_for_query(self, query: str, max_tokens: int = 2000) -> str:
        """Build a context string from top search results, budget-capped."""
        hits = self.search(query, n_results=6)
        context_parts: list[str] = []
        total_chars = 0
        char_budget = max_tokens * 4  # rough chars-per-token estimate

        for hit in hits:
            chunk = f"[{hit['citation']}]\n{hit['content']}\n"
            if total_chars + len(chunk) > char_budget:
                break
            context_parts.append(chunk)
            total_chars += len(chunk)

        return "\n---\n".join(context_parts)

    @property
    def count(self) -> int:
        return self._collection.count()
