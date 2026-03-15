"""
agents/challenger.py

Challenger Agent — challenges weak evidence, prevents bad diagnoses based on small samples,
label noise, or unstable patterns. Decides whether current findings are strong enough to trust.
"""

import json
import os
from typing import Any, Dict, Optional

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

class ConfidenceAssessment(BaseModel):
    overall_confidence: float = Field(
        ..., ge=0.0, le=1.0, description="Challenger's overall confidence in the findings (0.0–1.0)"
    )
    sample_size_verdict: str = Field(
        ...,
        description=(
            "Verdict on whether the sample size is adequate: "
            "'adequate', 'marginal', or 'insufficient'"
        ),
    )
    pattern_stability_verdict: str = Field(
        ...,
        description=(
            "Verdict on pattern stability: "
            "'stable', 'isolated', 'unstable', or 'inconclusive'"
        ),
    )
    label_quality_concern: str = Field(
        ...,
        description=(
            "Concern level about label (ground truth) quality: "
            "'none', 'minor', 'moderate', 'severe'"
        ),
    )


class ChallengerOutput(BaseModel):
    confidence_assessment: ConfidenceAssessment = Field(
        ..., description="Structured assessment of evidence confidence"
    )
    needs_more_evidence: bool = Field(
        ...,
        description=(
            "True if the challenger believes more evidence is needed before "
            "findings can be trusted for a release decision"
        ),
    )
    challenge_notes: list[str] = Field(
        default_factory=list,
        description="Specific challenges raised against the current findings",
    )
    sample_size_adequate: bool = Field(
        ...,
        description="True if each represented doc type has >= 10 transactions",
    )
    label_noise_concern: bool = Field(
        ...,
        description="True if there are indicators of noisy or inconsistent ground-truth labels",
    )
    recommended_expansion: Optional[str] = Field(
        default=None,
        description=(
            "If needs_more_evidence is True, a plain-English description of what additional "
            "evidence is needed. Null if evidence is sufficient."
        ),
    )


def _deterministic_challenger(
    total_transactions: int,
    doc_type_distribution: Dict[str, int],
    improvement_findings: list,
    regression_findings: list,
    hidden_risk_findings: list,
    evidence_summary: Dict[str, Any],
) -> Dict[str, Any]:
    counts = [int(v) for v in doc_type_distribution.values()] if isinstance(doc_type_distribution, dict) else []
    min_count = min(counts) if counts else 0
    if counts and min_count >= 10:
        sample_size_verdict = "adequate"
    elif counts and min_count >= 5:
        sample_size_verdict = "marginal"
    else:
        sample_size_verdict = "insufficient"

    finding_count = len(improvement_findings) + len(regression_findings) + len(hidden_risk_findings)
    pattern_stability_verdict = "stable" if finding_count >= 3 else "isolated" if finding_count > 0 else "inconclusive"

    missing_truth = int((evidence_summary or {}).get("missing_truth_count", 0) or 0)
    label_ratio = (missing_truth / total_transactions) if total_transactions else 0.0
    if label_ratio > 0.4:
        label_quality_concern = "severe"
    elif label_ratio > 0.2:
        label_quality_concern = "moderate"
    elif label_ratio > 0.0:
        label_quality_concern = "minor"
    else:
        label_quality_concern = "none"

    needs_more_evidence = sample_size_verdict == "insufficient" or pattern_stability_verdict == "isolated"
    challenge_notes = []
    if sample_size_verdict != "adequate":
        challenge_notes.append(f"Sample size is {sample_size_verdict}; add more transactions per represented doc type.")
    if pattern_stability_verdict in {"isolated", "inconclusive"}:
        challenge_notes.append("Observed patterns are not yet stable across enough transactions.")
    if label_quality_concern in {"moderate", "severe"}:
        challenge_notes.append("Ground-truth label quality may be affecting confidence in conclusions.")

    recommended_expansion = None
    if needs_more_evidence:
        recommended_expansion = "Expand targeted scope by 10-20 transactions in affected document types."

    overall_confidence = 0.8
    if sample_size_verdict == "marginal":
        overall_confidence = 0.6
    if sample_size_verdict == "insufficient":
        overall_confidence = 0.4
    if label_quality_concern in {"moderate", "severe"}:
        overall_confidence = min(overall_confidence, 0.5)

    return {
        "confidence_assessment": {
            "overall_confidence": overall_confidence,
            "sample_size_verdict": sample_size_verdict,
            "pattern_stability_verdict": pattern_stability_verdict,
            "label_quality_concern": label_quality_concern,
        },
        "needs_more_evidence": needs_more_evidence,
        "challenge_notes": challenge_notes,
        "sample_size_adequate": sample_size_verdict == "adequate",
        "label_noise_concern": label_quality_concern in {"moderate", "severe"},
        "recommended_expansion": recommended_expansion,
    }


# ---------------------------------------------------------------------------
# Agent entry point
# ---------------------------------------------------------------------------

