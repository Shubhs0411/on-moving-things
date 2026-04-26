from __future__ import annotations

import os

import pytest
from dotenv import load_dotenv

from src.eval.harness import EvalHarness
from src.eval.test_cases import EVAL_SUITE
from src.graph.orchestrator import FreightMindOrchestrator
from src.models.domain import QueryIntent


load_dotenv()


def _selected_cases():
    cases = EVAL_SUITE

    category = os.getenv("EVAL_CATEGORY")
    if category:
        try:
            cat_filter = QueryIntent(category)
        except ValueError as exc:
            raise AssertionError(
                f"Invalid EVAL_CATEGORY={category}. Expected one of: "
                f"{', '.join(i.value for i in QueryIntent)}"
            ) from exc
        cases = [c for c in cases if c.category == cat_filter]

    n_cases = os.getenv("EVAL_N_CASES")
    if n_cases:
        cases = cases[: int(n_cases)]

    return cases


@pytest.mark.integration
def test_live_eval_harness_meets_threshold():
    """
    Runs the live eval harness through pytest.

    Environment knobs:
    - EVAL_MIN_PASS_RATE: float in [0,1], default 0.60
    - EVAL_CATEGORY: optional QueryIntent value to filter suite
    - EVAL_N_CASES: optional int to limit cases
    """
    if not os.getenv("ANTHROPIC_API_KEY"):
        pytest.skip("ANTHROPIC_API_KEY is not set; skipping live eval integration test")

    threshold = float(os.getenv("EVAL_MIN_PASS_RATE", "0.60"))
    cases = _selected_cases()
    assert cases, "No eval cases selected; adjust EVAL_CATEGORY or EVAL_N_CASES"

    orchestrator = FreightMindOrchestrator()
    harness = EvalHarness(invoke_fn=orchestrator.invoke)
    summary = harness.run(suite=cases)

    passed = summary["passed"]
    total = summary["total_cases"]
    pass_rate = (passed / total) if total else 0.0

    assert pass_rate >= threshold, (
        f"Live eval threshold failed: pass_rate={pass_rate:.3f}, "
        f"threshold={threshold:.3f}, passed={passed}, total={total}, "
        f"avg_score={summary['avg_score']}, failed_cases={summary['failed_cases']}"
    )
