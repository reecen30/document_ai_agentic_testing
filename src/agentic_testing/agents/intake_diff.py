"""
agents/intake_diff.py

IntakeDiff Agent — compares the current execution artifact against the previous one,
identifies material changes in prompt text or model, and produces a structured change
summary with risk hypotheses.
"""

import json
import os
from typing import Any, Dict

from crewai import Agent, Crew, LLM, Task
from pydantic import BaseModel, Field

from agentic_testing.llm_factory import get_agent_llm


# ---------------------------------------------------------------------------
# LLM factory
# ---------------------------------------------------------------------------

def get_reasoning_llm() -> LLM:
    return get_agent_llm("reasoning")


def get_structured_llm() -> LLM:
    return get_agent_llm("structured")


# ---------------------------------------------------------------------------
# Output schema
# ---------------------------------------------------------------------------

class ArtifactDiffDetail(BaseModel):
    section: str = Field(..., description="Section of the prompt or artifact that changed")
    change_type: str = Field(..., description="Type of change: added, removed, modified, reworded")
    description: str = Field(..., description="Plain-English description of what changed")
    risk_level: str = Field(..., description="Risk level: low, medium, high, critical")


class RiskHypothesis(BaseModel):
    hypothesis: str = Field(..., description="Specific hypothesis about how this change may affect behavior")
    risk_area: str = Field(..., description="Area of risk: classification, extraction, confidence, scope, model_bias")
    risk_level: str = Field(..., description="Risk level: low, medium, high, critical")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Analyst confidence in this hypothesis (0.0–1.0)")


class IntakeDiffOutput(BaseModel):
    prompt_changed: bool = Field(..., description="Whether the prompt text materially changed")
    model_changed: bool = Field(..., description="Whether the model identifier changed")
    artifact_diff_summary: list[str] = Field(
        default_factory=list,
        description="High-level bullet points describing what changed",
    )
    artifact_diff_details: list[ArtifactDiffDetail] = Field(
        default_factory=list,
        description="Detailed per-section change records",
    )
    initial_risk_hypotheses: list[RiskHypothesis] = Field(
        default_factory=list,
        description="Ranked list of risk hypotheses generated from the diff",
    )
    confidence: float = Field(..., ge=0.0, le=1.0, description="Overall analyst confidence in the diff analysis")


# ---------------------------------------------------------------------------
# Agent entry point
# ---------------------------------------------------------------------------

def run_intake_diff(state_dict: Dict[str, Any]) -> Dict[str, Any]:
    """
    Run the IntakeDiff agent.

    Args:
        state_dict: Relevant subset of FlowState as a dict. Expected keys:
            - current_prompt_text (str): Full text of the current prompt artifact.
            - previous_prompt_text (str): Full text of the previous prompt artifact.
            - current_model (str): Current model identifier.
            - previous_model (str): Previous model identifier.
            - run_id (str): Unique run identifier for logging.
            - workspace_path (str): Path to the workspace for trace writes.

    Returns:
        dict conforming to IntakeDiffOutput schema, or error dict on failure.
    """
    from agentic_testing.tools.diff_tools import diff_prompt_artifacts, compare_model_change
    from agentic_testing.tools.logging_tools import write_model_data_trace

    current_artifact: Dict[str, Any] = state_dict.get("current_artifact", {}) or {}
    previous_artifact: Dict[str, Any] = state_dict.get("previous_artifact", {}) or {}

    current_prompt_text: str = state_dict.get("current_prompt_text") or current_artifact.get("prompt_text", "")
    previous_prompt_text: str = state_dict.get("previous_prompt_text") or previous_artifact.get("prompt_text", "")
    current_model: str = state_dict.get("current_model") or current_artifact.get("model_name", "unknown")
    previous_model: str = state_dict.get("previous_model") or previous_artifact.get("model_name", "unknown")
    run_id: str = state_dict.get("run_id", "unknown_run")
    workspace_path: str = state_dict.get("workspace_path", "")

    llm = get_reasoning_llm()

    # Load the system prompt from the companion .txt file if available
    prompt_file = os.path.join(os.path.dirname(__file__), "..", "prompts", "intake_diff.txt")
    backstory_extra = ""
    if os.path.exists(prompt_file):
        with open(prompt_file, "r", encoding="utf-8") as fh:
            backstory_extra = fh.read()

    agent = Agent(
        role="Intake Diff Analyst",
        goal=(
            "Compare the current execution artifact against the previous one, identify what "
            "materially changed in the prompt text or model, and produce a structured change "
            "summary with risk hypotheses."
        ),
        backstory=(
            "You are a senior AI engineer specializing in prompt engineering and model evaluation. "
            "You have deep expertise in identifying how changes to prompts affect document AI "
            "behavior, including classification errors, extraction gaps, false positives, and "
            "confidence degradation.\n\n"
            + backstory_extra
        ),
        tools=[diff_prompt_artifacts, compare_model_change, write_model_data_trace],
        llm=llm,
        verbose=True,
        max_iter=3,
    )

    task_description = f"""
You are performing an intake diff analysis for run '{run_id}'.

--- CURRENT MODEL ---
{current_model}

--- PREVIOUS MODEL ---
{previous_model}

--- CURRENT PROMPT TEXT ---
{current_prompt_text}

--- PREVIOUS PROMPT TEXT ---
{previous_prompt_text}

--- WORKSPACE PATH ---
{workspace_path}

Your tasks:
1. Use the `diff_prompt_artifacts` tool to produce a structured diff of the two prompt texts.
2. Use the `compare_model_change` tool to analyze whether the model change introduces risk.
3. Use the `write_model_data_trace` tool to persist a trace record for this diff event.
4. Synthesize the results and return a single valid JSON object matching the required schema.

Focus on:
- Added or removed classification guidance
- Changed extraction instructions (field names, formats, rules)
- Altered scoring or confidence thresholds
- Scope changes (document types added/removed)
- Model identity changes and known behavioral differences

Return ONLY valid JSON. Do not include markdown fences, explanations, or commentary.
"""

    task = Task(
        description=task_description,
        expected_output=(
            "A single valid JSON object with keys: prompt_changed (bool), model_changed (bool), "
            "artifact_diff_summary (list of strings), artifact_diff_details (list of objects with "
            "section, change_type, description, risk_level), initial_risk_hypotheses (list of "
            "objects with hypothesis, risk_area, risk_level, confidence), confidence (float)."
        ),
        agent=agent,
        output_pydantic=IntakeDiffOutput,
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
