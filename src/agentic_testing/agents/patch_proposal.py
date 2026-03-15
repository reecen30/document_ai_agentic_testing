"""
agents/patch_proposal.py

PatchProposal Agent — proposes the smallest safe patch candidates and follow-up experiments
that could address observed problems. Focuses on prompt wording, exclusion criteria,
extraction instructions, and benchmark coverage. All patches require human approval.
"""

import json
import os
from typing import Any, Dict, List

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

class PatchCandidate(BaseModel):
    patch_id: str = Field(..., description="Unique identifier for this patch candidate (e.g., PATCH-001)")
    patch_type: str = Field(
        ...,
        description="Type of patch: prompt | model | benchmark | experiment",
    )
    target: str = Field(
        ...,
        description=(
            "What this patch targets: e.g., 'classification guidance for Passport', "
            "'extraction instruction for field:DateOfBirth', 'benchmark coverage for ApplicationForm'"
        ),
    )
    description: str = Field(..., description="Plain-English description of what this patch does")
    proposed_change: str = Field(
        ...,
        description="The actual proposed change — exact wording, model version, or benchmark addition",
    )
    confidence: float = Field(
        ..., ge=0.0, le=1.0, description="Confidence that this patch will address the root cause"
    )
    requires_human_approval: bool = Field(
        default=True,
        description="Always True — no patch may be applied without human review and approval",
    )
    priority: str = Field(
        ..., description="Priority: critical | high | medium | low"
    )


class PatchProposalOutput(BaseModel):
    patch_candidates: List[PatchCandidate] = Field(
        default_factory=list,
        description="Ranked list of patch candidates, highest priority first",
    )
    recommended_experiments: List[str] = Field(
        default_factory=list,
        description=(
            "Follow-up experiments to run after applying patches. "
            "E.g., 'Re-run on 50 Passport transactions with the patched prompt to verify fix.'"
        ),
    )
    patch_rationale: str = Field(
        ...,
        description="Overall rationale connecting root causes to proposed patches",
    )


def _deterministic_patch_proposal(
    run_id: str,
    workspace_path: str,
    root_causes: list,
    regression_findings: list,
) -> Dict[str, Any]:
    from agentic_testing.tools.rerun_tools import write_patch_candidate

    patch_candidates: list[Dict[str, Any]] = []
    for idx, cause in enumerate(root_causes[:3], start=1):
        cause_text = str((cause or {}).get("cause", "Unspecified cause"))
        conf = float((cause or {}).get("confidence", 0.6) or 0.6)
        patch = {
            "patch_id": f"PATCH-{idx:03d}",
            "patch_type": "prompt",
            "target": "execution_artifact",
            "description": f"Targeted prompt adjustment for: {cause_text}",
            "proposed_change": "Tighten classification guards and clarify extraction constraints for affected patterns.",
            "confidence": max(0.3, min(0.9, round(conf, 2))),
            "requires_human_approval": True,
            "priority": "high" if conf >= 0.7 else "medium",
        }
        patch_candidates.append(patch)
        try:
            write_patch_candidate._run(
                workspace_path=workspace_path,
                patch_id=patch["patch_id"],
                patch_data={
                    "run_id": run_id,
                    "description": patch["description"],
                    "proposed_change": patch["proposed_change"],
                    "confidence": patch["confidence"],
                    "requires_human_approval": True,
                },
            )
        except Exception:
            pass

    if not patch_candidates and regression_findings:
        patch_candidates.append(
            {
                "patch_id": "PATCH-001",
                "patch_type": "prompt",
                "target": "execution_artifact",
                "description": "Introduce stricter out-of-scope guardrails for noisy pages.",
                "proposed_change": "Add explicit exclusion wording for non-target document families.",
                "confidence": 0.62,
                "requires_human_approval": True,
                "priority": "medium",
            }
        )

    recommended_experiments = []
    if patch_candidates:
        recommended_experiments.append("Run targeted rerun on affected doc types after applying patch candidates.")
        recommended_experiments.append("Compare weighted_f1_delta and missing-field rates before/after patch.")

    rationale = (
        "Patch candidates are minimal and tied to observed root causes."
        if patch_candidates
        else "No actionable root causes were identified for patch generation."
    )
    return {
        "patch_candidates": patch_candidates,
        "recommended_experiments": recommended_experiments,
        "patch_rationale": rationale,
    }


# ---------------------------------------------------------------------------
# Agent entry point
# ---------------------------------------------------------------------------

