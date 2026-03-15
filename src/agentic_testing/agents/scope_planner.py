"""
agents/scope_planner.py

ScopePlanner Agent — selects the most informative initial slice of transactions to analyze.
Respects user-supplied scope when present; otherwise performs risk-based selection.
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

class AnalysisPlan(BaseModel):
    rationale: str = Field(..., description="Why this particular scope was chosen")
    approach: str = Field(..., description="How the analysis will proceed step by step")
    risk_areas: list[str] = Field(default_factory=list, description="Risk areas to watch in this scope")


class ScopePlannerOutput(BaseModel):
    selected_transaction_ids: list[int] = Field(
        default_factory=list,
        description="Ordered list of transaction IDs selected for analysis",
    )
    selected_doc_types: list[str] = Field(
        default_factory=list,
        description="Document type names covered by the selected transactions",
    )
    analysis_plan: AnalysisPlan = Field(
        ..., description="Structured plan including rationale, approach, and risk areas"
    )
    scope_rationale: str = Field(
        ..., description="Human-readable explanation of how and why this scope was chosen"
    )
    initial_transaction_count: int = Field(
        ..., description="Number of transactions selected for initial analysis"
    )
    expansion_allowed: bool = Field(
        ..., description="Whether the agent is permitted to expand scope if evidence is weak"
    )


def _dedupe_keep_order(values: list) -> list:
    seen = set()
    result = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _deterministic_scope_planner(
    scope: Dict[str, Any],
    change_summary: Dict[str, Any],
    max_initial_transactions: int,
    evidence_store_path: str,
    evidence_store_config: Dict[str, Any],
) -> Dict[str, Any]:
    from agentic_testing.tools.excel_reader import read_document_data

    user_transaction_ids = scope.get("transaction_ids") or []
    document_type_names = scope.get("document_type_names") or []
    allow_expand = bool(scope.get("allow_agent_to_expand_scope", False))
    process_stage_ids = scope.get("process_stage_ids") or [1, 2, 3, 4]
    date_from = scope.get("date_from")
    date_to = scope.get("date_to")

    selected_ids: list[int] = []
    selected_doc_types: list[str] = []

    if user_transaction_ids:
        selected_ids = [int(x) for x in user_transaction_ids if str(x).strip().isdigit()][:max_initial_transactions]
        selected_doc_types = [str(x) for x in document_type_names]
        rationale = "Used explicit transaction_ids provided in scope."
    else:
        sheet_names = evidence_store_config.get("sheet_names", {}) if isinstance(evidence_store_config, dict) else {}
        document_sheet = str(sheet_names.get("document_data", "DocumentData"))
        raw = read_document_data._run(
            workbook_path=evidence_store_path,
            sheet_name=document_sheet,
            transaction_ids=None,
            process_stage_ids=process_stage_ids,
            document_type_names=document_type_names or None,
            date_from=date_from,
            date_to=date_to,
            max_rows=20000,
        )
        rows = json.loads(raw)
        if isinstance(rows, dict):
            rows = []

        critical = {"IdentityDocument", "Passport", "ApplicationForm"}
        if not document_type_names:
            rows.sort(key=lambda r: (0 if str(r.get("DocumentTypeName")) in critical else 1, str(r.get("CreatedDateTime", ""))), reverse=False)

        tx_ids = [int(r.get("TransactionID")) for r in rows if str(r.get("TransactionID", "")).isdigit()]
        selected_ids = _dedupe_keep_order(tx_ids)[:max_initial_transactions]

        dt_map = {}
        for r in rows:
            tid = r.get("TransactionID")
            if not str(tid).isdigit():
                continue
            if int(tid) not in set(selected_ids):
                continue
            dt = str(r.get("DocumentTypeName", "")).strip()
            if dt:
                dt_map[dt] = dt_map.get(dt, 0) + 1
        selected_doc_types = list(dt_map.keys())
        rationale = "Risk-based deterministic selection from evidence store."

    return {
        "selected_transaction_ids": selected_ids,
        "selected_doc_types": selected_doc_types,
        "analysis_plan": {
            "rationale": rationale,
            "approach": "Select high-signal transactions first, then expand only if evidence remains weak.",
            "risk_areas": [str(x) for x in (change_summary.get("artifact_diff_summary") or [])][:6],
        },
        "scope_rationale": rationale,
        "initial_transaction_count": len(selected_ids),
        "expansion_allowed": allow_expand,
    }


# ---------------------------------------------------------------------------
# Agent entry point
# ---------------------------------------------------------------------------

def run_scope_planner(state_dict: Dict[str, Any]) -> Dict[str, Any]:
    """
    Run the ScopePlanner agent.

    Args:
        state_dict: Relevant subset of FlowState as a dict. Expected keys:
            - change_summary (dict): Output from IntakeDiff agent.
            - scope (dict): User-supplied scope config with optional keys:
                - date_from (str): ISO date string.
                - date_to (str): ISO date string.
                - transaction_ids (list[int]): Explicit transaction IDs to use.
                - document_type_names (list[str]): Filter to these doc types.
                - allow_agent_to_expand_scope (bool): Permission flag.
            - max_initial_transactions (int): Hard cap on initial scope size.
            - evidence_store_path (str): Path to the Excel evidence store.
            - run_id (str): Unique run identifier.

    Returns:
        dict conforming to ScopePlannerOutput schema, or error dict on failure.
    """
    from agentic_testing.tools.excel_reader import read_document_data, read_lookup_sheet

    change_summary: Dict[str, Any] = state_dict.get("change_summary", {})
    scope: Dict[str, Any] = state_dict.get("scope", {})
    max_initial_transactions: int = state_dict.get("max_initial_transactions", 30)
    evidence_store_path: str = state_dict.get("evidence_store_path", "")
    run_id: str = state_dict.get("run_id", "unknown_run")

    # Decompose scope config
    date_from: str = scope.get("date_from", "")
    date_to: str = scope.get("date_to", "")
    user_transaction_ids: list = scope.get("transaction_ids", [])
    document_type_names: list = scope.get("document_type_names", [])
    allow_expand: bool = scope.get("allow_agent_to_expand_scope", False)

    if use_deterministic_mode():
        return _deterministic_scope_planner(
            scope=scope,
            change_summary=change_summary,
            max_initial_transactions=max_initial_transactions,
            evidence_store_path=evidence_store_path,
            evidence_store_config=state_dict.get("evidence_store_config", {}),
        )

    llm = get_reasoning_llm()

    prompt_file = os.path.join(os.path.dirname(__file__), "..", "prompts", "scope_planner.txt")
    backstory_extra = ""
    if os.path.exists(prompt_file):
        with open(prompt_file, "r", encoding="utf-8") as fh:
            backstory_extra = fh.read()

    agent = Agent(
        role="Scope Planning Strategist",
        goal=(
            "Select the most informative initial slice of transactions to analyze. "
            "Respect user-supplied scope if present. Otherwise choose risk-based transactions "
            "that are most likely to reveal improvements or regressions quickly."
        ),
        backstory=(
            "You are a testing strategy expert who understands that the right sample matters more "
            "than a large sample. You prioritize critical document types (IdentityDocument, Passport, "
            "ApplicationForm), recent data, and previously unstable transaction patterns.\n\n"
            + backstory_extra
        ),
        tools=[read_document_data, read_lookup_sheet],
        llm=llm,
        verbose=True,
        max_iter=3,
    )

    task_description = f"""
