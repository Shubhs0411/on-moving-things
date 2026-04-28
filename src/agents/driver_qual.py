from __future__ import annotations

import json
from datetime import date
from typing import Any

from src.knowledge.regulations import RegulationLoader
from src.models.domain import Driver, ComplianceStatus, RiskLevel
from .base import BaseComplianceAgent


class DriverQualificationAgent(BaseComplianceAgent):
    """
    Driver Qualification (DQ) compliance agent.
    Validates 49 CFR Part 391 requirements: CDL, medical cert,
    Clearinghouse status, drug/alcohol testing, and DQ file completeness.
    """

    name = "driver_qualification"

    def __init__(self) -> None:
        super().__init__()
        loader = RegulationLoader()
        raw_drivers = loader.load_drivers()
        self._drivers: dict[str, dict[str, Any]] = {
            d["license_number"]: d for d in raw_drivers
        }

    @property
    def system_prompt(self) -> str:
        return """You are a Driver Qualification (DQ) compliance specialist for HaulCopilot.

Your job: Verify that a commercial driver meets all FMCSA 49 CFR Part 391 requirements.

Process:
1. Call lookup_driver to retrieve driver data
2. Call check_dq_file_completeness to verify required DQ file items
3. Call check_clearinghouse_status for drug/alcohol program compliance
4. Synthesize into a compliance determination

Critical disqualifiers (immediately flag as NON_COMPLIANT):
- Expired CDL
- Expired medical certificate
- Positive drug test with no RTD completion
- PROHIBITED status in FMCSA Clearinghouse
- Refused drug/alcohol test

Output: Status → Disqualifiers (if any) → DQ file gaps → Recommendation"""

    @property
    def tools(self) -> list[dict[str, Any]]:
        return [
            {
                "name": "lookup_driver",
                "description": "Look up driver data by CDL license number. Returns CDL class, endorsements, medical cert status, and violation history.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "license_number": {
                            "type": "string",
                            "description": "CDL license number (e.g. CDL-TX-001234)",
                        }
                    },
                    "required": ["license_number"],
                },
            },
            {
                "name": "check_dq_file_completeness",
                "description": "Check whether all 49 CFR 391.51 required DQ file items are present and current.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "license_number": {"type": "string"},
                    },
                    "required": ["license_number"],
                },
            },
            {
                "name": "check_clearinghouse_status",
                "description": "Check driver's FMCSA Drug & Alcohol Clearinghouse status. Returns CLEAR, PROHIBITED, or PENDING.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "license_number": {"type": "string"},
                    },
                    "required": ["license_number"],
                },
            },
            {
                "name": "check_cdl_validity",
                "description": "Verify CDL class, endorsements, and expiration date against the requirements for a specific load type.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "license_number": {"type": "string"},
                        "load_type": {
                            "type": "string",
                            "description": "e.g. hazmat, tanker, double_triple, passengers, general_freight",
                        },
                    },
                    "required": ["license_number", "load_type"],
                },
            },
        ]

    def _dispatch_tool(self, tool_name: str, tool_input: dict[str, Any]) -> str:
        lic = tool_input.get("license_number", "")

        if tool_name == "lookup_driver":
            d = self._drivers.get(lic)
            if not d:
                return json.dumps({"error": f"Driver {lic} not found"})
            return json.dumps(d, default=str)

        if tool_name == "check_dq_file_completeness":
            d = self._drivers.get(lic)
            if not d:
                return json.dumps({"error": f"Driver {lic} not found"})
            driver = Driver(**d)
            today = date.today()

            checks = {
                "application_for_employment": True,  # assume on file
                "mvr_at_hire": driver.pre_employment_check_done,
                "previous_employer_inquiry": driver.pre_employment_check_done,
                "road_test_certificate": driver.road_test_on_file,
                "medical_certificate_current": (
                    driver.medical_cert_expiration is not None
                    and driver.medical_cert_expiration >= today
                ),
                "medical_examiner_on_registry": driver.medical_examiner_listed,
                "annual_mvr_review": driver.annual_review_current,
                "annual_violations_list": driver.annual_review_current,
                "clearinghouse_pre_employment": driver.pre_employment_check_done,
                "clearinghouse_annual_query": driver.annual_review_current,
            }
            gaps = [k.replace("_", " ").title() for k, v in checks.items() if not v]
            return json.dumps({
                "dq_file_items": checks,
                "gaps": gaps,
                "complete": len(gaps) == 0,
                "citation": "49 CFR 391.51",
            })

        if tool_name == "check_clearinghouse_status":
            d = self._drivers.get(lic)
            if not d:
                return json.dumps({"error": f"Driver {lic} not found"})
            driver = Driver(**d)
            return json.dumps({
                "clearinghouse_status": driver.clearinghouse_status,
                "drug_test_status": driver.drug_test_status,
                "can_perform_safety_sensitive": (
                    driver.clearinghouse_status == "CLEAR"
                    and driver.drug_test_status not in ("POSITIVE", "REFUSED")
                ),
                "citation": "49 CFR 382.701",
                "note": (
                    "PROHIBITED drivers must complete SAP process before returning to safety-sensitive functions. "
                    "49 CFR 382.705"
                ) if driver.clearinghouse_status == "PROHIBITED" else None,
            })

        if tool_name == "check_cdl_validity":
            d = self._drivers.get(lic)
            if not d:
                return json.dumps({"error": f"Driver {lic} not found"})
            driver = Driver(**d)
            load_type = tool_input.get("load_type", "general_freight")
            today = date.today()

            issues = []
            required_endorsements = {
                "hazmat": "H",
                "tanker": "N",
                "double_triple": "T",
                "passengers": "P",
                "school_bus": "S",
                "hazmat_tanker": "X",
            }

            if driver.cdl_expiration and driver.cdl_expiration < today:
                issues.append(f"CDL expired on {driver.cdl_expiration}")

            required_end = required_endorsements.get(load_type)
            if required_end and required_end not in driver.cdl_endorsements:
                issues.append(
                    f"Load type '{load_type}' requires endorsement '{required_end}', "
                    f"driver has: {driver.cdl_endorsements or 'none'}"
                )

            return json.dumps({
                "cdl_class": driver.cdl_class,
                "endorsements": driver.cdl_endorsements,
                "restrictions": driver.cdl_restrictions,
                "expiration": str(driver.cdl_expiration),
                "valid_for_load_type": len(issues) == 0,
                "issues": issues,
            })

        return f"Unknown tool: {tool_name}"