def run_patch_proposal(state_dict: Dict[str, Any]) -> Dict[str, Any]:
    """
    Run the PatchProposal agent.

    Args:
        state_dict: Relevant subset of FlowState as a dict. Expected keys:
            - root_causes (list[dict]): From RootCause agent.
            - change_summary (dict): From IntakeDiff agent.
            - regression_findings (list[dict]): From RegressionHunter.
            - workspace_path (str): Path to workspace where patch files will be written.
            - run_id (str): Unique run identifier.

    Returns:
        dict conforming to PatchProposalOutput schema, or error dict on failure.
    """
    from agentic_testing.tools.rerun_tools import write_patch_candidate

    root_causes: list = state_dict.get("root_causes", [])
    change_summary: Dict[str, Any] = state_dict.get("change_summary", {})
    regression_findings: list = state_dict.get("regression_findings", [])
    workspace_path: str = state_dict.get("workspace_path", "")
    run_id: str = state_dict.get("run_id", "unknown_run")

    if use_deterministic_mode():
        return _deterministic_patch_proposal(
            run_id=run_id,
            workspace_path=workspace_path,
            root_causes=root_causes,
            regression_findings=regression_findings,
        )

    llm = get_structured_llm()

    prompt_file = os.path.join(os.path.dirname(__file__), "..", "prompts", "patch_proposal.txt")
    backstory_extra = ""
    if os.path.exists(prompt_file):
        with open(prompt_file, "r", encoding="utf-8") as fh:
            backstory_extra = fh.read()

    agent = Agent(
        role="Safe Patch Proposal Architect",
        goal=(
            "Propose the smallest safe patch candidates and follow-up experiments that could "
            "address the observed problems. Focus on prompt wording, exclusion criteria, "
            "extraction instructions, and benchmark coverage. Never auto-approve production changes "
            "— all patches require human approval."
        ),
        backstory=(
            "You are a prompt engineer and AI improvement specialist. You propose minimal, targeted "
            "changes that are safe to review and test. You never auto-approve production changes — "
            "all patches require human approval.\n\n"
            + backstory_extra
        ),
        tools=[write_patch_candidate],
        llm=llm,
        verbose=True,
        max_iter=3,
    )

    task_description = f"""
You are proposing patch candidates for run '{run_id}'.

--- ROOT CAUSES (from RootCause agent) ---
{json.dumps(root_causes, indent=2)}

--- CHANGE SUMMARY ---
{json.dumps(change_summary, indent=2)}

--- REGRESSION FINDINGS ---
{json.dumps(regression_findings, indent=2)}

--- WORKSPACE PATH ---
{workspace_path}

Your tasks:
1. For each root cause with confidence > 0.3, propose at least one patch candidate.
2. Apply the minimal-change principle:
   - Prefer adding a single clarifying sentence to the prompt over rewriting sections.
   - Prefer an exclusion clause over changing classification thresholds.
   - Prefer a field-specific extraction instruction over a global extraction rule change.
3. For prompt patches, categorize them:
   - exclusion_wording: Adding "Do not classify X as Y when Z is present"
   - extraction_instructions: Clarifying how to extract a specific field
   - classification_guidance: Improving how a doc type is identified
   - scope_guards: Adding guards to prevent out-of-scope document processing
4. For each patch, write it to disk using `write_patch_candidate` with run_id and workspace_path.
5. Propose recommended_experiments to validate each patch.
6. ALL patches must have requires_human_approval = true — this is non-negotiable.
7. Return a single valid JSON object matching the required schema.

Patch priority rules:
- critical: Addresses a BLOCK-level regression in a critical doc type
- high: Addresses a regression in any doc type with evidence support
- medium: Addresses a hidden risk or improvement in a non-critical area
- low: Benchmark gap or cosmetic prompt improvement

Return ONLY valid JSON. Do not include markdown fences, explanations, or commentary.
"""

    task = Task(
        description=task_description,
        expected_output=(
            "A single valid JSON object with keys: patch_candidates (list of objects with "
            "patch_id, patch_type, target, description, proposed_change, confidence, "
            "requires_human_approval, priority), recommended_experiments (list of str), "
            "patch_rationale (str)."
        ),
        agent=agent,
        # Keep provider-compatible response mode (no forced json_schema).
    )

    try:
        crew = Crew(agents=[agent], tasks=[task], verbose=True)
        result = crew.kickoff()
    except Exception:
        return _deterministic_patch_proposal(
            run_id=run_id,
            workspace_path=workspace_path,
            root_causes=root_causes,
            regression_findings=regression_findings,
        )

    try:
        raw = result.raw if hasattr(result, "raw") else str(result)
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        if not isinstance(parsed, dict):
            raise ValueError("PatchProposal returned non-dict payload")
        return parsed
    except Exception:
        return _deterministic_patch_proposal(
            run_id=run_id,
            workspace_path=workspace_path,
            root_causes=root_causes,
            regression_findings=regression_findings,
        )
