from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from src.models.domain import (
    EvalCase, EvalResult, ComplianceStatus, RiskLevel, QueryIntent
)
from .test_cases import EVAL_SUITE


class EvalHarness:
    """
    Evaluation harness for FreightMind agents.

    Runs a suite of compliance test cases against the system and measures:
    - Status accuracy (when expected_status is defined)
    - Risk level accuracy (when expected_risk is defined)
    - Keyword recall (how many expected terms appear in response)
    - Regulation citation recall
    - Latency per call

    Embodies the 'nervous system' — continuous feedback on whether agents
    are producing correct, grounded, actionable responses.
    """

    def __init__(
        self,
        invoke_fn: Callable[[str], dict[str, Any]],
        output_dir: str = "./evals/results",
    ) -> None:
        self._invoke = invoke_fn
        self._output_dir = Path(output_dir)
        self._output_dir.mkdir(parents=True, exist_ok=True)

    def run(
        self,
        suite: list[EvalCase] | None = None,
        category_filter: QueryIntent | None = None,
        n_cases: int | None = None,
    ) -> dict[str, Any]:
        cases = suite or EVAL_SUITE
        if category_filter:
            cases = [c for c in cases if c.category == category_filter]
        if n_cases:
            cases = cases[:n_cases]

        results: list[EvalResult] = []
        for case in cases:
            result = self._run_single(case)
            results.append(result)

        summary = self._compute_summary(results, cases)
        self._persist(results, summary)
        return summary

    def _run_single(self, case: EvalCase) -> EvalResult:
        t0 = time.perf_counter()
        try:
            output = self._invoke(case.query)
            latency_ms = (time.perf_counter() - t0) * 1000
            response_text = output.get("response", "").lower()

            # Keyword recall
            keyword_hits = [kw for kw in case.expected_keywords if kw.lower() in response_text]
            keyword_misses = [kw for kw in case.expected_keywords if kw.lower() not in response_text]

            # Regulation citation recall
            reg_hits = [r for r in case.expected_regulation_refs if r.lower() in response_text]
            reg_misses = [r for r in case.expected_regulation_refs if r.lower() not in response_text]

            # Score components
            kw_score = len(keyword_hits) / max(len(case.expected_keywords), 1)
            reg_score = len(reg_hits) / max(len(case.expected_regulation_refs), 1)

            # Status/risk detection (heuristic from response text)
            actual_status = self._detect_status(response_text, output)
            actual_risk = self._detect_risk(response_text)

            status_correct = (
                case.expected_status is None
                or actual_status == case.expected_status
                or self._status_in_response(case.expected_status, response_text)
            )
            risk_correct = (
                case.expected_risk is None
                or actual_risk == case.expected_risk
                or self._risk_in_response(case.expected_risk, response_text)
            )

            score = (
                kw_score * 0.5
                + reg_score * 0.2
                + (0.15 if status_correct else 0.0)
                + (0.15 if risk_correct else 0.0)
            )
            passed = score >= 0.6

            return EvalResult(
                case_id=case.id,
                passed=passed,
                score=round(score, 3),
                actual_status=actual_status,
                actual_risk=actual_risk,
                keyword_hits=keyword_hits,
                keyword_misses=keyword_misses,
                regulation_hits=reg_hits,
                regulation_misses=reg_misses,
                latency_ms=round(latency_ms, 1),
                notes=f"kw={kw_score:.2f} reg={reg_score:.2f} status={'✓' if status_correct else '✗'} risk={'✓' if risk_correct else '✗'}",
            )
        except Exception as e:
            latency_ms = (time.perf_counter() - t0) * 1000
            return EvalResult(
                case_id=case.id,
                passed=False,
                score=0.0,
                latency_ms=round(latency_ms, 1),
                notes=f"ERROR: {e}",
            )

    def _detect_status(
        self, text: str, output: dict[str, Any]
    ) -> ComplianceStatus | None:
        if any(w in text for w in ["non-compliant", "non_compliant", "not compliant", "do not use", "cannot"]):
            return ComplianceStatus.NON_COMPLIANT
        if any(w in text for w in ["conditional", "use with caution", "conditions"]):
            return ComplianceStatus.CONDITIONAL
        if any(w in text for w in ["compliant", "approved", "qualified", "satisfactory"]):
            return ComplianceStatus.COMPLIANT
        return None

    def _detect_risk(self, text: str) -> RiskLevel | None:
        if "critical" in text:
            return RiskLevel.CRITICAL
        if "high risk" in text or "high" in text:
            return RiskLevel.HIGH
        if "medium" in text or "moderate" in text:
            return RiskLevel.MEDIUM
        if "low risk" in text or "low" in text:
            return RiskLevel.LOW
        return None

    def _status_in_response(self, expected: ComplianceStatus, text: str) -> bool:
        mapping = {
            ComplianceStatus.COMPLIANT: ["compliant", "approved", "satisfactory", "qualified"],
            ComplianceStatus.NON_COMPLIANT: ["non-compliant", "not compliant", "do not use", "prohibited", "disqualif"],
            ComplianceStatus.CONDITIONAL: ["conditional", "caution", "conditions apply"],
            ComplianceStatus.UNKNOWN: ["unknown", "insufficient data"],
        }
        return any(kw in text for kw in mapping.get(expected, []))

    def _risk_in_response(self, expected: RiskLevel, text: str) -> bool:
        mapping = {
            RiskLevel.LOW: ["low risk", "low"],
            RiskLevel.MEDIUM: ["medium", "moderate"],
            RiskLevel.HIGH: ["high risk", "high"],
            RiskLevel.CRITICAL: ["critical"],
        }
        return any(kw in text for kw in mapping.get(expected, []))

    def _compute_summary(
        self, results: list[EvalResult], cases: list[EvalCase]
    ) -> dict[str, Any]:
        total = len(results)
        passed = sum(1 for r in results if r.passed)
        avg_score = sum(r.score for r in results) / total if total else 0
        avg_latency = sum(r.latency_ms for r in results) / total if total else 0
        errors = [r for r in results if r.notes.startswith("ERROR")]

        by_category: dict[str, dict[str, Any]] = {}
        for case, result in zip(cases, results):
            cat = case.category.value
            if cat not in by_category:
                by_category[cat] = {"passed": 0, "total": 0, "scores": []}
            by_category[cat]["total"] += 1
            by_category[cat]["scores"].append(result.score)
            if result.passed:
                by_category[cat]["passed"] += 1

        category_stats = {
            cat: {
                "pass_rate": f"{v['passed']}/{v['total']}",
                "avg_score": round(sum(v["scores"]) / len(v["scores"]), 3),
            }
            for cat, v in by_category.items()
        }

        failed_cases = [
            {"id": r.case_id, "score": r.score, "notes": r.notes, "keyword_misses": r.keyword_misses}
            for r in results if not r.passed
        ]

        return {
            "run_at": datetime.utcnow().isoformat(),
            "total_cases": total,
            "passed": passed,
            "failed": total - passed,
            "pass_rate": f"{passed}/{total} ({passed/total*100:.1f}%)" if total else "0/0",
            "avg_score": round(avg_score, 3),
            "avg_latency_ms": round(avg_latency, 1),
            "error_count": len(errors),
            "by_category": category_stats,
            "failed_cases": failed_cases,
        }

    def _persist(self, results: list[EvalResult], summary: dict[str, Any]) -> None:
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        results_path = self._output_dir / f"eval_{ts}.json"
        results_path.write_text(
            json.dumps(
                {
                    "summary": summary,
                    "results": [r.model_dump() for r in results],
                },
                indent=2,
                default=str,
            )
        )
