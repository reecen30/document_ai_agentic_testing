"""
agents/root_cause.py

RootCause Agent — identifies the most likely causes of regressions or improvements by
correlating findings with the execution artifact change. Separates prompt issues from
model issues from label quality issues.
"""

import json
import os
from typing import Any, Dict, List, Optional

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

class RootCauseEntry(BaseModel):
    cause: str = Field(..., description="Description of the root cause")
    cause_type: str = Field(
        ...,
        description=(
            "Category of the cause: prompt | model | label | evidence | configuration"
        ),
    )
    confidence: float = Field(
        ..., ge=0.0, le=1.0, description="Confidence that this is the actual cause (0.0–1.0)"
    )
    supporting_evidence: List[str] = Field(
        default_factory=list,
        description="List of specific evidence items that support this cause hypothesis",
    )


class RootCauseOutput(BaseModel):
    root_causes: List[RootCauseEntry] = Field(
        default_factory=list,
        description="Ranked list of root causes, most confident first",
    )
    primary_cause: Optional[str] = Field(
        default=None,
        description=(
            "The single most likely root cause in plain English. "
            "Null if no cause can be identified with confidence > 0.4."
        ),
    )
    confidence: float = Field(
        ..., ge=0.0, le=1.0, description="Overall confidence in the root cause analysis"
    )


# ---------------------------------------------------------------------------
# Agent entry point
# ---------------------------------------------------------------------------

def run_root_cause(state_dict: Dict[str, Any]) -> Dict[str, Any]:
    """
    Run the RootCause agent.

    Args:
        state_dict: Relevant subset of FlowState as a dict. Expected keys:
            - change_summary (dict): Output from IntakeDiff agent.
            - regression_findings (list[dict]): From RegressionHunter.
            - targeted_rerun_summary (dict or None): From TargetedRerun agent (may be absent).
            - trend_summary (dict): From TrendDrift agent.
            - run_id (str): Unique run identifier.

    Returns:
        dict conforming to RootCauseOutput schema, or error dict on failure.
    """
    change_summary: Dict[str, Any] = state_dict.get("change_summary", {})
    regression_findings: list = state_dict.get("regression_findings", [])
    targeted_rerun_summary: Optional[Dict[str, Any]] = state_dict.get("targeted_rerun_summary", None)
    trend_summary: Dict[str, Any] = state_dict.get("trend_summary", {})
    run_id: str = state_dict.get("run_id", "unknown_run")

    llm = get_reasoning_llm()

    prompt_file = os.path.join(os.path.dirname(__file__), "..", "prompts", "root_cause.txt")
    backstory_extra = ""
    if os.path.exists(prompt_file):
        with open(prompt_file, "r", encoding="utf-8") as fh:
            backstory_extra = fh.read()

    agent = Agent(
        role="Root Cause Investigator",
        goal=(
            "Identify the most likely causes of regressions or improvements by correlating "
            "findings with the execution artifact change. Separate prompt issues from model "
            "issues from label quality issues."
        ),
        backstory=(
            "You are a senior debugging expert who never jumps to conclusions. You correlate "
            "error clusters with what changed in the prompt or model. You always rank causes "
            "by confidence and clearly state what evidence supports each cause.\n\n"
            + backstory_extra
        ),
        tools=[],
        llm=llm,
        verbose=True,
        max_iter=3,
    )

    task_description = f"""
You are performing root cause analysis for run '{run_id}'.

--- CHANGE SUMMARY (what changed in this release) ---
{json.dumps(change_summary, indent=2)}

--- REGRESSION FINDINGS ---
{json.dumps(regression_findings, indent=2)}

--- TARGETED RERUN SUMMARY ---
{json.dumps(targeted_rerun_summary, indent=2) if targeted_rerun_summary else "(no targeted rerun was performed)"}

--- TREND SUMMARY ---
{json.dumps(trend_summary, indent=2)}

Your tasks:
1. For each regression finding, correlate it with the change_summary:
   - If the regression affects classification: look for classification guidance changes in the prompt.
   - If the regression affects extraction fields: look for extraction instruction changes.
   - If the regression is model-wide: look for model identity changes.
   - If the regression is doc-type-specific: look for scope changes for that doc type.
2. Consider alternative causes:
   - label: The ground truth data changed or was noisy (not a model problem).
   - evidence: The evidence is too sparse to confirm the regression.
   - configuration: A deployment config change (thresholds, routing) may be responsible.
3. For each cause, list specific supporting evidence items (quote from change_summary or findings).
4. Rank causes by confidence (0.0–1.0). Never claim certainty (max realistic confidence: 0.85).
5. Identify the primary_cause only if confidence > 0.4 for the top candidate.
6. Return a single valid JSON object matching the required schema.

Cause type taxonomy:
- prompt: The regression correlates with a specific change in prompt wording or instructions.
- model: The regression correlates with a model version change and is present across all doc types.
- label: The "regression" appears in ground truth inconsistencies, not in model output.
- evidence: The evidence is insufficient to determine causality (small n, isolated patterns).
- configuration: A non-prompt, non-model configuration change caused the behavior change.

Return ONLY valid JSON. Do not include markdown fences, explanations, or commentary.
"""

    task = Task(
        description=task_description,
        expected_output=(
            "A single valid JSON object with keys: root_causes (list of objects with cause, "
            "cause_type, confidence, supporting_evidence), primary_cause (str or null), "
            "confidence (float)."
        ),
        agent=agent,
        output_pydantic=RootCauseOutput,
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
