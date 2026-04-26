from __future__ import annotations

import json
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any

import networkx as nx


DATA_DIR = Path(__file__).parent.parent.parent / "data"


class FreightKnowledgeGraph:
    """
    NetworkX-based knowledge graph for freight compliance entities.

    Nodes: Carrier, Driver, Vehicle, Inspection, Violation, Regulation
    Edges: EMPLOYS, RECEIVED, FOUND, CITES, INSPECTED_DRIVER

    Answers relational queries RAG alone cannot:
    - Which regulations are most cited in a carrier's violation history?
    - Which carriers share drivers with Clearinghouse violations?
    - What is the full compliance chain for a given driver?
    """

    def __init__(self) -> None:
        self._g: nx.MultiDiGraph = nx.MultiDiGraph()
        self._built = False

    # ── Build ──────────────────────────────────────────────────────────────────

    def build(self) -> "FreightKnowledgeGraph":
        """Populate graph from all mock data files."""
        self._load_carriers()
        self._load_drivers()
        self._load_inspections()
        self._built = True
        return self

    def _load_carriers(self) -> None:
        path = DATA_DIR / "mock" / "carriers.json"
        if not path.exists():
            return
        for c in json.loads(path.read_text()):
            self._g.add_node(
                f"carrier:{c['dot_number']}",
                type="Carrier",
                dot_number=c["dot_number"],
                name=c["legal_name"],
                state=c.get("state"),
                operating_status=c.get("operating_status"),
                safety_rating=c.get("safety_rating"),
                hm_flag=c.get("hm_flag", False),
                out_of_service=c.get("out_of_service", False),
                insurance_on_file=c.get("insurance_on_file", True),
            )

    def _load_drivers(self) -> None:
        path = DATA_DIR / "mock" / "drivers.json"
        if not path.exists():
            return
        for d in json.loads(path.read_text()):
            self._g.add_node(
                f"driver:{d['license_number']}",
                type="Driver",
                license_number=d["license_number"],
                license_state=d["license_state"],
                cdl_class=d["cdl_class"],
                endorsements=d.get("cdl_endorsements", []),
                clearinghouse_status=d.get("clearinghouse_status", "CLEAR"),
                drug_test_status=d.get("drug_test_status", "NEGATIVE"),
                medical_cert_expiration=str(d.get("medical_cert_expiration", "")),
            )

    def _load_inspections(self) -> None:
        path = DATA_DIR / "mock" / "inspections.json"
        if not path.exists():
            return
        for ins in json.loads(path.read_text()):
            ins_id = ins["inspection_id"]
            dot = ins["dot_number"]
            driver_lic = ins.get("driver_license")

            # Inspection node
            self._g.add_node(
                f"inspection:{ins_id}",
                type="Inspection",
                inspection_id=ins_id,
                date=ins["inspection_date"],
                level=ins["level"],
                oos_driver=ins["oos_driver"],
                oos_vehicle=ins["oos_vehicle"],
                violation_count=len(ins["violations"]),
            )
            # Carrier → Inspection
            carrier_node = f"carrier:{dot}"
            if carrier_node in self._g:
                self._g.add_edge(carrier_node, f"inspection:{ins_id}", rel="RECEIVED")

            # Driver → Inspection (if driver known)
            if driver_lic:
                driver_node = f"driver:{driver_lic}"
                if driver_node in self._g:
                    self._g.add_edge(driver_node, f"inspection:{ins_id}", rel="INSPECTED_IN")
                    # Carrier → Driver (EMPLOYS) — inferred from co-occurrence
                    if carrier_node in self._g:
                        if not self._g.has_edge(carrier_node, driver_node):
                            self._g.add_edge(carrier_node, driver_node, rel="EMPLOYS")

            # Violations
            for v in ins["violations"]:
                viol_node = f"violation:{ins_id}:{v['code']}"
                reg_node = f"regulation:{v['citation']}"

                self._g.add_node(
                    viol_node,
                    type="Violation",
                    code=v["code"],
                    description=v["description"],
                    severity=v["severity"],
                    date=ins["inspection_date"],
                )
                self._g.add_node(
                    reg_node,
                    type="Regulation",
                    citation=v["citation"],
                )

                self._g.add_edge(f"inspection:{ins_id}", viol_node, rel="FOUND")
                self._g.add_edge(viol_node, reg_node, rel="CITES")

    # ── Ingest from external source (FMCSA API / Docling) ─────────────────────

    def add_carrier(self, data: dict[str, Any]) -> str:
        node_id = f"carrier:{data['dot_number']}"
        self._g.add_node(node_id, type="Carrier", **{
            k: v for k, v in data.items()
            if isinstance(v, (str, int, float, bool)) or v is None
        })
        return node_id

    def add_driver(self, data: dict[str, Any]) -> str:
        node_id = f"driver:{data['license_number']}"
        self._g.add_node(node_id, type="Driver", **{
            k: v for k, v in data.items()
            if isinstance(v, (str, int, float, bool, list)) or v is None
        })
        return node_id

    def link_driver_to_carrier(self, license_number: str, dot_number: str) -> None:
        c, d = f"carrier:{dot_number}", f"driver:{license_number}"
        for node, data in [
            (c, {"type": "Carrier", "dot_number": dot_number}),
            (d, {"type": "Driver", "license_number": license_number}),
        ]:
            if node not in self._g:
                self._g.add_node(node, **data)
        if not self._g.has_edge(c, d):
            self._g.add_edge(c, d, rel="EMPLOYS")

    def add_inspection_with_violations(
        self,
        dot_number: str,
        inspection_id: str,
        inspection_date: str,
        violations: list[dict[str, Any]],
        oos_driver: bool = False,
        oos_vehicle: bool = False,
    ) -> None:
        ins_node = f"inspection:{inspection_id}"
        carrier_node = f"carrier:{dot_number}"

        self._g.add_node(ins_node, type="Inspection", inspection_id=inspection_id,
                         date=inspection_date, oos_driver=oos_driver, oos_vehicle=oos_vehicle,
                         violation_count=len(violations))
        if carrier_node not in self._g:
            self._g.add_node(carrier_node, type="Carrier", dot_number=dot_number)
        if not self._has_rel_edge(carrier_node, ins_node, "RECEIVED"):
            self._g.add_edge(carrier_node, ins_node, rel="RECEIVED")

        for v in violations:
            viol_node = f"violation:{inspection_id}:{v['code']}"
            reg_node = f"regulation:{v['citation']}"
            self._g.add_node(viol_node, type="Violation", **v, date=inspection_date)
            self._g.add_node(reg_node, type="Regulation", citation=v["citation"])
            if not self._has_rel_edge(ins_node, viol_node, "FOUND"):
                self._g.add_edge(ins_node, viol_node, rel="FOUND")
            if not self._has_rel_edge(viol_node, reg_node, "CITES"):
                self._g.add_edge(viol_node, reg_node, rel="CITES")

    def _has_rel_edge(self, src: str, dst: str, rel: str) -> bool:
        if not self._g.has_edge(src, dst):
            return False
        for _, attrs in self._g.get_edge_data(src, dst).items():
            if attrs.get("rel") == rel:
                return True
        return False

    # ── Queries ────────────────────────────────────────────────────────────────

    def get_carrier_violation_history(self, dot_number: str) -> list[dict[str, Any]]:
        """All violations for a carrier, newest first."""
        carrier_node = f"carrier:{dot_number}"
        if carrier_node not in self._g:
            return []
        violations = []
        for _, ins_node, edge_data in self._g.out_edges(carrier_node, data=True):
            if edge_data.get("rel") != "RECEIVED":
                continue
            ins_attrs = self._g.nodes[ins_node]
            for _, viol_node, ve in self._g.out_edges(ins_node, data=True):
                if ve.get("rel") != "FOUND":
                    continue
                viol_attrs = self._g.nodes[viol_node]
                for _, reg_node, re in self._g.out_edges(viol_node, data=True):
                    if re.get("rel") == "CITES":
                        reg_attrs = self._g.nodes[reg_node]
                        violations.append({
                            "date": ins_attrs.get("date"),
                            "inspection_id": ins_attrs.get("inspection_id"),
                            "code": viol_attrs.get("code"),
                            "description": viol_attrs.get("description"),
                            "severity": viol_attrs.get("severity"),
                            "citation": reg_attrs.get("citation"),
                            "oos_driver": ins_attrs.get("oos_driver", False),
                            "oos_vehicle": ins_attrs.get("oos_vehicle", False),
                        })
        return sorted(violations, key=lambda x: x.get("date", ""), reverse=True)

    def get_top_cited_regulations(self, dot_number: str, top_n: int = 5) -> list[dict[str, Any]]:
        """Which CFR sections are most frequently violated by this carrier."""
        history = self.get_carrier_violation_history(dot_number)
        counts: dict[str, dict[str, Any]] = defaultdict(lambda: {"count": 0, "total_severity": 0})
        for v in history:
            cit = v["citation"]
            counts[cit]["count"] += 1
            counts[cit]["total_severity"] += v.get("severity", 0)
            counts[cit]["citation"] = cit
        ranked = sorted(counts.values(), key=lambda x: (x["count"], x["total_severity"]), reverse=True)
        return ranked[:top_n]

    def get_driver_compliance_chain(self, license_number: str) -> dict[str, Any]:
        """Full compliance picture for a driver: employer, violations, status."""
        driver_node = f"driver:{license_number}"
        if driver_node not in self._g:
            return {"error": f"Driver {license_number} not in graph"}

        attrs = dict(self._g.nodes[driver_node])

        # Find employer carriers
        employers = [
            dict(self._g.nodes[src])
            for src, _, d in self._g.in_edges(driver_node, data=True)
            if d.get("rel") == "EMPLOYS" and self._g.nodes[src].get("type") == "Carrier"
        ]

        # Driver's own violations via inspections
        violations = []
        for _, ins_node, d in self._g.out_edges(driver_node, data=True):
            if d.get("rel") != "INSPECTED_IN":
                continue
            ins_attrs = self._g.nodes[ins_node]
            for _, viol_node, ve in self._g.out_edges(ins_node, data=True):
                if ve.get("rel") != "FOUND":
                    continue
                viol_attrs = dict(self._g.nodes[viol_node])
                viol_attrs["date"] = ins_attrs.get("date")
                violations.append(viol_attrs)

        return {
            "driver": attrs,
            "employers": employers,
            "violations": sorted(violations, key=lambda x: x.get("date", ""), reverse=True),
            "clearinghouse_status": attrs.get("clearinghouse_status", "UNKNOWN"),
            "drug_test_status": attrs.get("drug_test_status", "UNKNOWN"),
        }

    def find_carriers_with_violation(
        self, citation: str, min_count: int = 1
    ) -> list[dict[str, Any]]:
        """Find all carriers who have been cited for a specific regulation."""
        reg_node = f"regulation:{citation}"
        if reg_node not in self._g:
            return []
        results = []
        for carrier_node in self._g.nodes:
            if self._g.nodes[carrier_node].get("type") != "Carrier":
                continue
            dot = self._g.nodes[carrier_node].get("dot_number", "")
            history = self.get_carrier_violation_history(dot)
            matching = [v for v in history if v.get("citation") == citation]
            if len(matching) >= min_count:
                results.append({
                    "carrier": dict(self._g.nodes[carrier_node]),
                    "violation_count": len(matching),
                    "violations": matching,
                })
        return sorted(results, key=lambda x: x["violation_count"], reverse=True)

    def get_graph_context_for_carrier(self, dot_number: str) -> str:
        """Summarize graph facts about a carrier for use as Claude context."""
        history = self.get_carrier_violation_history(dot_number)
        top_regs = self.get_top_cited_regulations(dot_number)
        carrier_node = f"carrier:{dot_number}"
        if carrier_node not in self._g:
            return f"No graph data for carrier DOT {dot_number}."

        attrs = self._g.nodes[carrier_node]
        drivers = [
            self._g.nodes[n].get("license_number", n)
            for _, n, d in self._g.out_edges(carrier_node, data=True)
            if d.get("rel") == "EMPLOYS"
        ]

        lines = [
            f"## Knowledge Graph: Carrier DOT {dot_number}",
            f"- Name: {attrs.get('name', 'Unknown')}",
            f"- Operating status: {attrs.get('operating_status', 'Unknown')}",
            f"- Safety rating: {attrs.get('safety_rating', 'Unrated')}",
            f"- OOS flag: {attrs.get('out_of_service', False)}",
            f"- Known drivers (graph): {', '.join(drivers) or 'None'}",
            f"",
            f"### Violation History ({len(history)} violations across inspections):",
        ]
        for v in history[:8]:
            lines.append(
                f"  [{v['date']}] {v['citation']} — {v['description']} "
                f"(severity {v['severity']}"
                + (", OOS driver" if v["oos_driver"] else "")
                + (", OOS vehicle" if v["oos_vehicle"] else "")
                + ")"
            )
        if top_regs:
            lines.append(f"")
            lines.append(f"### Most Cited Regulations:")
            for r in top_regs:
                lines.append(f"  {r['citation']}: cited {r['count']}x (total severity {r['total_severity']})")

        return "\n".join(lines)

    def get_graph_context_for_driver(self, license_number: str) -> str:
        """Summarize graph facts about a driver for Claude context."""
        chain = self.get_driver_compliance_chain(license_number)
        if "error" in chain:
            return chain["error"]

        d = chain["driver"]
        lines = [
            f"## Knowledge Graph: Driver {license_number}",
            f"- CDL class: {d.get('cdl_class')} | State: {d.get('license_state')}",
            f"- Endorsements: {', '.join(d.get('endorsements', [])) or 'None'}",
            f"- Clearinghouse: {d.get('clearinghouse_status')}",
            f"- Drug test status: {d.get('drug_test_status')}",
            f"- Medical cert expires: {d.get('medical_cert_expiration', 'Unknown')}",
        ]
        if chain["employers"]:
            lines.append(f"- Known employer(s): {', '.join(e.get('name', e.get('dot_number', '')) for e in chain['employers'])}")
        if chain["violations"]:
            lines.append(f"")
            lines.append(f"### Driver Violation History ({len(chain['violations'])} violations):")
            for v in chain["violations"][:6]:
                lines.append(f"  [{v.get('date','?')}] {v.get('citation','?')} — {v.get('description','?')} (severity {v.get('severity','?')})")
        else:
            lines.append(f"- No violations found in graph")

        return "\n".join(lines)

    # ── Stats ──────────────────────────────────────────────────────────────────

    def stats(self) -> dict[str, Any]:
        type_counts: dict[str, int] = defaultdict(int)
        for _, attrs in self._g.nodes(data=True):
            type_counts[attrs.get("type", "Unknown")] += 1
        rel_counts: dict[str, int] = defaultdict(int)
        for _, _, attrs in self._g.edges(data=True):
            rel_counts[attrs.get("rel", "Unknown")] += 1
        return {
            "nodes": self._g.number_of_nodes(),
            "edges": self._g.number_of_edges(),
            "by_type": dict(type_counts),
            "by_relationship": dict(rel_counts),
        }


# Module-level singleton
_graph: FreightKnowledgeGraph | None = None


def get_graph() -> FreightKnowledgeGraph:
    global _graph
    if _graph is None:
        _graph = FreightKnowledgeGraph().build()
    return _graph
