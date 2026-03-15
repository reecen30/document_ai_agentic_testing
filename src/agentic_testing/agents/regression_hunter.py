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

from agentic_testing.agent_mode import use_deterministic_mode
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


def _avg(values: list[float]) -> float:
    clean = [float(v) for v in values if isinstance(v, (int, float))]
    return round(sum(clean) / len(clean), 4) if clean else 0.0


def _deterministic_regression_hunter(case_bundles: list, critical_doc_types: list[str]) -> Dict[str, Any]:
    from agentic_testing.tools.metrics_tools import (
        compare_baseline_to_truth,
        compare_candidate_to_truth,
        calculate_doc_type_metrics,
        detect_confidence_mismatch,
    )

    baseline_rows = []
    candidate_rows = []
    improvements = []
    regressions = []
    hidden_risks = []

    for bundle in case_bundles:
        b = json.loads(compare_baseline_to_truth._run(case_bundle=bundle))
        c = json.loads(compare_candidate_to_truth._run(case_bundle=bundle))
        if isinstance(b, dict) and "error" not in b:
            baseline_rows.append(b)
        if isinstance(c, dict) and "error" not in c:
            candidate_rows.append(c)

        if not isinstance(b, dict) or not isinstance(c, dict):
            continue
        tid = int(bundle.get("transaction_id", 0) or 0)
        doc_type = str(bundle.get("doc_type_truth") or bundle.get("doc_type_baseline") or "Unknown")
        b_ok = b.get("classification_correct")
        c_ok = c.get("classification_correct")

        if b_ok is False and c_ok is True:
            improvements.append(
                {
                    "transaction_id": tid,
                    "doc_type": doc_type,
                    "field": "DocumentType",
                    "description": "Candidate classification corrected a baseline mismatch.",
                    "severity": "high" if doc_type in set(critical_doc_types) else "medium",
                    "metric_delta": 1.0,
                    "evidence_reference": "classification_correct baseline->candidate",
                }
            )
        if b_ok is True and c_ok is False:
            regressions.append(
                {
                    "transaction_id": tid,
                    "doc_type": doc_type,
                    "field": "DocumentType",
                    "description": "Candidate introduced a classification regression.",
                    "severity": "critical" if doc_type in set(critical_doc_types) else "high",
                    "metric_delta": -1.0,
                    "evidence_reference": "classification_correct baseline->candidate",
                }
            )

    baseline_cls = [1.0 if r.get("classification_correct") is True else 0.0 for r in baseline_rows if r.get("classification_correct") is not None]
    candidate_cls = [1.0 if r.get("classification_correct") is True else 0.0 for r in candidate_rows if r.get("classification_correct") is not None]
    baseline_exact = [r.get("exact_match_rate") for r in baseline_rows if r.get("exact_match_rate") is not None]
    candidate_exact = [r.get("exact_match_rate") for r in candidate_rows if r.get("exact_match_rate") is not None]
    baseline_empty = [r.get("missing_field_rate") for r in baseline_rows if r.get("missing_field_rate") is not None]
    candidate_empty = [r.get("missing_field_rate") for r in candidate_rows if r.get("missing_field_rate") is not None]

    classification_accuracy_baseline = _avg(baseline_cls)
    classification_accuracy_candidate = _avg(candidate_cls)
    weighted_f1_baseline = classification_accuracy_baseline
    weighted_f1_candidate = classification_accuracy_candidate
    weighted_f1_delta = round(weighted_f1_candidate - weighted_f1_baseline, 4)

    exact_match_rate_baseline = _avg(baseline_exact)
    exact_match_rate_candidate = _avg(candidate_exact)
    empty_rate_baseline = _avg(baseline_empty)
    empty_rate_candidate = _avg(candidate_empty)

    conf_mismatch = json.loads(
        detect_confidence_mismatch._run(
            case_bundles=case_bundles,
            confidence_threshold=0.85,
            mode="candidate",
        )
    )
    for item in conf_mismatch.get("confidence_mismatch_transactions", []):
        hidden_risks.append(
            {
                "transaction_id": int(item.get("transaction_id", 0) or 0),
                "doc_type": str(item.get("truth_doc_type", "Unknown")),
                "field": "DocumentType",
                "description": "High-confidence wrong candidate prediction detected.",
                "severity": "high",
                "metric_delta": 0.0,
                "evidence_reference": "detect_confidence_mismatch",
            }
        )

    doc_metrics_raw = json.loads(calculate_doc_type_metrics._run(case_bundles=case_bundles))
    doc_type_breakdown = {}
    for row in doc_metrics_raw.get("doc_type_metrics", []):
        doc_type_breakdown[str(row.get("doc_type", "Unknown"))] = {
            "weighted_f1_delta": row.get("delta_f1", 0.0),
            "improvement_count": len([x for x in improvements if str(x.get("doc_type")) == str(row.get("doc_type"))]),
            "regression_count": len([x for x in regressions if str(x.get("doc_type")) == str(row.get("doc_type"))]),
        }

    return {
        "improvement_findings": improvements,
        "regression_findings": regressions,
        "hidden_risk_findings": hidden_risks,
        "summary_metrics": {
            "weighted_f1_baseline": weighted_f1_baseline,
            "weighted_f1_candidate": weighted_f1_candidate,
            "weighted_f1_delta": weighted_f1_delta,
            "exact_match_rate_baseline": exact_match_rate_baseline,
            "exact_match_rate_candidate": exact_match_rate_candidate,
            "empty_rate_baseline": empty_rate_baseline,
            "empty_rate_candidate": empty_rate_candidate,
            "classification_accuracy_baseline": classification_accuracy_baseline,
            "classification_accuracy_candidate": classification_accuracy_candidate,
        },
        "doc_type_breakdown": doc_type_breakdown,
    }


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

    if use_deterministic_mode():
        return _deterministic_regression_hunter(case_bundles=case_bundles, critical_doc_types=critical_doc_types)

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
        # Keep provider-compatible response mode (no forced json_schema).
    )

    try:
        crew = Crew(agents=[agent], tasks=[task], verbose=True)
        result = crew.kickoff()
    except Exception:
        return _deterministic_regression_hunter(case_bundles=case_bundles, critical_doc_types=critical_doc_types)

    try:
        raw = result.raw if hasattr(result, "raw") else str(result)
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        if not isinstance(parsed, dict):
            raise ValueError("Regression hunter returned non-dict payload")
        return parsed
    except Exception:
        return _deterministic_regression_hunter(case_bundles=case_bundles, critical_doc_types=critical_doc_types)
