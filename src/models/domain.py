from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ComplianceStatus(str, Enum):
    COMPLIANT = "compliant"
    NON_COMPLIANT = "non_compliant"
    CONDITIONAL = "conditional"
    UNKNOWN = "unknown"


class QueryIntent(str, Enum):
    CARRIER_VETTING = "carrier_vetting"
    DRIVER_QUALIFICATION = "driver_qualification"
    CSA_SCORING = "csa_scoring"
    REGULATION_LOOKUP = "regulation_lookup"
    RISK_ASSESSMENT = "risk_assessment"
    MULTI_DOMAIN = "multi_domain"


# ── Domain Entities ───────────────────────────────────────────────────────────

class CSAScore(BaseModel):
    """CSA BASIC (Behavior Analysis and Safety Improvement Categories) scores."""
    unsafe_driving: float | None = Field(None, ge=0, le=100)
    hours_of_service: float | None = Field(None, ge=0, le=100)
    driver_fitness: float | None = Field(None, ge=0, le=100)
    controlled_substances: float | None = Field(None, ge=0, le=100)
    vehicle_maintenance: float | None = Field(None, ge=0, le=100)
    hazmat_compliance: float | None = Field(None, ge=0, le=100)
    crash_indicator: float | None = Field(None, ge=0, le=100)

    def intervention_thresholds(self) -> dict[str, float]:
        return {
            "unsafe_driving": 65.0,
            "hours_of_service": 65.0,
            "driver_fitness": 80.0,
            "controlled_substances": 80.0,
            "vehicle_maintenance": 80.0,
            "hazmat_compliance": 80.0,
            "crash_indicator": 65.0,
        }

    def violations(self) -> list[str]:
        thresholds = self.intervention_thresholds()
        violations = []
        for basic, threshold in thresholds.items():
            score = getattr(self, basic)
            if score is not None and score >= threshold:
                violations.append(f"{basic.replace('_', ' ').title()}: {score:.1f} (threshold: {threshold})")
        return violations

    def highest_risk_basic(self) -> tuple[str, float] | None:
        scores = {k: getattr(self, k) for k in CSAScore.model_fields if getattr(self, k) is not None}
        if not scores:
            return None
        worst = max(scores, key=lambda k: scores[k])
        return worst, scores[worst]


class Carrier(BaseModel):
    """Motor carrier entity with FMCSA compliance data."""
    dot_number: str
    mc_number: str | None = None
    legal_name: str
    dba_name: str | None = None
    operating_status: str = "AUTHORIZED"
    carrier_operation: str = "CARRIER"
    hm_flag: bool = False
    pc_flag: bool = False
    state: str | None = None
    country: str = "US"
    safety_rating: str | None = None  # SATISFACTORY, CONDITIONAL, UNSATISFACTORY
    safety_rating_date: date | None = None
    insurance_on_file: bool = True
    insurance_required: float = 750_000.0  # minimum required
    insurance_amount: float = 1_000_000.0
    out_of_service: bool = False
    out_of_service_date: date | None = None
    csa_scores: CSAScore | None = None
    total_drivers: int | None = None
    total_power_units: int | None = None
    crashes_total: int = 0
    crashes_fatal: int = 0
    crashes_injury: int = 0
    inspections_total: int = 0
    driver_oos_inspections: int = 0
    vehicle_oos_inspections: int = 0

    @property
    def driver_oos_rate(self) -> float | None:
        if self.inspections_total == 0:
            return None
        return self.driver_oos_inspections / self.inspections_total * 100

    @property
    def vehicle_oos_rate(self) -> float | None:
        if self.inspections_total == 0:
            return None
        return self.vehicle_oos_inspections / self.inspections_total * 100

    def is_authorized(self) -> bool:
        return (
            self.operating_status == "AUTHORIZED"
            and not self.out_of_service
            and self.insurance_on_file
        )