You are performing scope planning for run '{run_id}'.

--- CHANGE SUMMARY FROM INTAKE DIFF ---
{json.dumps(change_summary, indent=2)}

--- USER-SUPPLIED SCOPE CONFIG ---
date_from: {date_from or "(not set)"}
date_to: {date_to or "(not set)"}
transaction_ids: {user_transaction_ids or "(not set — agent must choose)"}
document_type_names: {document_type_names or "(not set — agent must choose)"}
allow_agent_to_expand_scope: {allow_expand}

--- CONSTRAINTS ---
max_initial_transactions: {max_initial_transactions}
evidence_store_path: {evidence_store_path}

Your tasks:
1. Use `read_lookup_sheet` to retrieve available document types and any priority flags.
2. Use `read_document_data` to inspect available transactions matching any user-supplied filters.
3. If the user supplied explicit transaction_ids, use them (up to max_initial_transactions).
   If NOT, apply risk-based selection: prioritize IdentityDocument, Passport, ApplicationForm,
   then transactions flagged in the change_summary risk_areas, then recent transactions.
4. Cap at max_initial_transactions.
5. Return a single valid JSON object matching the required schema.

Selection strategy when no user IDs are provided:
- Step 1: Include all transactions of critical doc types first.
- Step 2: Add transactions with known low-confidence patterns from change_summary.
- Step 3: Fill remaining slots with most recent transactions.
- Never exceed max_initial_transactions.

Return ONLY valid JSON. Do not include markdown fences, explanations, or commentary.
"""

    task = Task(
        description=task_description,
        expected_output=(
            "A single valid JSON object with keys: selected_transaction_ids (list of int), "
            "selected_doc_types (list of str), analysis_plan (object with rationale, approach, "
            "risk_areas), scope_rationale (str), initial_transaction_count (int), "
            "expansion_allowed (bool)."
        ),
        agent=agent,
        # Keep provider-compatible response mode (no forced json_schema).
    )

    try:
        crew = Crew(agents=[agent], tasks=[task], verbose=True)
        result = crew.kickoff()
    except Exception:
        return _deterministic_scope_planner(
            scope=scope,
            change_summary=change_summary,
            max_initial_transactions=max_initial_transactions,
            evidence_store_path=evidence_store_path,
            evidence_store_config=state_dict.get("evidence_store_config", {}),
        )

    try:
        raw = result.raw if hasattr(result, "raw") else str(result)
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        if not isinstance(parsed, dict):
            raise ValueError("Scope planner returned non-dict payload")
        return parsed
    except Exception:
        return _deterministic_scope_planner(
            scope=scope,
            change_summary=change_summary,
            max_initial_transactions=max_initial_transactions,
            evidence_store_path=evidence_store_path,
            evidence_store_config=state_dict.get("evidence_store_config", {}),
        )
