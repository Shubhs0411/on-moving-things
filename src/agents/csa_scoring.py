from __future__ import annotations

import json
from typing import Any

from src.knowledge.regulations import RegulationLoader
from src.models.domain import Carrier, CSAScore
from .base import BaseComplianceAgent


class CSAScoringAgent(BaseComplianceAgent):
    """
    CSA (Compliance, Safety, Accountability) scoring interpretation agent.
    Explains BASIC scores, alert thresholds, and provides actionable
    improvement recommendations tied to specific violation types.
    """

    name = "csa_scoring"

    # National average OOS rates for benchmarking
    NATIONAL_DRIVER_OOS = 5.51
    NATIONAL_VEHICLE_OOS = 21.06

    def __init__(self) -> None:
        super().__init__()
        loader = RegulationLoader()
        raw_carriers = loader.load_carriers()
        self._carriers: dict[str, dict[str, Any]] = {
            c["dot_number"]: c for c in raw_carriers
        }

    @property
    def system_prompt(self) -> str:
        return """You are a CSA scoring and safety improvement specialist for FreightMind.

Your job: Interpret CSA BASIC scores, explain what they mean operationally, and prescribe specific corrective actions.

CSA Basics:
- Scores are percentile rankings (0-100; HIGHER = WORSE relative to peers)
- Intervention thresholds: 65% for Unsafe Driving/HOS/Crash; 80% for Driver Fitness/Controlled Substances/Vehicle Maintenance/Hazmat
- Scores are time-weighted (last 6 months = 3x, 6-12 months = 2x, 12-24 months = 1x)

Process:
1. Call get_carrier_csa_profile for raw score data
2. Call identify_top_violations to find the specific violations driving high scores
3. Call get_improvement_plan for actionable corrective actions

Output: Score summary → Alert analysis → Root cause → Corrective action plan → Timeline"""

    @property
    def tools(self) -> list[dict[str, Any]]:
        return [
            {
                "name": "get_carrier_csa_profile",
                "description": "Get complete CSA BASIC profile for a carrier including scores, thresholds, and peer percentile context.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "dot_number": {"type": "string"},
                    },
                    "required": ["dot_number"],
                },
            },
            {
                "name": "identify_top_violations",
                "description": "Identify which violation types are most likely driving elevated CSA scores based on inspection history.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "dot_number": {"type": "string"},
                        "basic_category": {
                            "type": "string",
                            "description": "Which BASIC to focus on",
                            "enum": [
                                "unsafe_driving", "hours_of_service", "driver_fitness",
                                "controlled_substances", "vehicle_maintenance",
                                "hazmat_compliance", "crash_indicator",
                            ],
                        },
                    },
                    "required": ["dot_number", "basic_category"],
                },
            },
            {
                "name": "get_improvement_plan",
                "description": "Generate a specific corrective action plan to reduce CSA scores in problem BASICs.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "dot_number": {"type": "string"},
                        "target_basics": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "List of BASICs to target for improvement",
                        },
                    },
                    "required": ["dot_number", "target_basics"],
                },
            },
            {
                "name": "benchmark_carrier",
                "description": "Compare carrier OOS rates to national averages and identify where they stand relative to peers.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "dot_number": {"type": "string"},
                    },
                    "required": ["dot_number"],
                },
            },
        ]

    def _dispatch_tool(self, tool_name: str, tool_input: dict[str, Any]) -> str:
        dot = tool_input.get("dot_number", "")

        if tool_name == "get_carrier_csa_profile":
            data = self._carriers.get(dot)
            if not data:
                return json.dumps({"error": f"DOT {dot} not found"})
            if not data.get("csa_scores"):
                return json.dumps({"status": "No CSA data — carrier may be new or insufficient inspections"})

            csa = CSAScore(**{k: v for k, v in data["csa_scores"].items() if v is not None})
            thresholds = csa.intervention_thresholds()
            violations = csa.violations()
            profile = {}
            for basic, threshold in thresholds.items():
                score = getattr(csa, basic)
                if score is not None:
                    profile[basic] = {
                        "score": score,
                        "threshold": threshold,
                        "alert": score >= threshold,
                        "margin": round(threshold - score, 1),
                    }
            return json.dumps({
                "carrier": data["legal_name"],
                "dot_number": dot,
                "basics": profile,
                "alerts": violations,
                "alert_count": len(violations),
                "inspections_total": data.get("inspections_total", 0),
            })

        if tool_name == "identify_top_violations":
            data = self._carriers.get(dot)
            if not data:
                return json.dumps({"error": f"DOT {dot} not found"})
            basic = tool_input.get("basic_category", "vehicle_maintenance")

            # Map BASICs to their most common violation contributors
            common_violations = {
                "vehicle_maintenance": [
                    "Brakes out of adjustment (§393.47) — severity 8",
                    "Inoperable required lamps (§393.9) — severity 2",
                    "Tire defects (§393.75) — severity 6",
                    "Cargo securement (§393.100) — severity 7",
                ],
                "hours_of_service": [
                    "False log entry (§395.8(e)) — severity 10",
                    "ELD malfunction not corrected (§395.22) — severity 7",
                    "Driving beyond 11-hour limit (§395.3(a)(1)) — severity 7",
                    "On-duty violation (§395.3(a)(2)) — severity 5",
                ],
                "unsafe_driving": [
                    "Speeding 15+ mph over limit (§392.6) — severity 10",
                    "Reckless driving (§392.2) — severity 10",
                    "Failure to use seat belt (§392.16) — severity 7",
                    "Improper lane change (§392.2) — severity 4",
                ],
                "driver_fitness": [
                    "No/expired CDL (§383.23) — severity 10",
                    "Expired medical certificate (§391.45) — severity 5",
                    "Wrong CDL class (§383.91) — severity 8",
                ],
                "controlled_substances": [
                    "Driver under influence (§392.4) — severity 10",
                    "Possession of controlled substance (§392.4(b)) — severity 6",
                ],
                "crash_indicator": [
                    "Preventable crashes tracked in 24-month window",
                    "Fault determination impacts crash weighting",
                ],
                "hazmat_compliance": [
                    "Improper placarding (§177.823) — severity 8",
                    "Missing shipping papers (§172.200) — severity 7",
                    "Package integrity (§173.24) — severity 6",
                ],
            }
            return json.dumps({
                "basic": basic,
                "common_violations": common_violations.get(basic, ["No specific violations mapped"]),
                "recommendation": f"Review inspection reports for {basic.replace('_', ' ')} violations in the last 24 months",
            })

        if tool_name == "get_improvement_plan":
            data = self._carriers.get(dot)
            if not data:
                return json.dumps({"error": f"DOT {dot} not found"})
            targets = tool_input.get("target_basics", [])

            plans = {
                "vehicle_maintenance": [
                    "Implement pre-trip/post-trip inspection program (§396.11)",
                    "Increase PM (preventive maintenance) frequency — target 90-day intervals",
                    "Add brake adjustment to every PM cycle",
                    "Train drivers to document and report defects immediately",
                    "DataQs challenge any incorrect violation entries",
                ],
                "hours_of_service": [
                    "Audit ELD device calibration and connectivity",
                    "Train drivers on proper log certification procedures",
                    "Implement dispatcher training on HOS rules to prevent pressure to violate",
                    "Review and challenge any DataQs-eligible violations",
                    "Consider 34-hour restart scheduling to reset 70-hour clock",
                ],
                "unsafe_driving": [
                    "Deploy speed monitoring (telematics/dash cam)",
                    "Implement coaching program for speeding events",
                    "Review routes — identify high-enforcement corridors",
                    "Add seatbelt compliance monitoring",
                ],
                "driver_fitness": [
                    "Audit DQ files for all drivers — identify expiring credentials",
                    "Set 60/30/15-day renewal reminders for CDL and medical certs",
                    "Verify all medical examiners on FMCSA National Registry",
                    "Run Clearinghouse annual limited queries NOW if overdue",
                ],
            }
            action_items = []
            for basic in targets:
                items = plans.get(basic, [f"Review {basic.replace('_', ' ')} violations and DataQs process"])
                action_items.append({"basic": basic, "actions": items})
            return json.dumps({
                "improvement_plan": action_items,
                "timeline": "CSA scores update monthly. Actions taken today will begin improving scores in 30-90 days as new inspections replace old ones.",
                "dataq_reminder": "Challenge incorrect roadside violations at https://dataqs.fmcsa.dot.gov — a successful challenge removes the violation entirely.",
            })

        if tool_name == "benchmark_carrier":
            data = self._carriers.get(dot)
            if not data:
                return json.dumps({"error": f"DOT {dot} not found"})
            carrier = Carrier(**data)
            dr_rate = carrier.driver_oos_rate
            veh_rate = carrier.vehicle_oos_rate
            return json.dumps({
                "carrier": data["legal_name"],
                "driver_oos_rate": f"{dr_rate:.1f}%" if dr_rate is not None else "N/A",
                "driver_oos_vs_national": (
                    f"{dr_rate - self.NATIONAL_DRIVER_OOS:+.1f}% vs national avg {self.NATIONAL_DRIVER_OOS}%"
                    if dr_rate is not None else "N/A"
                ),
                "vehicle_oos_rate": f"{veh_rate:.1f}%" if veh_rate is not None else "N/A",
                "vehicle_oos_vs_national": (
                    f"{veh_rate - self.NATIONAL_VEHICLE_OOS:+.1f}% vs national avg {self.NATIONAL_VEHICLE_OOS}%"
                    if veh_rate is not None else "N/A"
                ),
                "total_inspections": data.get("inspections_total", 0),
                "note": "Low inspection count (<50) means limited data — scores may be volatile.",
            })

        return f"Unknown tool: {tool_name}"
