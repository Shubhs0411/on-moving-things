from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel


DATA_DIR = Path(__file__).parent.parent.parent / "data"


class RegulationChunk(BaseModel):
    id: str
    title: str
    content: str
    citation: str
    category: str  # HOS, DQ, CSA, AUTHORITY, VEHICLE, DRUG_ALCOHOL
    keywords: list[str]


class RegulationLoader:
    """Loads and chunks regulatory documents for ingestion into vector store."""

    CATEGORIES = {
        "fmcsa_hos.md": "HOS",
        "fmcsa_driver_qualification.md": "DQ",
        "csa_scoring.md": "CSA",
        "operating_authority.md": "AUTHORITY",
    }

    def load_all(self) -> list[RegulationChunk]:
        chunks: list[RegulationChunk] = []
        reg_dir = DATA_DIR / "regulations"
        for filename, category in self.CATEGORIES.items():
            path = reg_dir / filename
            if path.exists():
                chunks.extend(self._chunk_document(path.read_text(), category, filename))
        return chunks

    def _chunk_document(self, text: str, category: str, filename: str) -> list[RegulationChunk]:
        chunks: list[RegulationChunk] = []
        sections = text.split("\n### ")
        for i, section in enumerate(sections):
            if not section.strip():
                continue
            lines = section.strip().split("\n")
            title = lines[0].lstrip("# ").strip()
            content = "\n".join(lines[1:]).strip()
            if len(content) < 30:
                continue
            citation = self._extract_citation(content)
            chunk = RegulationChunk(
                id=f"{category.lower()}_{i:03d}",
                title=title,
                content=f"### {title}\n{content}",
                citation=citation or f"49 CFR ({category})",
                category=category,
                keywords=self._extract_keywords(title + " " + content),
            )
            chunks.append(chunk)
        return chunks

    def _extract_citation(self, text: str) -> str | None:
        import re
        match = re.search(r"49 CFR[\s\w.]+", text)
        return match.group(0).strip() if match else None

    def _extract_keywords(self, text: str) -> list[str]:
        keywords = []
        markers = [
            "HOS", "hours of service", "ELD", "driving limit", "off duty", "sleeper berth",
            "CDL", "driver qualification", "DQ file", "medical certificate", "clearinghouse",
            "CSA", "BASIC", "inspection", "out of service", "violation", "crash",
            "operating authority", "insurance", "MC number", "DOT number", "SAFER",
            "drug test", "alcohol", "return to duty", "SAP",
            "hazmat", "hazardous materials", "placard",
        ]
        text_lower = text.lower()
        for kw in markers:
            if kw.lower() in text_lower:
                keywords.append(kw)
        return keywords

    def load_carriers(self) -> list[dict[str, Any]]:
        path = DATA_DIR / "mock" / "carriers.json"
        return json.loads(path.read_text()) if path.exists() else []

    def load_drivers(self) -> list[dict[str, Any]]:
        path = DATA_DIR / "mock" / "drivers.json"
        return json.loads(path.read_text()) if path.exists() else []
