"""
agents/evidence_collector.py

EvidenceCollector Agent — loads raw evidence rows from DocumentData, ai.ModelData,
ExceptionLogs, and api.APIData sheets and assembles them into compact, per-transaction
case bundles. Does NOT judge quality — only organizes evidence.
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

class EvidenceCollectorOutput(BaseModel):
    case_bundles: list[Dict[str, Any]] = Field(
        default_factory=list,
        description=(
            "List of per-transaction case bundles. Each bundle contains: transaction_id, "
            "doc_type, baseline_classify (stage 1), truth_classify (stage 2), "
            "baseline_extract (stage 3), truth_extract (stage 4), candidate data, "
            "exception_logs, api_data."
        ),
    )
    total_transactions: int = Field(..., description="Total number of transactions for which bundles were built")
    doc_type_distribution: Dict[str, int] = Field(
        default_factory=dict,
        description="Count of transactions per document type in the collected evidence",
    )
    evidence_quality_note: str = Field(
        ...,
        description=(
            "Neutral description of data completeness — NOT a quality judgment. "
            "States which stages are present or absent across the dataset."
        ),
    )
    missing_truth_count: int = Field(
        ..., description="Number of transactions missing truth (stage 2/4) data"
    )
    missing_candidate_count: int = Field(
        ..., description="Number of transactions missing candidate output data"
    )


def _deterministic_evidence_collector(
    evidence_store_path: str,
    selected_transaction_ids: list,
    sheet_names: Dict[str, str],
) -> Dict[str, Any]:
    from agentic_testing.tools.excel_reader import read_document_data, read_exception_logs, read_api_data
    from agentic_testing.tools.evidence_tools import build_case_bundle, summarize_evidence

    errors: List[str] = []

    if not evidence_store_path or not os.path.exists(evidence_store_path):
        error_msg = (
            "Evidence store workbook not found. "
            f"Resolved path: '{evidence_store_path}'. "
            "Set a valid payload store_ref or EVIDENCE_STORE_PATH."
        )
        return {
            "error": error_msg,
            "errors": [error_msg],
            "case_bundles": [],
            "total_transactions": 0,
            "doc_type_distribution": {},
            "evidence_quality_note": "MISSING_EVIDENCE_STORE",
            "missing_truth_count": 0,
            "missing_candidate_count": 0,
            "evidence_summary": {
                "total_transactions": 0,
                "doc_type_distribution": {},
                "missing_truth_count": 0,
                "missing_candidate_count": 0,
                "evidence_quality_note": "MISSING_EVIDENCE_STORE",
            },
            "evidence_store_path": evidence_store_path,
        }

    def _parse_rows(raw_payload: str, tool_name: str) -> List[Dict[str, Any]]:
        try:
            parsed = json.loads(raw_payload)
        except Exception as exc:
            errors.append(f"{tool_name}: failed to parse JSON payload ({exc})")
            return []
        if isinstance(parsed, dict):
            if parsed.get("error"):
                errors.append(f"{tool_name}: {parsed.get('error')}")
            else:
                errors.append(f"{tool_name}: unexpected object payload returned")
            return []
        if isinstance(parsed, list):
            return parsed
        errors.append(f"{tool_name}: unexpected payload type {type(parsed).__name__}")
        return []

    raw_doc = read_document_data._run(
        workbook_path=evidence_store_path,
        sheet_name=str(sheet_names.get("document_data", "DocumentData")),
        transaction_ids=selected_transaction_ids or None,
        process_stage_ids=[1, 2, 3, 4],
        max_rows=50000,
    )
    document_rows = _parse_rows(raw_doc, "read_document_data:DocumentData")

    if not selected_transaction_ids:
        selected_transaction_ids = sorted(
            {
                int(r.get("TransactionID"))
                for r in document_rows
                if str(r.get("TransactionID", "")).isdigit()
            }
        )

    raw_exc = read_exception_logs._run(
        workbook_path=evidence_store_path,
        sheet_name=str(sheet_names.get("exception_logs", "ExceptionLogs")),
        transaction_ids=selected_transaction_ids or None,
        max_rows=10000,
    )
    exception_rows = _parse_rows(raw_exc, "read_exception_logs")

    raw_api = read_api_data._run(
        workbook_path=evidence_store_path,
        sheet_name=str(sheet_names.get("api_data", "api.APIData")),
        transaction_ids=selected_transaction_ids or None,
        max_rows=10000,
    )
    api_rows = _parse_rows(raw_api, "read_api_data")

    candidate_sheet_name = str(
        sheet_names.get("candidate_data")
        or sheet_names.get("candidate_document_data")
        or "DocumentData_Candidate"
    )
    raw_candidate = read_document_data._run(
        workbook_path=evidence_store_path,
        sheet_name=candidate_sheet_name,
        transaction_ids=selected_transaction_ids or None,
        process_stage_ids=[1, 3],
        max_rows=50000,
    )
    candidate_rows = _parse_rows(raw_candidate, f"read_document_data:{candidate_sheet_name}")

    # Safe fallback: if no candidate sheet/rows are available, mirror baseline rows.
    if not candidate_rows:
        candidate_rows = [
            dict(r)
            for r in document_rows
            if int(r.get("ProcessStageID", 0) or 0) in {1, 3}
        ]
        errors.append(
            f"Candidate rows missing from sheet '{candidate_sheet_name}'. "
            "Falling back to baseline rows."
        )

    if not document_rows:
        error_msg = (
            "No DocumentData rows were loaded for the selected scope. "
            f"Workbook: '{evidence_store_path}'. "
            "Check path/sheet names/transaction IDs."
        )
        all_errors = [error_msg] + errors
        return {
            "error": error_msg,
            "errors": all_errors,
            "case_bundles": [],
            "total_transactions": 0,
            "doc_type_distribution": {},
            "evidence_quality_note": "NO_DOCUMENT_ROWS",
            "missing_truth_count": 0,
            "missing_candidate_count": 0,
            "evidence_summary": {
                "total_transactions": 0,
                "doc_type_distribution": {},
                "missing_truth_count": 0,
                "missing_candidate_count": 0,
                "evidence_quality_note": "NO_DOCUMENT_ROWS",
            },
            "candidate_sheet_name": candidate_sheet_name,
            "candidate_row_count": len(candidate_rows),
            "evidence_store_path": evidence_store_path,
            "read_row_counts": {
                "document_rows": 0,
                "candidate_rows": len(candidate_rows),
                "exception_rows": len(exception_rows),
                "api_rows": len(api_rows),
            },
        }

    case_bundles: list[Dict[str, Any]] = []
    for tid in selected_transaction_ids:
        raw_bundle = build_case_bundle._run(
            transaction_id=int(tid),
            document_data_rows=document_rows,
            exception_rows=exception_rows,
            api_rows=api_rows,
            candidate_rows=candidate_rows,
        )
        bundle = json.loads(raw_bundle)
        if isinstance(bundle, dict) and "error" not in bundle:
            case_bundles.append(bundle)

    raw_summary = summarize_evidence._run(case_bundles=case_bundles)
    summary = json.loads(raw_summary)
    if not isinstance(summary, dict):
        summary = {}

    result = {
        "case_bundles": case_bundles,
        "total_transactions": int(summary.get("total_transactions", len(case_bundles))),
        "doc_type_distribution": summary.get("doc_type_distribution", {}),
        "evidence_quality_note": summary.get("evidence_quality_note", ""),
        "missing_truth_count": int(summary.get("missing_truth_count", 0)),
        "missing_candidate_count": int(summary.get("missing_candidate_count", 0)),
        "evidence_summary": summary,
        "candidate_sheet_name": candidate_sheet_name,
        "candidate_row_count": len(candidate_rows),
        "evidence_store_path": evidence_store_path,
        "read_row_counts": {
            "document_rows": len(document_rows),
            "candidate_rows": len(candidate_rows),
            "exception_rows": len(exception_rows),
            "api_rows": len(api_rows),
        },
    }
    if errors:
        result["warnings"] = errors
    return result


# ---------------------------------------------------------------------------
# Agent entry point
# ---------------------------------------------------------------------------

def run_evidence_collector(state_dict: Dict[str, Any]) -> Dict[str, Any]:
    """
    Run the EvidenceCollector agent.

    Args:
        state_dict: Relevant subset of FlowState as a dict. Expected keys:
            - evidence_store_path (str): Path to the Excel evidence store workbook.
            - selected_transaction_ids (list[int]): Transaction IDs to collect evidence for.
            - evidence_store_config (dict): Config with key 'sheet_names' (dict mapping
              logical names to actual sheet names in the workbook).
            - run_id (str): Unique run identifier.

    Returns:
        dict conforming to EvidenceCollectorOutput schema, or error dict on failure.
    """
    from agentic_testing.tools.excel_reader import (
        read_document_data,
        read_model_data,
        read_exception_logs,
        read_api_data,
    )
    from agentic_testing.tools.evidence_tools import build_case_bundle, summarize_evidence

    evidence_store_path: str = state_dict.get("evidence_store_path", "")
    selected_transaction_ids: list = state_dict.get("selected_transaction_ids", [])
    evidence_store_config: Dict[str, Any] = state_dict.get("evidence_store_config", {})
    run_id: str = state_dict.get("run_id", "unknown_run")

    sheet_names: Dict[str, str] = evidence_store_config.get(
        "sheet_names",
        {
            "document_data": "DocumentData",
            "model_data": "ai.ModelData",
            "exception_logs": "ExceptionLogs",
            "api_data": "api.APIData",
        },
    )

    if use_deterministic_mode():
        return _deterministic_evidence_collector(
            evidence_store_path=evidence_store_path,
            selected_transaction_ids=selected_transaction_ids,
            sheet_names=sheet_names,
        )

    llm = get_structured_llm()

    prompt_file = os.path.join(os.path.dirname(__file__), "..", "prompts", "evidence_collector.txt")
    backstory_extra = ""
    if os.path.exists(prompt_file):
        with open(prompt_file, "r", encoding="utf-8") as fh:
            backstory_extra = fh.read()

    agent = Agent(
        role="Evidence Collection Specialist",
        goal=(
            "Load raw evidence rows from the DocumentData, ai.ModelData, ExceptionLogs, and "
            "api.APIData sheets and assemble them into compact, per-transaction case bundles. "
            "You do NOT judge quality — you only organize evidence."
        ),
        backstory=(
            "You are a data engineer who builds clean evidence packages. You are meticulous "
            "about separating baseline (stage 1/3), truth (stage 2/4), and candidate data. "
            "You never invent or modify evidence.\n\n"
            + backstory_extra
        ),
        tools=[
            read_document_data,
            read_model_data,
            read_exception_logs,
            read_api_data,
            build_case_bundle,
            summarize_evidence,
        ],
        llm=llm,
        verbose=True,
        max_iter=3,
    )

    task_description = f"""
