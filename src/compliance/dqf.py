from __future__ import annotations

from datetime import date, datetime
from typing import Any


def _parse_date(value: Any) -> date | None:
    if not value:
        return None
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value).date()
        except ValueError:
            return None
    return None


def audit_dqf_packet(packet: dict[str, Any], today: date | None = None) -> dict[str, Any]:
    """Minimal DQF audit MVP with rule-linked findings and operational next steps."""
    today = today or date.today()

    findings: list[dict[str, str]] = []
    missing_items: list[str] = []
    stale_items: list[str] = []

    def add_missing(item: str, rule: str, action: str) -> None:
        missing_items.append(item)
        findings.append({
            "item": item,
            "status": "missing",
            "rule": rule,
            "next_step": action,
        })

    def add_stale(item: str, rule: str, action: str) -> None:
        stale_items.append(item)
        findings.append({
            "item": item,
            "status": "stale",
            "rule": rule,
            "next_step": action,
        })

    if not packet.get("employment_application"):
        add_missing(
            "employment_application",
            "49 CFR 391.21",
            "Collect signed and complete driver application before onboarding.",
        )

    if not packet.get("mvr_initial"):
        add_missing(
            "mvr_initial",
            "49 CFR 391.23(a)(1)",
            "Request and review state MVR before safety-sensitive assignment.",
        )

    annual_mvr_review = _parse_date(packet.get("mvr_annual_review_date"))
    if not annual_mvr_review:
        add_missing(
            "mvr_annual_review_date",
            "49 CFR 391.25",
            "Document annual MVR review and retention in DQF.",
        )
    elif (today - annual_mvr_review).days > 365:
        add_stale(
            "mvr_annual_review_date",
            "49 CFR 391.25",
            "Run annual MVR review immediately and update review record.",
        )

    medical_exp = _parse_date(packet.get("medical_certificate_expiration"))
    if not medical_exp:
        add_missing(
            "medical_certificate_expiration",
            "49 CFR 391.41 and 49 CFR 391.45",
            "Upload valid medical examiner certificate and verify examiner listing.",
        )
    elif medical_exp < today:
        add_stale(
            "medical_certificate_expiration",
            "49 CFR 391.41 and 49 CFR 391.45",
            "Driver cannot operate until medical certification is renewed.",
        )

    if not packet.get("road_test_or_cdl_copy"):
        add_missing(
            "road_test_or_cdl_copy",
            "49 CFR 391.31 and 49 CFR 391.33",
            "Store CDL equivalent evidence or completed road test certificate.",
        )

    if not packet.get("clearinghouse_preemployment_query"):
        add_missing(
            "clearinghouse_preemployment_query",
            "49 CFR 382.701(a)",
            "Run and retain pre-employment Clearinghouse query result.",
        )

    annual_clearinghouse = _parse_date(packet.get("clearinghouse_annual_query_date"))
    if not annual_clearinghouse:
        add_missing(
            "clearinghouse_annual_query_date",
            "49 CFR 382.701(b)",
            "Run annual Clearinghouse query and log completion date.",
        )
    elif (today - annual_clearinghouse).days > 365:
        add_stale(
            "clearinghouse_annual_query_date",
            "49 CFR 382.701(b)",
            "Run annual Clearinghouse query immediately and record evidence.",
        )

    if missing_items or stale_items:
        risk = "high" if stale_items else "medium"
        status = "non_compliant"
    else:
        risk = "low"
        status = "compliant"

    next_steps = [f["next_step"] for f in findings]
    return {
        "status": status,
        "risk_level": risk,
        "missing_items": missing_items,
        "stale_items": stale_items,
        "findings": findings,
        "next_steps": next_steps,
        "summary": (
            "DQF packet complete and current." if status == "compliant"
            else f"DQF packet requires remediation: {len(missing_items)} missing, {len(stale_items)} stale items."
        ),
    }
