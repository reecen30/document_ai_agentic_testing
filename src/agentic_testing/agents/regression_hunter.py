"""
agents/regression_hunter.py

RegressionHunter Agent — systematically finds improvements, regressions, and hidden risks
across evidence bundles. Compares baseline vs truth and candidate vs truth. Never invents
metrics — works only with supplied evidence.
"""

import json
import os
from typing import Any, Dict

from crewai import Agent, Crew, LLM, Task
from pydantic import BaseModel, Field

from agentic_testing.llm_factory import get_agent_llm


# ---------------------------------------------------------------------------
# LLM factories
# ---------------------------------------------------------------------------

def get_reasoning_llm() -> LLM:
    return get_agent_llm("reasoning")


def get_structured_llm() -> LLM:
    return get_agent_llm("structured")


# ---------------------------------------------------------------------------
# Output schema
# ---------------------------------------------------------------------------

class Finding(BaseModel):
    transaction_id: int = Field(..., description="Transaction ID where the finding was observed")
    doc_type: str = Field(..., description="Document type involved")
    field: str = Field(default="", description="Specific field involved, if applicable")
    description: str = Field(..., description="Human-readable description of the finding")
    severity: str = Field(..., description="Severity: low, medium, high, critical")
    metric_delta: float = Field(default=0.0, description="Numeric change (positive = improvement)")
    evidence_reference: str = Field(default="", description="Reference to source data supporting this finding")


class SummaryMetrics(BaseModel):
    weighted_f1_baseline: float = Field(default=0.0, description="Weighted F1 for baseline vs truth")
    weighted_f1_candidate: float = Field(default=0.0, description="Weighted F1 for candidate vs truth")
    weighted_f1_delta: float = Field(default=0.0, description="Delta: candidate F1 minus baseline F1")
    exact_match_rate_baseline: float = Field(default=0.0, description="Exact match rate for baseline")
    exact_match_rate_candidate: float = Field(default=0.0, description="Exact match rate for candidate")
    empty_rate_baseline: float = Field(default=0.0, description="Empty/null field rate for baseline")
    empty_rate_candidate: float = Field(default=0.0, description="Empty/null field rate for candidate")
    classification_accuracy_baseline: float = Field(default=0.0)
    classification_accuracy_candidate: float = Field(default=0.0)


class RegressionHunterOutput(BaseModel):
    improvement_findings: list[Finding] = Field(
        default_factory=list,
        description="Findings where the candidate is better than the baseline",
    )
    regression_findings: list[Finding] = Field(
        default_factory=list,
        description="Findings where the candidate is worse than the baseline",
    )
    hidden_risk_findings: list[Finding] = Field(
        default_factory=list,
        description=(
            "Findings that are not regressions but represent hidden risks: "
            "high confidence on wrong answers, field-specific empty spikes, etc."
        ),
    )
    summary_metrics: SummaryMetrics = Field(..., description="Aggregate metrics across all evaluated transactions")
    doc_type_breakdown: Dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Per-document-type metrics dict. Keys are doc type names; "
            "values are dicts with weighted_f1_delta, improvement_count, regression_count."
        ),
    )


# ---------------------------------------------------------------------------
# Agent entry point
# ---------------------------------------------------------------------------

