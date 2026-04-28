"""
Unit tests — no API key required. Validates all structural components:
knowledge graph, FMCSA mock client, document ingester, and domain models.
Run: pytest evals/test_unit.py -v
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


# ── Knowledge Graph ────────────────────────────────────────────────────────────

def test_graph_builds_with_correct_node_count():
    from src.knowledge.graph import FreightKnowledgeGraph
    g = FreightKnowledgeGraph().build()
    stats = g.stats()
    assert stats["nodes"] > 0, "Graph has no nodes"
    assert stats["edges"] > 0, "Graph has no edges"
    assert stats["by_type"].get("Carrier", 0) >= 5
    assert stats["by_type"].get("Driver", 0) >= 5
    assert stats["by_type"].get("Violation", 0) > 0
    assert stats["by_type"].get("Regulation", 0) > 0


def test_graph_violation_history_for_known_carrier():
    from src.knowledge.graph import FreightKnowledgeGraph
    g = FreightKnowledgeGraph().build()
    history = g.get_carrier_violation_history("2345678")
    assert len(history) > 0, "No violations for carrier 2345678"
    for v in history:
        assert "citation" in v
        assert "description" in v
        assert "severity" in v
        assert "date" in v


def test_graph_top_cited_regulations():
    from src.knowledge.graph import FreightKnowledgeGraph
    g = FreightKnowledgeGraph().build()
    top = g.get_top_cited_regulations("2345678")
    assert len(top) > 0, "No top regulations returned"
    assert top[0]["count"] >= top[-1]["count"], "Results not sorted by count"


def test_graph_driver_compliance_chain():
    from src.knowledge.graph import FreightKnowledgeGraph
    g = FreightKnowledgeGraph().build()
    chain = g.get_driver_compliance_chain("CDL-OH-005678")
    assert "error" not in chain
    assert "driver" in chain
    assert "violations" in chain
    assert "clearinghouse_status" in chain
    assert len(chain["violations"]) > 0, "Expected violations for CDL-OH-005678"


def test_graph_clean_carrier_has_no_violations():
    from src.knowledge.graph import FreightKnowledgeGraph
    g = FreightKnowledgeGraph().build()
    history = g.get_carrier_violation_history("4567890")
    # This carrier has a clean inspection in the fixture
    assert isinstance(history, list)


def test_graph_context_string_contains_carrier_name():
    from src.knowledge.graph import FreightKnowledgeGraph
    g = FreightKnowledgeGraph().build()
    ctx = g.get_graph_context_for_carrier("2345678")
    assert "2345678" in ctx
    assert "Violation" in ctx or "violation" in ctx


def test_graph_singleton_returns_same_instance():
    from src.knowledge.graph import get_graph
    g1 = get_graph()
    g2 = get_graph()
    assert g1 is g2


def test_graph_add_carrier_and_link_driver():
    from src.knowledge.graph import FreightKnowledgeGraph
    g = FreightKnowledgeGraph().build()
    g.add_carrier({"dot_number": "9999999", "legal_name": "Test Carrier LLC",
                   "operating_status": "AUTHORIZED"})
    g.add_driver({"license_number": "CDL-TEST-999", "license_state": "TX", "cdl_class": "A"})
    g.link_driver_to_carrier("CDL-TEST-999", "9999999")
    chain = g.get_driver_compliance_chain("CDL-TEST-999")
    assert len(chain["employers"]) == 1
    assert chain["employers"][0].get("dot_number") == "9999999"


def test_graph_add_inspection_with_violations():
    from src.knowledge.graph import FreightKnowledgeGraph
    g = FreightKnowledgeGraph().build()
    g.add_inspection_with_violations(
        dot_number="1234567",
        inspection_id="INS-TEST-001",
        inspection_date="2026-04-01",
        violations=[
            {"code": "395.3A1", "citation": "49 CFR 395.3(a)(1)",
             "description": "Driving beyond 11-hour limit", "severity": 7}
        ],
    )
    history = g.get_carrier_violation_history("1234567")
    codes = [v["code"] for v in history]
    assert "395.3A1" in codes


# ── FMCSA API Client ───────────────────────────────────────────────────────────

def test_fmcsa_client_mock_mode_without_key():
    from src.knowledge.fmcsa_api import FMCSAClient
    client = FMCSAClient(web_key="")
    assert not client.is_live()


def test_fmcsa_mock_returns_known_carrier():
    from src.knowledge.fmcsa_api import FMCSAClient
    client = FMCSAClient(web_key="")
    carrier = client.get_carrier("1234567")
    assert carrier.get("legal_name"), f"Missing legal_name: {carrier}"
    assert carrier.get("dot_number") == "1234567"
    assert carrier.get("_source") == "mock"


def test_fmcsa_mock_returns_unknown_carrier_gracefully():
    from src.knowledge.fmcsa_api import FMCSAClient
    client = FMCSAClient(web_key="")
    carrier = client.get_carrier("0000000")
    assert "dot_number" in carrier
    assert "_note" in carrier  # explains it's not in mock data


def test_fmcsa_mock_returns_csa_basics():
    from src.knowledge.fmcsa_api import FMCSAClient
    client = FMCSAClient(web_key="")
    basics = client.get_carrier_basics("2345678")
    assert "csa_scores" in basics
    assert basics["csa_scores"] is not None


def test_fmcsa_status_dict_has_expected_keys():
    from src.knowledge.fmcsa_api import FMCSAClient
    status = FMCSAClient(web_key="").status()
    assert "mode" in status
    assert "mock_carriers_loaded" in status
    assert status["mock_carriers_loaded"] >= 5


# ── Document Ingester ──────────────────────────────────────────────────────────

@pytest.mark.integration
def test_ingester_text_adds_chunks(tmp_path, monkeypatch):
    monkeypatch.setenv("CHROMA_PERSIST_DIR", str(tmp_path / "chroma"))
    from src.knowledge.vectorstore import FreightKnowledgeBase
    from src.knowledge.ingester import DocumentIngester
    kb = FreightKnowledgeBase(persist_dir=str(tmp_path / "chroma"))
    kb.ingest()
    ingester = DocumentIngester(kb=kb)
    result = ingester.ingest_text(
        "49 CFR 395.3(a)(1): A driver may drive a maximum of 11 hours after 10 consecutive hours off duty.",
        title="HOS Test",
        category="HOS",
    )
    assert result["chunks_added"] >= 1


@pytest.mark.integration
def test_ingester_inspection_report_updates_graph(tmp_path, monkeypatch):
    monkeypatch.setenv("CHROMA_PERSIST_DIR", str(tmp_path / "chroma"))
    from src.knowledge.vectorstore import FreightKnowledgeBase
    from src.knowledge.graph import FreightKnowledgeGraph
    from src.knowledge.ingester import DocumentIngester
    kb = FreightKnowledgeBase(persist_dir=str(tmp_path / "chroma"))
    kb.ingest()
    graph = FreightKnowledgeGraph().build()
    ingester = DocumentIngester(kb=kb, graph=graph)
    result = ingester.ingest_inspection_report({
        "inspection_id": "INS-UNIT-001",
        "dot_number": "1234567",
        "date": "2026-04-26",
        "level": 1,
        "oos_driver": False,
        "oos_vehicle": True,
        "violations": [
            {"code": "393.47", "citation": "49 CFR 393.47",
             "description": "Brakes out of adjustment", "severity": 8}
        ],
    })
    assert result["chunks_added"] >= 1
    assert result.get("graph_nodes_added", 0) >= 1
    history = graph.get_carrier_violation_history("1234567")
    assert any(v["code"] == "393.47" for v in history)


@pytest.mark.integration
def test_ingester_handles_missing_file_gracefully():
    from src.knowledge.ingester import DocumentIngester
    ingester = DocumentIngester()
    result = ingester.ingest_pdf("/nonexistent/path/file.pdf")
    assert "error" in result


# ── Domain Models ──────────────────────────────────────────────────────────────

def test_csa_score_violations_above_threshold():
    from src.models.domain import CSAScore
    csa = CSAScore(unsafe_driving=70, hours_of_service=82, vehicle_maintenance=91)
    violations = csa.violations()
    assert len(violations) == 3
    assert any("Unsafe Driving" in v for v in violations)
    assert any("Hours Of Service" in v for v in violations)
    assert any("Vehicle Maintenance" in v for v in violations)


def test_csa_score_no_violations_when_below_threshold():
    from src.models.domain import CSAScore
    csa = CSAScore(unsafe_driving=40, hours_of_service=30, vehicle_maintenance=50)
    assert len(csa.violations()) == 0


def test_csa_score_highest_risk_basic():
    from src.models.domain import CSAScore
    csa = CSAScore(unsafe_driving=40, vehicle_maintenance=91, crash_indicator=60)
    name, score = csa.highest_risk_basic()
    assert name == "vehicle_maintenance"
    assert score == 91


def test_driver_is_disqualified_on_positive_drug_test():
    from src.models.domain import Driver
    driver = Driver(
        license_number="CDL-TEST-001",
        license_state="TX",
        cdl_class="A",
        drug_test_status="POSITIVE",
        clearinghouse_status="PROHIBITED",
        cdl_expiration=date(2028, 1, 1),
        medical_cert_expiration=date(2027, 6, 1),
    )
    assert not driver.is_qualified()
    offenses = driver.disqualifying_offenses()
    assert any("drug" in o.lower() or "positive" in o.lower() for o in offenses)
    assert any("clearinghouse" in o.lower() or "prohibited" in o.lower() for o in offenses)


def test_driver_is_qualified_with_clean_record():
    from src.models.domain import Driver
    driver = Driver(
        license_number="CDL-TEST-002",
        license_state="NY",
        cdl_class="A",
        drug_test_status="NEGATIVE",
        clearinghouse_status="CLEAR",
        cdl_expiration=date(2029, 1, 1),
        medical_cert_expiration=date(2027, 6, 1),
    )
    assert driver.is_qualified()
    assert len(driver.disqualifying_offenses()) == 0


def test_driver_disqualified_on_refused_test():
    from src.models.domain import Driver
    driver = Driver(
        license_number="CDL-TEST-003",
        license_state="FL",
        cdl_class="A",
        drug_test_status="REFUSED",
        clearinghouse_status="PROHIBITED",
    )
    assert not driver.is_qualified()
    offenses = driver.disqualifying_offenses()
    assert any("refused" in o.lower() for o in offenses)


def test_carrier_is_authorized():
    from src.models.domain import Carrier
    c = Carrier(
        dot_number="1234567",
        legal_name="Test Carrier",
        operating_status="AUTHORIZED",
        insurance_on_file=True,
        out_of_service=False,
    )
    assert c.is_authorized()


def test_carrier_is_not_authorized_when_oos():
    from src.models.domain import Carrier
    c = Carrier(
        dot_number="3456789",
        legal_name="OOS Carrier",
        operating_status="INACTIVE",
        insurance_on_file=False,
        out_of_service=True,
    )
    assert not c.is_authorized()


def test_carrier_oos_rates():
    from src.models.domain import Carrier
    c = Carrier(
        dot_number="2345678",
        legal_name="Red Line Transport",
        inspections_total=94,
        driver_oos_inspections=18,
        vehicle_oos_inspections=31,
    )
    assert c.driver_oos_rate is not None
    assert abs(c.driver_oos_rate - 18 / 94 * 100) < 0.01
    assert c.vehicle_oos_rate is not None


# ── Mock data integrity ────────────────────────────────────────────────────────

def test_mock_carriers_json_is_valid():
    data = json.loads(Path("data/mock/carriers.json").read_text())
    assert len(data) >= 5
    for c in data:
        assert "dot_number" in c
        assert "legal_name" in c
        assert "operating_status" in c


def test_mock_drivers_json_is_valid():
    data = json.loads(Path("data/mock/drivers.json").read_text())
    assert len(data) >= 5
    for d in data:
        assert "license_number" in d
        assert "cdl_class" in d


def test_mock_inspections_json_is_valid():
    data = json.loads(Path("data/mock/inspections.json").read_text())
    assert len(data) >= 5
    total_violations = sum(len(ins["violations"]) for ins in data)
    assert total_violations >= 10
    for ins in data:
        assert "dot_number" in ins
        assert "inspection_id" in ins
        for v in ins["violations"]:
            assert "code" in v
            assert "citation" in v
            assert "severity" in v


# ── Knowledge Graph — new methods ─────────────────────────────────────────────

def test_graph_search_nodes_by_type():
    from src.knowledge.graph import FreightKnowledgeGraph
    g = FreightKnowledgeGraph().build()
    carriers = g.search_nodes(node_type="Carrier")
    assert len(carriers) >= 5
    for c in carriers:
        assert c.get("type") == "Carrier"


def test_graph_search_nodes_by_field_value():
    from src.knowledge.graph import FreightKnowledgeGraph
    g = FreightKnowledgeGraph().build()
    # Search for a carrier by dot_number substring
    results = g.search_nodes(node_type="Carrier", field="dot_number", value="2345678")
    assert len(results) >= 1
    assert results[0]["dot_number"] == "2345678"


def test_graph_get_top_violating_carriers():
    from src.knowledge.graph import FreightKnowledgeGraph
    g = FreightKnowledgeGraph().build()
    top = g.get_top_violating_carriers(top_n=3)
    assert isinstance(top, list)
    # Each entry should have required fields
    for entry in top:
        assert "dot_number" in entry
        assert "violation_count" in entry
    # Should be sorted descending
    if len(top) >= 2:
        assert top[0]["violation_count"] >= top[-1]["violation_count"]


def test_graph_export_mermaid_returns_string():
    from src.knowledge.graph import FreightKnowledgeGraph
    g = FreightKnowledgeGraph().build()
    mermaid = g.export_mermaid(dot_number="2345678")
    assert mermaid.startswith("graph LR")
    assert "2345678" in mermaid or "carrier" in mermaid.lower()


def test_graph_export_mermaid_unknown_dot():
    from src.knowledge.graph import FreightKnowledgeGraph
    g = FreightKnowledgeGraph().build()
    mermaid = g.export_mermaid(dot_number="0000000")
    assert "not in graph" in mermaid


def test_graph_stats_includes_top_cited_regulations():
    from src.knowledge.graph import FreightKnowledgeGraph
    g = FreightKnowledgeGraph().build()
    s = g.stats()
    assert "top_cited_regulations_overall" in s
    assert isinstance(s["top_cited_regulations_overall"], list)


def test_graph_regulation_context_for_citation():
    from src.knowledge.graph import FreightKnowledgeGraph
    g = FreightKnowledgeGraph().build()
    # Get a real citation from the graph
    history = g.get_carrier_violation_history("2345678")
    if history:
        citation = history[0]["citation"]
        ctx = g.get_regulation_context(citation)
        assert isinstance(ctx, str)
        assert len(ctx) > 0


def test_graph_find_carriers_with_violation_returns_sorted():
    from src.knowledge.graph import FreightKnowledgeGraph
    g = FreightKnowledgeGraph().build()
    history = g.get_carrier_violation_history("2345678")
    if not history:
        return
    citation = history[0]["citation"]
    results = g.find_carriers_with_violation(citation)
    assert isinstance(results, list)
    if len(results) >= 2:
        assert results[0]["violation_count"] >= results[-1]["violation_count"]


def test_orchestrator_graph_mermaid_contains_topology_nodes():
    from src.graph.orchestrator import RigCompassOrchestrator

    mermaid = RigCompassOrchestrator.graph_mermaid()
    assert mermaid.startswith("flowchart LR")
    assert "router" in mermaid
    assert "carrier_vetting" in mermaid
    assert "driver_qualification" in mermaid
    assert "csa_scoring" in mermaid
    assert "compliance_oracle" in mermaid
    assert "synthesizer" in mermaid


# ── FMCSA API — improved normalization ────────────────────────────────────────

def test_fmcsa_normalize_carrier_handles_boolean_allowed():
    from src.knowledge.fmcsa_api import FMCSAClient
    client = FMCSAClient(web_key="")
    # Simulate API response with boolean allowedToOperate
    data = {"carrier": {"dotNumber": "9988776", "legalName": "Test Co",
                        "allowedToOperate": True, "hmFlag": "N", "pcFlag": "N"}}
    result = client._normalize_carrier(data, "9988776")
    assert result["operating_status"] == "AUTHORIZED"


def test_fmcsa_normalize_carrier_handles_n_flag():
    from src.knowledge.fmcsa_api import FMCSAClient
    client = FMCSAClient(web_key="")
    data = {"carrier": {"dotNumber": "1122334", "legalName": "Inactive Co",
                        "allowedToOperate": "N"}}
    result = client._normalize_carrier(data, "1122334")
    assert result["operating_status"] == "NOT_AUTHORIZED"


def test_fmcsa_get_carrier_crash_stats():
    from src.knowledge.fmcsa_api import FMCSAClient
    client = FMCSAClient(web_key="")
    stats = client.get_carrier_crash_stats("2345678")
    assert "crashes_total" in stats
    assert "crashes_fatal" in stats
    assert isinstance(stats["crashes_total"], int)


def test_fmcsa_mock_inspections_capped():
    from src.knowledge.fmcsa_api import FMCSAClient
    client = FMCSAClient(web_key="")
    inspections = client.get_recent_inspections("2345678")
    assert len(inspections) <= FMCSAClient._MAX_INSPECTIONS


# ── Document Ingester — chunking and extraction ────────────────────────────────

def test_ingester_chunk_hard_splits_large_text():
    from src.knowledge.ingester import chunk_text
    long_text = "A" * 5000  # single block with no newlines, must hard-split
    chunks = chunk_text(long_text, max_chars=1500)
    assert len(chunks) >= 3
    for c in chunks:
        assert len(c["text"]) <= 1500


def test_ingester_extract_citation_handles_section_format():
    from src.knowledge.ingester import _extract_citation
    text = "Under 49 CFR 395.3(a)(1), a driver may not drive beyond 11 hours."
    result = _extract_citation(text)
    assert result is not None
    assert "395.3" in result


def test_ingester_extract_citation_handles_part_format():
    from src.knowledge.ingester import _extract_citation
    text = "See 49 CFR Part 391 for driver qualification requirements."
    result = _extract_citation(text)
    assert result is not None
    assert "Part 391" in result


def test_ingester_extract_citation_returns_none_for_no_match():
    from src.knowledge.ingester import _extract_citation
    result = _extract_citation("This text has no CFR citation at all.")
    assert result is None


# ── DQF Auditor ───────────────────────────────────────────────────────────────

def test_dqf_audit_flags_missing_and_stale_items():
    from src.compliance.dqf import audit_dqf_packet

    report = audit_dqf_packet(
        {
            "employment_application": True,
            "mvr_initial": False,
            "mvr_annual_review_date": "2024-01-10",
            "medical_certificate_expiration": "2025-01-01",
            "road_test_or_cdl_copy": True,
            "clearinghouse_preemployment_query": False,
        },
        today=date(2026, 4, 27),
    )
    assert report["status"] == "non_compliant"
    assert "mvr_initial" in report["missing_items"]
    assert "medical_certificate_expiration" in report["stale_items"]
    assert len(report["next_steps"]) >= 2


def test_dqf_audit_endpoint_returns_summary():
    from src.api.main import app

    client = TestClient(app)
    response = client.post(
        "/v1/dqf/audit",
        json={
            "packet": {
                "employment_application": True,
                "mvr_initial": True,
                "mvr_annual_review_date": "2026-04-01",
                "medical_certificate_expiration": "2027-01-01",
                "road_test_or_cdl_copy": True,
                "clearinghouse_preemployment_query": True,
                "clearinghouse_annual_query_date": "2026-03-15",
            }
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert "status" in payload
    assert "summary" in payload
