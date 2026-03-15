"""
agents/trend_drift.py

TrendDrift Agent - determines whether performance is improving, declining,
plateauing, or suddenly regressing.
"""

import json
import os
from typing import Any, Dict, List

from crewai import Agent, Crew, LLM, Task
from pydantic import BaseModel, Field

from agentic_testing.agent_mode import use_deterministic_mode
from agentic_testing.llm_factory import get_agent_llm


def get_reasoning_llm() -> LLM:
    return get_agent_llm("reasoning")


def get_structured_llm() -> LLM:
    return get_agent_llm("structured")


class DriftAlert(BaseModel):
    doctype: str = Field(..., description="Document type where the drift was detected")
    alert_type: str = Field(..., description="Type of drift alert")
    description: str = Field(..., description="Description of the drift event")
    severity: str = Field(..., description="Severity: low, medium, high, critical")


class TrendSummary(BaseModel):
    by_doctype: Dict[str, Any] = Field(default_factory=dict)
    overall_direction: str = Field(...)


class TrendDriftOutput(BaseModel):
    trend_summary: TrendSummary = Field(...)
    drift_alerts: List[DriftAlert] = Field(default_factory=list)
    trend_direction: str = Field(...)
    trend_confidence: float = Field(..., ge=0.0, le=1.0)


def _deterministic_trend_drift(summary_metrics: Dict[str, Any], regression_findings: list) -> Dict[str, Any]:
    try:
        delta = float(summary_metrics.get("weighted_f1_delta", 0.0))
    except (TypeError, ValueError, AttributeError):
        delta = 0.0

    if delta > 0.02:
        direction = "improving"
    elif delta < -0.05:
        direction = "sudden_regression"
    elif delta < -0.02:
        direction = "declining"
    elif abs(delta) <= 0.01:
        direction = "plateau"
    else:
        direction = "converging"

    drift_alerts: List[Dict[str, Any]] = []
    if direction in {"declining", "sudden_regression"}:
        drift_alerts.append(
            {
                "doctype": "overall",
                "alert_type": direction,
                "description": f"Weighted F1 delta is {delta:.4f}, indicating {direction}.",
                "severity": "high" if direction == "sudden_regression" else "medium",
            }
        )
    if regression_findings:
        drift_alerts.append(
            {
                "doctype": "mixed",
                "alert_type": "sustained_decline" if len(regression_findings) > 1 else "sudden_regression",
                "description": f"Observed {len(regression_findings)} regression finding(s).",
                "severity": "medium",
            }
        )

    return {
        "trend_summary": {"by_doctype": {}, "overall_direction": direction},
        "drift_alerts": drift_alerts,
        "trend_direction": direction,
        "trend_confidence": 0.75 if summary_metrics else 0.55,
    }


def run_trend_drift(state_dict: Dict[str, Any]) -> Dict[str, Any]:
    """
    Run the TrendDrift agent.
    """
    from agentic_testing.tools.excel_reader import read_model_data

    date_from: str = state_dict.get("date_from", "")
    date_to: str = state_dict.get("date_to", "")
    evidence_store_path: str = state_dict.get("evidence_store_path", "")
    summary_metrics: Dict[str, Any] = state_dict.get("summary_metrics", {})
    regression_findings: list = state_dict.get("regression_findings", [])
    run_id: str = state_dict.get("run_id", "unknown_run")

    if use_deterministic_mode():
        return _deterministic_trend_drift(summary_metrics=summary_metrics, regression_findings=regression_findings)

    llm = get_structured_llm()

    prompt_file = os.path.join(os.path.dirname(__file__), "..", "prompts", "trend_drift.txt")
    backstory_extra = ""
    if os.path.exists(prompt_file):
        with open(prompt_file, "r", encoding="utf-8") as fh:
            backstory_extra = fh.read()

    agent = Agent(
        role="Trend and Drift Analyst",
        goal="Assess trend direction and drift risk from current and historical evidence.",
        backstory="You analyze trend direction conservatively and avoid overclaiming.\n\n" + backstory_extra,
        tools=[read_model_data],
        llm=llm,
        verbose=True,
        max_iter=3,
    )

    task_description = f"""
Run ID: {run_id}
date_from: {date_from or "(not set)"}
date_to: {date_to or "(not set)"}
evidence_store_path: {evidence_store_path}
summary_metrics: {json.dumps(summary_metrics, indent=2)}
regression_findings: {json.dumps(regression_findings, indent=2)}

Return JSON with keys:
- trend_summary
- drift_alerts
- trend_direction
- trend_confidence
"""

    task = Task(
        description=task_description,
        expected_output="A valid JSON object matching TrendDriftOutput fields.",
        agent=agent,
    )

    try:
        result = Crew(agents=[agent], tasks=[task], verbose=True).kickoff()
        raw = result.raw if hasattr(result, "raw") else str(result)
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        if not isinstance(parsed, dict):
            raise ValueError("TrendDrift returned non-dict payload")
        return parsed
    except Exception:
        return _deterministic_trend_drift(summary_metrics=summary_metrics, regression_findings=regression_findings)

