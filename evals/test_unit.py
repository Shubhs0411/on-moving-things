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
