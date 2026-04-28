from __future__ import annotations

import mimetypes
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .vectorstore import FreightKnowledgeBase
    from .graph import FreightKnowledgeGraph


class DocumentIngester:
    """
    Document ingestion pipeline using Docling for PDF/image parsing.

    Accepts: local PDFs, images (scanned inspection reports, DQ forms),
    plain text, and markdown. Feeds results into both ChromaDB (semantic
    search) and the knowledge graph (entity relationships).

    Docling handles: multi-column PDFs, tables, OCR on scanned pages,
    header/footer stripping — the real-world document formats that trucking
    compliance actually uses.
    """

    def __init__(
        self,
        kb: "FreightKnowledgeBase | None" = None,
        graph: "FreightKnowledgeGraph | None" = None,
    ) -> None:
        if kb is None:
            from .vectorstore import FreightKnowledgeBase
            kb = FreightKnowledgeBase()
        self._kb = kb
        self._kb.ingest()
        self._graph = graph
        self._docling_available = self._check_docling()

    def _check_docling(self) -> bool:
        try:
            import docling  # noqa: F401
            return True
        except ImportError:
            return False

    # ── Public API ─────────────────────────────────────────────────────────────

    def ingest_pdf(
        self,
        path: str | Path,
        category: str = "REGULATION",
        source_type: str = "regulation",
    ) -> dict[str, Any]:
        """
        Ingest a PDF file. Uses Docling if available for layout-aware parsing
        (tables, multi-column), falls back to basic text extraction otherwise.
        """
        path = Path(path)
        if not path.exists():
            return {"error": f"File not found: {path}"}

        if self._docling_available:
            text, metadata = self._parse_with_docling(path)
        else:
            text, metadata = self._parse_basic(path)

        return self._ingest_text(
            text,
            metadata,
            category,
            source=str(path),
            source_type=source_type,
        )

    def ingest_text(
        self,
        text: str,
        title: str = "Ingested Document",
        category: str = "REGULATION",
        source: str = "manual",
        source_type: str = "regulation",
    ) -> dict[str, Any]:
        """Ingest raw text directly — useful for pasted regulation excerpts."""
        metadata = {"title": title, "source": source, "source_type": source_type}
        return self._ingest_text(text, metadata, category, source, source_type=source_type)

    def ingest_image(
        self,
        path: str | Path,
        category: str = "INSPECTION",
        source_type: str = "inspection",
    ) -> dict[str, Any]:
        """
        Ingest an image file (scan/photo). Uses Docling OCR when available.
        """
        path = Path(path)
        if not path.exists():
            return {"error": f"File not found: {path}"}

        if self._docling_available:
            text, metadata = self._parse_with_docling(path)
        else:
            text, metadata = self._parse_basic(path)

        metadata["modality"] = "image"
        metadata["source_type"] = source_type
        return self._ingest_text(text, metadata, category, source=str(path), source_type=source_type)

    def ingest_audio_transcript(
        self,
        transcript: str,
        title: str = "Audio Transcript",
        source: str = "audio_upload",
        category: str = "INTERVIEW",
        source_type: str = "guidance",
    ) -> dict[str, Any]:
        """
        Ingest already-transcribed audio text. Keeps modality metadata so
        downstream evaluators can segment quality by input type.
        """
        metadata = {
            "title": title,
            "source": source,
            "modality": "audio",
            "source_type": source_type,
        }
        return self._ingest_text(transcript, metadata, category, source, source_type=source_type)

    def ingest_inspection_report(self, report: dict[str, Any]) -> dict[str, Any]:
        """
        Ingest a structured inspection report dict (from FMCSA DataQs or API).
        Adds to both KB (for semantic search) and graph (for relational queries).
        """
        dot = report.get("dot_number", "")
        ins_id = report.get("inspection_id", f"INS-{dot}-{report.get('date','0')}")

        # Build natural-language text for ChromaDB
        violations = report.get("violations", [])
        viol_text = "\n".join(
            f"- {v['citation']}: {v['description']} (severity {v['severity']})"
            for v in violations
        ) or "No violations"

        text = (
            f"# Inspection Report {ins_id}\n"
            f"Carrier DOT: {dot}\n"
            f"Date: {report.get('date', 'Unknown')}\n"
            f"Level: {report.get('level', 'Unknown')}\n"
            f"Driver OOS: {report.get('oos_driver', False)}\n"
            f"Vehicle OOS: {report.get('oos_vehicle', False)}\n\n"
            f"## Violations\n{viol_text}"
        )

        kb_result = self._ingest_text(
            text,
            {"title": f"Inspection {ins_id}", "source": "inspection_api", "source_type": "inspection"},
            "INSPECTION",
            source=ins_id,
            source_type="inspection",
        )

        # Add to knowledge graph
        graph_result = {}
        if self._graph:
            self._graph.add_inspection_with_violations(
                dot_number=dot,
                inspection_id=ins_id,
                inspection_date=report.get("date", ""),
                violations=violations,
                oos_driver=report.get("oos_driver", False),
                oos_vehicle=report.get("oos_vehicle", False),
            )
            graph_result = {"graph_nodes_added": len(violations) + 1}

        return {**kb_result, **graph_result, "inspection_id": ins_id}

    # ── Parsing ────────────────────────────────────────────────────────────────

    def _parse_with_docling(self, path: Path) -> tuple[str, dict[str, Any]]:
        """Use Docling for layout-aware PDF parsing."""
        from docling.document_converter import DocumentConverter

        # Build converter with OCR + table structure options when available.
        # Docling's pipeline options API changed between 1.x and 2.x, so we
        # try the modern path first and fall back to a plain converter.
        converter = self._build_docling_converter()
        result = converter.convert(str(path))
        doc = result.document

        # Export to markdown — Docling preserves tables as markdown tables
        markdown = doc.export_to_markdown()

        metadata = {
            "title": doc.name or path.stem,
            "source": str(path),
            "pages": len(doc.pages) if hasattr(doc, "pages") else 0,
            "parser": "docling",
        }
        return markdown, metadata

    def _build_docling_converter(self) -> "Any":
        """Build a DocumentConverter, wiring in pipeline options when possible."""
        from docling.document_converter import DocumentConverter
        try:
            # Docling 2.x API
            from docling.document_converter import PdfFormatOption  # type: ignore
            from docling.datamodel.base_models import InputFormat  # type: ignore
            from docling.datamodel.pipeline_options import PdfPipelineOptions  # type: ignore
            pipeline_opts = PdfPipelineOptions()
            pipeline_opts.do_ocr = True
            pipeline_opts.do_table_structure = True
            return DocumentConverter(
                format_options={
                    InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_opts)
                }
            )
        except Exception:
            # Version mismatch or OCR deps unavailable — use safe defaults
            return DocumentConverter()

    def _parse_basic(self, path: Path) -> tuple[str, dict[str, Any]]:
        """Basic text extraction — works for plain text and simple PDFs."""
        suffix = path.suffix.lower()
        mime, _ = mimetypes.guess_type(str(path))
        if suffix in (".txt", ".md"):
            text = path.read_text(encoding="utf-8", errors="replace")
        elif suffix == ".pdf":
            text = self._extract_pdf_text(path)
        elif mime and mime.startswith("image/"):
            text = (
                f"[Image source: {path.name}]\n"
                "OCR parser unavailable in basic mode. Install docling for OCR extraction."
            )
        else:
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                text = f"[Unsupported binary source: {path.name}]"

        return text, {"title": path.stem, "source": str(path), "parser": "basic"}

    def _extract_pdf_text(self, path: Path) -> str:
        """Minimal PDF text extraction without Docling."""
        try:
            import pypdf  # type: ignore[import-not-found]
            reader = pypdf.PdfReader(str(path))
            return "\n\n".join(
                page.extract_text() or "" for page in reader.pages
            )
        except ImportError:
            pass
        try:
            import pdfplumber  # type: ignore[import-not-found]
            with pdfplumber.open(str(path)) as pdf:
                return "\n\n".join(p.extract_text() or "" for p in pdf.pages)
        except ImportError:
            pass
        return f"[PDF extraction unavailable — install docling or pypdf: {path}]"

    # ── Indexing ───────────────────────────────────────────────────────────────

    def _ingest_text(
        self,
        text: str,
        metadata: dict[str, Any],
        category: str,
        source: str,
        source_type: str = "regulation",
    ) -> dict[str, Any]:
        """Chunk text and upsert into ChromaDB."""
        chunks = self._chunk(text, metadata.get("title", source))
        if not chunks:
            return {"chunks_added": 0, "source": source}

        ids = [f"doc_{_slugify(source)}_{i}" for i in range(len(chunks))]
        documents = [c["text"] for c in chunks]
        metadatas = [
            {
                "title": metadata.get("title", source),
                "citation": _extract_citation(c["text"]) or source,
                "category": category,
                "keywords": ", ".join(_extract_keywords(c["text"])),
                "source": source,
                "modality": metadata.get("modality", "text"),
                "source_type": metadata.get("source_type", source_type),
            }
            for c in chunks
        ]

        self._kb._collection.upsert(ids=ids, documents=documents, metadatas=metadatas)
        return {"chunks_added": len(chunks), "source": source, "category": category}

    def _chunk(self, text: str, title: str, max_chars: int = 1500) -> list[dict[str, Any]]:
        """Split text into semantically coherent chunks at section boundaries."""
        return chunk_text(text, max_chars=max_chars)


