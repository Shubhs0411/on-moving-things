from __future__ import annotations

import json
from typing import Any

from src.knowledge.regulations import RegulationLoader
from src.models.domain import (
    Carrier, CSAScore, ComplianceReport, ComplianceStatus, Finding, RiskLevel
)
from .base import BaseComplianceAgent


class CarrierVettingAgent(BaseComplianceAgent):
    """
    Carrier safety vetting agent. Checks operating authority, insurance,
    safety rating, CSA scores, and crash history for a given DOT number.
    """

    name = "carrier_vetting"

    def __init__(self) -> None:
        super().__init__()
        loader = RegulationLoader()
        raw_carriers = loader.load_carriers()
        self._carriers: dict[str, dict[str, Any]] = {
            c["dot_number"]: c for c in raw_carriers
        }

    @property
    def system_prompt(self) -> str:
        return """You are a carrier safety vetting specialist for the FreightMind platform.

Your job: Evaluate motor carriers for compliance and safety risk before a shipper or broker engages them.

Process:
1. Call lookup_carrier with the DOT number
2. Call check_csa_scores to interpret CSA BASIC percentile scores
3. Call calculate_risk_score to get structured risk assessment
4. Synthesize findings into a clear recommendation

Output format:
- Overall status: COMPLIANT / NON_COMPLIANT / CONDITIONAL
- Risk level: LOW / MEDIUM / HIGH / CRITICAL
- Key findings (bullet points with CFR citations)
- Recommendation: Approve / Approve with conditions / Do not use

Be direct. A shipper needs a clear answer, not a hedge."""

    @property
    def tools(self) -> list[dict[str, Any]]:
        return [
            {
                "name": "lookup_carrier",
                "description": "Look up carrier data by DOT number. Returns operating authority, insurance, safety rating, and inspection history.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "dot_number": {"type": "string", "description": "FMCSA DOT number"}
                    },
                    "required": ["dot_number"],
                },
            },
            {
                "name": "check_csa_scores",
                "description": "Interpret CSA BASIC percentile scores for a carrier. Flags any scores above intervention thresholds.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "dot_number": {"type": "string"},
                        "scores": {
                            "type": "object",
                            "description": "CSA BASIC scores dict",
                        },
                    },
                    "required": ["dot_number"],
                },
            },
            {
                "name": "calculate_risk_score",
                "description": "Calculate composite risk score for a carrier based on all available data points.",
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

        if tool_name == "lookup_carrier":
            carrier_data = self._carriers.get(dot)
            if not carrier_data:
                return json.dumps({"error": f"No carrier found for DOT {dot}"})
            return json.dumps(carrier_data, default=str)

        if tool_name == "check_csa_scores":
            carrier_data = self._carriers.get(dot)
            if not carrier_data or not carrier_data.get("csa_scores"):
                return json.dumps({"status": "No CSA data available"})

            scores = carrier_data["csa_scores"]
            csa = CSAScore(**{k: v for k, v in scores.items() if v is not None})
            thresholds = csa.intervention_thresholds()
            violations = csa.violations()
            alerts = []
            for basic, threshold in thresholds.items():
                score = getattr(csa, basic)
                if score is not None:
                    alerts.append({
                        "basic": basic.replace("_", " ").title(),
                        "score": score,
                        "threshold": threshold,
                        "alert": score >= threshold,
                    })

            return json.dumps({
                "alerts": alerts,
                "violations": violations,
                "alert_count": len(violations),
                "interpretation": (
                    f"{len(violations)} BASIC(s) above intervention threshold. "
                    "FMCSA may prioritize this carrier for investigation."
                    if violations else "All CSA scores below intervention thresholds."
                ),
            })

        if tool_name == "calculate_risk_score":
            carrier_data = self._carriers.get(dot)
            if not carrier_data:
                return json.dumps({"error": f"DOT {dot} not found"})

            carrier = Carrier(**carrier_data)
            risk_factors = []
            risk_score = 0.0

            if not carrier.is_authorized():
                risk_score += 100
                risk_factors.append("CRITICAL: Carrier not authorized to operate")
            if carrier.safety_rating == "UNSATISFACTORY":
                risk_score += 80
                risk_factors.append("HIGH: Unsatisfactory safety rating")
            elif carrier.safety_rating == "CONDITIONAL":
                risk_score += 40
                risk_factors.append("MEDIUM: Conditional safety rating")

            if carrier.csa_scores:
                csa = CSAScore(**{
                    k: v for k, v in carrier.csa_scores.model_dump().items()
                    if v is not None
                }) if hasattr(carrier.csa_scores, "model_dump") else carrier.csa_scores
                violations = csa.violations() if hasattr(csa, "violations") else []
                risk_score += len(violations) * 15
                for v in violations:
                    risk_factors.append(f"CSA Alert: {v}")

            dr_rate = carrier.driver_oos_rate
            if dr_rate is not None and dr_rate > 10:
                risk_score += 20
                risk_factors.append(
                    f"Driver OOS rate {dr_rate:.1f}% (national avg ~5.5%)"
                )

            veh_rate = carrier.vehicle_oos_rate
            if veh_rate is not None and veh_rate > 30:
                risk_score += 15
                risk_factors.append(
                    f"Vehicle OOS rate {veh_rate:.1f}% (national avg ~21%)"
                )

            if carrier.crashes_fatal > 0:
                risk_score += 25
                risk_factors.append(f"Fatal crash history: {carrier.crashes_fatal} fatal crash(es)")

            risk_level = (
                "CRITICAL" if risk_score >= 100
                else "HIGH" if risk_score >= 60
                else "MEDIUM" if risk_score >= 30
                else "LOW"
            )
            return json.dumps({
                "composite_risk_score": round(risk_score, 1),
                "risk_level": risk_level,
                "factors": risk_factors,
                "recommendation": (
                    "DO NOT USE" if risk_score >= 100
                    else "USE WITH CAUTION" if risk_score >= 30
                    else "APPROVED FOR USE"
                ),
            })

        return f"Unknown tool: {tool_name}"
