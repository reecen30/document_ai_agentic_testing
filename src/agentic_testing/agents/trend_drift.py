"""
agents/trend_drift.py

TrendDrift Agent — analyzes whether the candidate is part of a sustained improvement trend,
a decline, a plateau, or a sudden regression. Focuses on patterns that matter to operations
and critical document types.
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

class DriftAlert(BaseModel):
    doctype: str = Field(..., description="Document type where the drift was detected")
    alert_type: str = Field(
        ...,
        description=(
            "Type of drift alert: sustained_decline, sudden_regression, "
            "plateau_broken, convergence_stall, confidence_drift"
        ),
    )
    description: str = Field(..., description="Plain-English description of the drift event")
    severity: str = Field(..., description="Severity: low, medium, high, critical")


class TrendSummary(BaseModel):
    by_doctype: Dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Per-document-type trend data. Keys are doc type names; "
            "values contain direction, velocity, run_count, metric_history."
        ),
    )
    overall_direction: str = Field(
        ...,
        description=(
            "Overall trend direction across all doc types: "
            "improving, declining, plateau, sudden_regression, converging"
        ),
    )


class TrendDriftOutput(BaseModel):
    trend_summary: TrendSummary = Field(..., description="Trend summary by doc type and overall")
    drift_alerts: List[DriftAlert] = Field(
        default_factory=list,
        description="List of drift alerts warranting attention",
    )
    trend_direction: str = Field(
        ...,
        description=(
            "Single-word trend direction: "
            "improving | declining | plateau | sudden_regression | converging"
        ),
    )
    trend_confidence: float = Field(
        ..., ge=0.0, le=1.0, description="Confidence in the trend assessment (0.0–1.0)"
    )


# ---------------------------------------------------------------------------
# Agent entry point
# ---------------------------------------------------------------------------

def run_trend_drift(state_dict: Dict[str, Any]) -> Dict[str, Any]:
    """
    Run the TrendDrift agent.

    Args:
        state_dict: Relevant subset of FlowState as a dict. Expected keys:
            - date_from (str): Start of analysis period (ISO date).
            - date_to (str): End of analysis period (ISO date).
            - evidence_store_path (str): Path to the Excel evidence store (for historical traces).
            - summary_metrics (dict): Current run's summary metrics from RegressionHunter.
            - regression_findings (list[dict]): Current run's regression findings.
            - run_id (str): Unique run identifier.

    Returns:
        dict conforming to TrendDriftOutput schema, or error dict on failure.
    """
    from agentic_testing.tools.excel_reader import read_model_data

    date_from: str = state_dict.get("date_from", "")
    date_to: str = state_dict.get("date_to", "")
    evidence_store_path: str = state_dict.get("evidence_store_path", "")
    summary_metrics: Dict[str, Any] = state_dict.get("summary_metrics", {})
    regression_findings: list = state_dict.get("regression_findings", [])
    run_id: str = state_dict.get("run_id", "unknown_run")

    llm = get_structured_llm()

    prompt_file = os.path.join(os.path.dirname(__file__), "..", "prompts", "trend_drift.txt")
    backstory_extra = ""
    if os.path.exists(prompt_file):
        with open(prompt_file, "r", encoding="utf-8") as fh:
            backstory_extra = fh.read()

    agent = Agent(
        role="Trend and Drift Analyst",
        goal=(
            "Analyze whether the candidate is part of a sustained improvement trend, a decline, "
            "a plateau, or a sudden regression. Focus on patterns that matter to operations and "
            "critical document types."
        ),
        backstory=(
            "You are a data scientist who specializes in time-series analysis of model performance. "
            "You understand that a single point in time is insufficient — what matters is direction "
            "and velocity.\n\n"
            + backstory_extra
        ),
        tools=[read_model_data],
        llm=llm,
        verbose=True,
        max_iter=3,
    )

    task_description = f"""
You are performing trend and drift analysis for run '{run_id}'.

--- ANALYSIS PERIOD ---
date_from: {date_from or "(not set — use all available history)"}
date_to: {date_to or "(not set — use all available history)"}

--- EVIDENCE STORE ---
Path: {evidence_store_path}

--- CURRENT RUN SUMMARY METRICS ---
{json.dumps(summary_metrics, indent=2)}

--- CURRENT RUN REGRESSION FINDINGS ---
{json.dumps(regression_findings, indent=2)}

Your tasks:
1. Use `read_model_data` to load historical run trace data from the ai.ModelData sheet.
   Focus on the following columns if available:
   - run_id, run_date, doc_type, weighted_f1, exact_match_rate, empty_rate, classification_accuracy
2. For each doc type represented in history, construct a time-ordered metric series.
3. Classify the trend for each doc type:
   - improving: consistent positive F1 delta over >= 3 consecutive runs
   - declining: consistent negative F1 delta over >= 3 consecutive runs
   - plateau: < 0.02 F1 change over last 5 runs
   - sudden_regression: F1 drop > 0.05 in a single run
   - converging: alternating small positive/negative, variance shrinking
4. Identify drift alerts for any doc type showing sudden_regression or sustained decline.
5. Determine an overall trend direction based on the weighted average across doc types.
6. Assign a trend_confidence score (0.0–1.0) based on:
   - Number of historical data points (more = higher confidence)
   - Consistency of the pattern (more consistent = higher confidence)
7. Return a single valid JSON object matching the required schema.

Key distinctions:
- plateau vs converging: plateau means stagnant performance; converging means oscillating but
  narrowing toward a stable value — converging is generally positive.
- sudden_regression vs declining: sudden means single-run drop; declining means sustained multi-run.

Return ONLY valid JSON. Do not include markdown fences, explanations, or commentary.
"""

    task = Task(
        description=task_description,
        expected_output=(
            "A single valid JSON object with keys: trend_summary (object with by_doctype dict "
            "and overall_direction), drift_alerts (list of objects with doctype, alert_type, "
            "description, severity), trend_direction (str), trend_confidence (float)."
        ),
        agent=agent,
        output_pydantic=TrendDriftOutput,
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