You are collecting evidence for run '{run_id}'.

--- EVIDENCE STORE ---
Path: {evidence_store_path}
Sheet names:
  DocumentData sheet: {sheet_names.get("document_data", "DocumentData")}
  ai.ModelData sheet: {sheet_names.get("model_data", "ai.ModelData")}
  ExceptionLogs sheet: {sheet_names.get("exception_logs", "ExceptionLogs")}
  api.APIData sheet: {sheet_names.get("api_data", "api.APIData")}

--- TRANSACTION IDs TO COLLECT ---
{selected_transaction_ids}

Your tasks:
1. Use `read_document_data` to load document classification and metadata rows for the selected IDs.
2. Use `read_model_data` to load AI model output rows (stages 1–4) for the selected IDs.
   Stage mapping:
     Stage 1 = baseline classification output
     Stage 2 = truth/ground-truth classification
     Stage 3 = baseline extraction output
     Stage 4 = truth/ground-truth extraction
   Candidate data is the NEW model/prompt output being evaluated.
3. Use `read_exception_logs` to load any exception records for the selected IDs.
4. Use `read_api_data` to load API call records for the selected IDs.
5. Use `build_case_bundle` to assemble per-transaction bundles combining all of the above.
6. Use `summarize_evidence` to produce the doc_type_distribution and quality note.
7. Return a single valid JSON object matching the required schema.