def run_regression_hunter(state_dict: Dict[str, Any]) -> Dict[str, Any]:
    """
    Run the RegressionHunter agent.

    Args:
        state_dict: Relevant subset of FlowState as a dict. Expected keys:
            - case_bundles (list[dict]): Per-transaction evidence bundles from EvidenceCollector.
            - policy (dict): Testing policy with keys:
                - critical_doc_types (list[str]): Doc types that get elevated scrutiny.
                - thresholds (dict): Metric thresholds for regression/improvement detection.
            - run_id (str): Unique run identifier.

    Returns:
        dict conforming to RegressionHunterOutput schema, or error dict on failure.
    """
    from agentic_testing.tools.metrics_tools import (
        compare_baseline_to_truth,
        compare_candidate_to_truth,
        calculate_doc_type_metrics,
        calculate_field_metrics,
        detect_missing_field_spikes,
        detect_confidence_mismatch,
    )

    case_bundles: list = state_dict.get("case_bundles", [])
    policy: Dict[str, Any] = state_dict.get("policy", {})
    run_id: str = state_dict.get("run_id", "unknown_run")

    critical_doc_types: list = policy.get("critical_doc_types", ["IdentityDocument", "Passport", "ApplicationForm"])
    thresholds: Dict[str, Any] = policy.get("thresholds", {})

    llm = get_structured_llm()

    prompt_file = os.path.join(os.path.dirname(__file__), "..", "prompts", "regression_hunter.txt")
    backstory_extra = ""
    if os.path.exists(prompt_file):
        with open(prompt_file, "r", encoding="utf-8") as fh:
            backstory_extra = fh.read()

    agent = Agent(
        role="Regression and Improvement Hunter",
        goal=(
            "Systematically find improvements, regressions, and hidden risks across the evidence "
            "bundles. Compare baseline vs truth (old quality) and candidate vs truth (new quality). "
            "Never invent metrics — work only with the supplied evidence."
        ),
        backstory=(
            "You are a senior quality analyst with expertise in document AI evaluation. You know "
            "that what matters is: did the candidate get closer to the truth than the baseline? "
            "You are alert to hidden risks like high confidence on wrong answers.\n\n"
            + backstory_extra
        ),
        tools=[
            compare_baseline_to_truth,
            compare_candidate_to_truth,
            calculate_doc_type_metrics,
            calculate_field_metrics,
            detect_missing_field_spikes,
            detect_confidence_mismatch,
        ],
        llm=llm,
        verbose=True,
        max_iter=3,
    )

    task_description = f"""
You are performing regression and improvement analysis for run '{run_id}'.

--- POLICY ---
Critical doc types: {critical_doc_types}
Thresholds: {json.dumps(thresholds, indent=2)}

--- CASE BUNDLES ---
Total bundles: {len(case_bundles)}
{json.dumps(case_bundles, indent=2)}

Your tasks:
1. Use `compare_baseline_to_truth` on each bundle to compute baseline quality metrics.
2. Use `compare_candidate_to_truth` on each bundle to compute candidate quality metrics.
3. Use `calculate_doc_type_metrics` to aggregate metrics per document type.
4. Use `calculate_field_metrics` to identify field-level regressions and improvements.
5. Use `detect_missing_field_spikes` to flag doc types or fields with unusually high empty rates.
6. Use `detect_confidence_mismatch` to flag high-confidence wrong answers (hidden risks).
7. Classify each finding as improvement, regression, or hidden_risk based on direction and magnitude.
8. Apply elevated scrutiny to critical doc types: {critical_doc_types}.
9. Return a single valid JSON object matching the required schema.

Three-way comparison framework:
- baseline vs truth → measures OLD quality (pre-change)
- candidate vs truth → measures NEW quality (post-change)
- The DELTA (candidate minus baseline) determines improvement vs regression

A finding is significant if:
- Weighted F1 delta >= 0.05 (improvement) or <= -0.03 (regression)
- Empty rate increases by >= 10% in any field
- Confidence mismatch rate > 15% in any doc type

Return ONLY valid JSON. Do not include markdown fences, explanations, or commentary.
"""

    task = Task(
        description=task_description,
        expected_output=(
            "A single valid JSON object with keys: improvement_findings (list), "
            "regression_findings (list), hidden_risk_findings (list), "
            "summary_metrics (object with weighted_f1 deltas and exact match rates), "
            "doc_type_breakdown (dict)."
        ),
        agent=agent,
        output_pydantic=RegressionHunterOutput,
    )

    crew = Crew(agents=[agent], tasks=[task], verbose=True)
    result = crew.kickoff()

    try:
        if hasattr(result, "pydantic") and result.pydantic is not None:
            return result.pydantic.model_dump()
        raw = result.raw if hasattr(result, "raw") else str(result)
        return json.loads(raw) if isinstance(raw, str) else raw
    except (json.JSONDecodeError, AttributeError) as exc:
        return {
            "error": "Failed to parse agent output",
            "detail": str(exc),
            "raw": str(result),
        }