class Driver(BaseModel):
    """Commercial motor vehicle driver with FMCSA qualification data."""
    license_number: str
    license_state: str
    cdl_class: str  # A, B, C
    cdl_endorsements: list[str] = Field(default_factory=list)  # H, N, P, S, T, X
    cdl_restrictions: list[str] = Field(default_factory=list)
    cdl_expiration: date | None = None
    medical_cert_expiration: date | None = None
    medical_examiner_listed: bool = True
    drug_test_status: str = "NEGATIVE"  # NEGATIVE, POSITIVE, REFUSED, NOT_TESTED
    clearinghouse_status: str = "CLEAR"  # CLEAR, PROHIBITED, PENDING
    violations_3yr: int = 0
    accidents_3yr: int = 0
    out_of_service_orders: int = 0
    traffic_convictions_3yr: int = 0
    date_of_hire: date | None = None
    pre_employment_check_done: bool = False
    annual_review_current: bool = True
    road_test_on_file: bool = True

    def is_qualified(self, today: date | None = None) -> bool:
        today = today or date.today()
        if self.cdl_expiration and self.cdl_expiration < today:
            return False
        if self.medical_cert_expiration and self.medical_cert_expiration < today:
            return False
        if self.drug_test_status in ("POSITIVE", "REFUSED"):
            return False
        if self.clearinghouse_status == "PROHIBITED":
            return False
        return True

    def disqualifying_offenses(self) -> list[str]:
        issues = []
        today = date.today()
        if self.cdl_expiration and self.cdl_expiration < today:
            issues.append("CDL expired")
        if self.medical_cert_expiration and self.medical_cert_expiration < today:
            issues.append("Medical certificate expired")
        if self.drug_test_status == "POSITIVE":
            issues.append("Positive drug test — Return-to-Duty required")
        if self.drug_test_status == "REFUSED":
            issues.append("Refused drug/alcohol test — treated as positive")
        if self.clearinghouse_status == "PROHIBITED":
            issues.append("FMCSA Drug & Alcohol Clearinghouse: prohibited status")
        return issues


class Vehicle(BaseModel):
    """Commercial motor vehicle inspection and safety data."""
    vin: str
    year: int | None = None
    make: str | None = None
    unit_type: str = "TRUCK"  # TRUCK, TRAILER, BUS
    license_plate: str | None = None
    license_state: str | None = None
    gvwr: float | None = None  # gross vehicle weight rating
    out_of_service: bool = False
    annual_inspection_date: date | None = None
    inspections_total: int = 0
    oos_inspections: int = 0
    violations_total: int = 0

    @property
    def oos_rate(self) -> float | None:
        if self.inspections_total == 0:
            return None
        return self.oos_inspections / self.inspections_total * 100

    def annual_inspection_current(self, today: date | None = None) -> bool:
        today = today or date.today()
        if not self.annual_inspection_date:
            return False
        return (today - self.annual_inspection_date).days <= 365


# ── Compliance Output Models ──────────────────────────────────────────────────

class Finding(BaseModel):
    category: str
    severity: RiskLevel
    description: str
    regulation_ref: str | None = None
    recommendation: str | None = None


class ComplianceReport(BaseModel):
    subject_type: str  # carrier, driver, vehicle
    subject_id: str
    subject_name: str | None = None
    status: ComplianceStatus
    risk_level: RiskLevel
    findings: list[Finding] = Field(default_factory=list)
    summary: str
    regulation_citations: list[str] = Field(default_factory=list)
    checked_at: datetime = Field(default_factory=datetime.utcnow)
    agent_reasoning: str | None = None
    confidence: float = Field(1.0, ge=0, le=1)


# ── Observability ─────────────────────────────────────────────────────────────

class AgentTrace(BaseModel):
    trace_id: str
    agent_name: str
    query: str
    intent: QueryIntent | None = None
    tools_called: list[str] = Field(default_factory=list)
    tool_results: list[dict[str, Any]] = Field(default_factory=list)
    model_used: str
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: float = 0.0
    started_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: datetime | None = None
    error: str | None = None


# ── Eval Framework ────────────────────────────────────────────────────────────

class EvalCase(BaseModel):
    id: str
    category: QueryIntent
    query: str
    context: dict[str, Any] = Field(default_factory=dict)
    expected_status: ComplianceStatus | None = None
    expected_risk: RiskLevel | None = None
    expected_keywords: list[str] = Field(default_factory=list)
    expected_regulation_refs: list[str] = Field(default_factory=list)
    description: str = ""


class EvalResult(BaseModel):
    case_id: str
    passed: bool
    score: float = Field(ge=0, le=1)
    actual_status: ComplianceStatus | None = None
    actual_risk: RiskLevel | None = None
    keyword_hits: list[str] = Field(default_factory=list)
    keyword_misses: list[str] = Field(default_factory=list)
    regulation_hits: list[str] = Field(default_factory=list)
    regulation_misses: list[str] = Field(default_factory=list)
    latency_ms: float = 0.0
    notes: str = ""
