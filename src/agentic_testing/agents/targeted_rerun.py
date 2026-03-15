"""
agents/targeted_rerun.py

TargetedRerun Agent — when evidence is weak or a suspicious pattern appears, defines
the smallest most informative follow-up scope. Requests fewest extra transactions
needed to strengthen or disprove the finding.
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


def get_code_llm() -> LLM:
    return get_agent_llm("code")


# ---------------------------------------------------------------------------
# Output schema
# ---------------------------------------------------------------------------

class TargetedRerunSummary(BaseModel):
    pattern_identified: str = Field(
        ...,
        description=(
            "The specific pattern that triggered the rerun request: "
            "e.g., 'Passport extraction empty-field spike in 2024-Q4'"
        ),
    )
    rationale: str = Field(
        ...,
        description="Why this specific pattern was selected for follow-up",
    )


class ScopeExpansionRequest(BaseModel):
    new_transaction_ids: List[int] = Field(
        default_factory=list,
        description="Additional transaction IDs to include in the expanded scope",
    )
    expansion_reason: str = Field(
        ..., description="Plain-English reason for adding these transactions"
    )
    doctype_filter: Optional[str] = Field(
        default=None,
        description="If set, restrict expansion to this document type",
    )
    date_filter: Optional[str] = Field(
        default=None,
        description="If set, restrict expansion to this date range (ISO format: YYYY-MM-DD/YYYY-MM-DD)",
    )


class TargetedRerunOutput(BaseModel):
    targeted_rerun_summary: TargetedRerunSummary = Field(
        ..., description="Summary of the pattern identified and why it needs follow-up"
    )
    scope_expansion_request: ScopeExpansionRequest = Field(
        ..., description="Specifics of the scope expansion being requested"
    )
    transactions_added: List[int] = Field(
        default_factory=list,
        description="Final list of transaction IDs added to the scope",
    )
    expansion_rationale: str = Field(
        ...,
        description="Full rationale for the expansion decision",
    )
    rerun_findings: list[Dict[str, Any]] = Field(
        default_factory=list,
        description=(
            "Findings from the targeted rerun (populated after rerun completes). "
            "Empty list if the rerun has not yet been executed."
        ),
    )


# ---------------------------------------------------------------------------
# Agent entry point
# ---------------------------------------------------------------------------

def run_targeted_rerun(state_dict: Dict[str, Any]) -> Dict[str, Any]:
    """
    Run the TargetedRerun agent.

    Args:
        state_dict: Relevant subset of FlowState as a dict. Expected keys:
            - needs_more_evidence (bool): From Challenger agent.
            - challenge_notes (list[str]): From Challenger agent.
            - hidden_risk_findings (list[dict]): From RegressionHunter.
            - change_summary (dict): From IntakeDiff agent.
            - current_scope (dict): Currently active scope config.
            - evidence_store_path (str): Path to the evidence store.
            - max_total_transactions (int): Hard cap on total transactions across all reruns.
            - run_id (str): Unique run identifier.

    Returns:
        dict conforming to TargetedRerunOutput schema, or error dict on failure.
    """
    from agentic_testing.tools.rerun_tools import expand_scope_by_pattern, request_targeted_rerun

    needs_more_evidence: bool = state_dict.get("needs_more_evidence", False)
    challenge_notes: list = state_dict.get("challenge_notes", [])
    hidden_risk_findings: list = state_dict.get("hidden_risk_findings", [])
    change_summary: Dict[str, Any] = state_dict.get("change_summary", {})
    current_scope: Dict[str, Any] = state_dict.get("current_scope", {})
    evidence_store_path: str = state_dict.get("evidence_store_path", "")
    max_total_transactions: int = state_dict.get("max_total_transactions", 100)
    run_id: str = state_dict.get("run_id", "unknown_run")

    currently_selected: list = current_scope.get("transaction_ids", [])
    remaining_budget: int = max(0, max_total_transactions - len(currently_selected))

    llm = get_code_llm()

    prompt_file = os.path.join(os.path.dirname(__file__), "..", "prompts", "targeted_rerun.txt")
    backstory_extra = ""
    if os.path.exists(prompt_file):
        with open(prompt_file, "r", encoding="utf-8") as fh:
            backstory_extra = fh.read()

    agent = Agent(
        role="Targeted Rerun Strategist",
        goal=(
            "When evidence is weak or a suspicious pattern appears, define the smallest most "
            "informative follow-up scope. Do not ask for all data — ask for the fewest extra "
            "transactions needed to strengthen or disprove the finding."
        ),
        backstory=(
            "You are a performance tester who knows that targeted evidence is worth 10x more "
            "than broad noise. You identify the exact pattern — by doctype, confidence band, "
            "date range, or exception type — that will most efficiently resolve the open question.\n\n"
            + backstory_extra
        ),
        tools=[expand_scope_by_pattern, request_targeted_rerun],
        llm=llm,
        verbose=True,
        max_iter=3,
    )

    task_description = f"""
You are performing targeted rerun strategy for run '{run_id}'.

--- CHALLENGER VERDICT ---
needs_more_evidence: {needs_more_evidence}
challenge_notes:
{json.dumps(challenge_notes, indent=2)}

--- HIDDEN RISK FINDINGS ---
{json.dumps(hidden_risk_findings, indent=2)}

--- CHANGE SUMMARY ---
{json.dumps(change_summary, indent=2)}

--- CURRENT SCOPE ---
{json.dumps(current_scope, indent=2)}

--- CONSTRAINTS ---
evidence_store_path: {evidence_store_path}
max_total_transactions: {max_total_transactions}
currently_selected_count: {len(currently_selected)}
remaining_budget: {remaining_budget}

Your tasks:
1. If needs_more_evidence is False AND hidden_risk_findings is empty:
   - Do NOT expand scope. Return an empty expansion with clear rationale.
2. If needs_more_evidence is True OR hidden_risk_findings is non-empty:
   a. Identify the MOST SPECIFIC pattern from challenge_notes and hidden_risk_findings.
   b. Use `expand_scope_by_pattern` to find transactions matching that pattern.
   c. Select the minimum set needed (aim for 10–20 additional transactions per pattern).
   d. Use `request_targeted_rerun` to register the expansion request.
   e. Stay within the remaining_budget of {remaining_budget} transactions.
3. Return a single valid JSON object matching the required schema.

Principle of minimal expansion:
- Prefer 1 targeted filter (doctype + date range) over broad expansion.
- If the challenger flagged "insufficient Passport data", expand on Passport only.
- If a confidence mismatch was found in a specific date band, filter by that date band.
- Never request all remaining data — always apply at least one filter.

Return ONLY valid JSON. Do not include markdown fences, explanations, or commentary.
"""

    task = Task(
        description=task_description,
        expected_output=(
            "A single valid JSON object with keys: targeted_rerun_summary (object with "
            "pattern_identified and rationale), scope_expansion_request (object with "
            "new_transaction_ids, expansion_reason, doctype_filter, date_filter), "
            "transactions_added (list of int), expansion_rationale (str), rerun_findings (list)."
        ),
        agent=agent,
        output_pydantic=TargetedRerunOutput,
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