# ── Helpers ────────────────────────────────────────────────────────────────────

def chunk_text(text: str, max_chars: int = 1500) -> list[dict[str, Any]]:
    """
    Split text into semantically coherent chunks at section boundaries.
    Module-level so it can be tested or used without initialising DocumentIngester.
    """
    sections = re.split(r"\n(?=#{1,3}\s+|\n)", text)
    chunks: list[dict[str, Any]] = []
    current = ""
    for section in sections:
        section = section.strip()
        if not section:
            continue
        if len(current) + len(section) > max_chars and current:
            chunks.append({"text": current.strip()})
            current = section
        else:
            current = (current + "\n\n" + section) if current else section
    if current.strip():
        chunks.append({"text": current.strip()})
    # Hard-split any chunk that still exceeds max_chars
    final: list[dict[str, Any]] = []
    for chunk in chunks or [{"text": text}]:
        t = chunk["text"]
        while len(t) > max_chars:
            # rfind returns -1 when not found (-1 is truthy, so we check explicitly)
            split_at = t.rfind("\n", 0, max_chars)
            if split_at <= 0:
                split_at = max_chars
            final.append({"text": t[:split_at].strip()})
            t = t[split_at:].strip()
        if t:
            final.append({"text": t})
    return final or [{"text": text[:max_chars]}]


def _slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "_", s.lower())[:40]


def _extract_citation(text: str) -> str | None:
    # Match "49 CFR 395.3(a)(1)" style — stop at non-citation characters
    m = re.search(r"49 CFR\s+[\d]+\.[\d]+[\w.()\-]*", text)
    if m:
        return m.group(0).strip()[:60]
    # Fallback: bare "49 CFR Part NNN"
    m2 = re.search(r"49 CFR\s+Part\s+\d+", text, re.IGNORECASE)
    return m2.group(0).strip()[:60] if m2 else None


def _extract_keywords(text: str) -> list[str]:
    markers = [
        "HOS", "hours of service", "ELD", "CDL", "driver qualification",
        "medical certificate", "clearinghouse", "CSA", "BASIC", "inspection",
        "out of service", "violation", "crash", "operating authority",
        "insurance", "drug test", "alcohol", "hazmat",
    ]
    text_lower = text.lower()
    return [kw for kw in markers if kw.lower() in text_lower]