IMPORTANT:
- Never invent, interpolate, or modify evidence data.
- If a stage is missing for a transaction, record it as null in the bundle.
- Count missing_truth_count and missing_candidate_count accurately.

Return ONLY valid JSON. Do not include markdown fences, explanations, or commentary.
"""

    task = Task(
        description=task_description,
        expected_output=(
            "A single valid JSON object with keys: case_bundles (list of bundle objects), "
            "total_transactions (int), doc_type_distribution (dict str->int), "
            "evidence_quality_note (str), missing_truth_count (int), missing_candidate_count (int)."
        ),
        agent=agent,
        # Keep provider-compatible response mode (no forced json_schema).
    )

    try:
        crew = Crew(agents=[agent], tasks=[task], verbose=True)
        result = crew.kickoff()
    except Exception:
        return _deterministic_evidence_collector(
            evidence_store_path=evidence_store_path,
            selected_transaction_ids=selected_transaction_ids,
            sheet_names=sheet_names,
        )

    try:
        raw = result.raw if hasattr(result, "raw") else str(result)
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        if not isinstance(parsed, dict):
            raise ValueError("Evidence collector returned non-dict payload")
        return parsed
    except Exception:
        return _deterministic_evidence_collector(
            evidence_store_path=evidence_store_path,
            selected_transaction_ids=selected_transaction_ids,
            sheet_names=sheet_names,
        )