def run_challenger(state_dict: Dict[str, Any]) -> Dict[str, Any]:
    """
    Run the Challenger agent.

    Args:
        state_dict: Relevant subset of FlowState as a dict. Expected keys:
            - evidence_summary (dict): Summary of evidence collected (from EvidenceCollector).
            - improvement_findings (list[dict]): From RegressionHunter.
            - regression_findings (list[dict]): From RegressionHunter.
            - hidden_risk_findings (list[dict]): From RegressionHunter.
            - total_transactions (int): Total transactions in the evidence set.
            - doc_type_distribution (dict): Per-doctype transaction counts.
            - run_id (str): Unique run identifier.

    Returns:
        dict conforming to ChallengerOutput schema, or error dict on failure.
    """
    evidence_summary: Dict[str, Any] = state_dict.get("evidence_summary", {})
    improvement_findings: list = state_dict.get("improvement_findings", [])
    regression_findings: list = state_dict.get("regression_findings", [])
    hidden_risk_findings: list = state_dict.get("hidden_risk_findings", [])
    total_transactions: int = state_dict.get("total_transactions", 0)
    doc_type_distribution: Dict[str, int] = state_dict.get("doc_type_distribution", {})
    run_id: str = state_dict.get("run_id", "unknown_run")

    if use_deterministic_mode():
        return _deterministic_challenger(
            total_transactions=total_transactions,
            doc_type_distribution=doc_type_distribution,
            improvement_findings=improvement_findings,
            regression_findings=regression_findings,
            hidden_risk_findings=hidden_risk_findings,
            evidence_summary=evidence_summary,
        )

    llm = get_reasoning_llm()

    prompt_file = os.path.join(os.path.dirname(__file__), "..", "prompts", "challenger.txt")
    backstory_extra = ""
    if os.path.exists(prompt_file):
        with open(prompt_file, "r", encoding="utf-8") as fh:
            backstory_extra = fh.read()

    agent = Agent(
        role="Evidence Quality Challenger",
        goal=(
            "Challenge weak evidence. Prevent bad diagnoses based on small samples, label noise, "
            "or unstable patterns. Decide whether the current findings are strong enough to trust."
        ),
        backstory=(
            "You are the adversarial voice in the testing process. You have seen too many "
            "premature release decisions based on thin evidence. Your job is to push back when "
            "the sample is too small, the patterns are isolated, or the labels look noisy.\n\n"
            + backstory_extra
        ),
        tools=[],
        llm=llm,
        verbose=True,
        max_iter=3,
    )

    task_description = f"""
You are challenging the quality of evidence for run '{run_id}'.

--- EVIDENCE SUMMARY ---
{json.dumps(evidence_summary, indent=2)}

--- TOTAL TRANSACTIONS ---
{total_transactions}

--- DOC TYPE DISTRIBUTION ---
{json.dumps(doc_type_distribution, indent=2)}

--- IMPROVEMENT FINDINGS ({len(improvement_findings)} total) ---
{json.dumps(improvement_findings, indent=2)}

--- REGRESSION FINDINGS ({len(regression_findings)} total) ---
{json.dumps(regression_findings, indent=2)}

--- HIDDEN RISK FINDINGS ({len(hidden_risk_findings)} total) ---
{json.dumps(hidden_risk_findings, indent=2)}

Your tasks:
1. Assess whether the sample size is adequate:
   - Minimum 10 transactions per represented doc type is required for statistical credibility.
   - Minimum 5 transactions per represented doc type is marginal.
   - Below 5 per doc type is insufficient.
2. Evaluate pattern stability:
   - Are regressions or improvements concentrated in 1–2 transactions (isolated) or spread across many?
   - Are findings consistent with each other, or do they contradict?
3. Assess label quality:
   - Look for inconsistencies in the ground truth labels across similar transactions.
   - Flag if truth data (stage 2/4) appears sparse, contradictory, or implausible.
4. Determine if more evidence is needed:
   - If sample_size_verdict is 'insufficient' OR pattern_stability_verdict is 'isolated' → needs_more_evidence = true.
   - If needs_more_evidence is true, describe what specific evidence would resolve the concern.
5. Return a single valid JSON object matching the required schema.

Be skeptical. Your role is to prevent premature decisions, not to block all releases.
Challenge specific findings — do not issue a blanket block without cause.

Return ONLY valid JSON. Do not include markdown fences, explanations, or commentary.
"""

    task = Task(
        description=task_description,
        expected_output=(
            "A single valid JSON object with keys: confidence_assessment (object with "
            "overall_confidence, sample_size_verdict, pattern_stability_verdict, "
            "label_quality_concern), needs_more_evidence (bool), challenge_notes (list of str), "
            "sample_size_adequate (bool), label_noise_concern (bool), "
            "recommended_expansion (str or null)."
        ),
        agent=agent,
        # Keep provider-compatible response mode (no forced json_schema).
    )

    try:
        crew = Crew(agents=[agent], tasks=[task], verbose=True)
        result = crew.kickoff()
    except Exception:
        return _deterministic_challenger(
            total_transactions=total_transactions,
            doc_type_distribution=doc_type_distribution,
            improvement_findings=improvement_findings,
            regression_findings=regression_findings,
            hidden_risk_findings=hidden_risk_findings,
            evidence_summary=evidence_summary,
        )

    try:
        raw = result.raw if hasattr(result, "raw") else str(result)
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        if not isinstance(parsed, dict):
            raise ValueError("Challenger returned non-dict payload")
        return parsed
    except Exception:
        return _deterministic_challenger(
            total_transactions=total_transactions,
            doc_type_distribution=doc_type_distribution,
            improvement_findings=improvement_findings,
            regression_findings=regression_findings,
            hidden_risk_findings=hidden_risk_findings,
            evidence_summary=evidence_summary,
        )
