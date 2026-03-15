"""
Rerun tools — expand transaction scope and simulate rerun requests.
In production, RequestTargetedRerunTool would trigger a UiPath process.
"""
import datetime
import json
import os
import uuid
from typing import Any, Dict, List, Optional, Type
from crewai.tools import BaseTool
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# ExpandScopeByPatternTool
# ---------------------------------------------------------------------------

SUPPORTED_PATTERNS = [
    "low_confidence_hard_negatives",
    "specific_doctype",
    "date_range",
    "all_errors",
    "random_sample",
]


class ExpandScopeByPatternInput(BaseModel):
    evidence_store_path: str = Field(..., description="Absolute path to the evidence store workbook.")
    pattern_name: str = Field(
        ...,
        description=(
            "Expansion strategy. One of: low_confidence_hard_negatives, specific_doctype, "
            "date_range, all_errors, random_sample."
        ),
    )
    seed_transaction_ids: Optional[List[int]] = Field(
        default=None,
        description="Initial transaction IDs to include regardless of pattern.",
    )
    document_type_name: Optional[str] = Field(
        default=None,
        description="Required when pattern_name='specific_doctype'.",
    )
    date_from: Optional[str] = Field(default=None, description="YYYY-MM-DD — used by date_range pattern.")
    date_to: Optional[str] = Field(default=None, description="YYYY-MM-DD — used by date_range pattern.")
    confidence_threshold: float = Field(
        default=0.6,
        description="Upper confidence bound for low_confidence_hard_negatives pattern.",
    )
    max_transactions: int = Field(default=200, description="Maximum number of transaction IDs to return.")
    process_stage_ids: Optional[List[int]] = Field(
        default=None,
        description="ProcessStageID filter applied before pattern logic.",
    )


class ExpandScopeByPatternTool(BaseTool):
    name: str = "expand_scope_by_pattern"
    description: str = (
        "Given a pattern name and optional filters, expand the set of transaction IDs "
        "to include in a rerun. Reads from the evidence store. Returns a JSON object "
        "with expanded_transaction_ids and expansion metadata."
    )
    args_schema: Type[BaseModel] = ExpandScopeByPatternInput

    def _run(
        self,
        evidence_store_path: str,
        pattern_name: str,
        seed_transaction_ids: Optional[List[int]] = None,
        document_type_name: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        confidence_threshold: float = 0.6,
        max_transactions: int = 200,
        process_stage_ids: Optional[List[int]] = None,
    ) -> str:
        try:
            from .excel_reader import ReadDocumentDataTool

            reader = ReadDocumentDataTool()

            # Build reader kwargs
            reader_kwargs: Dict[str, Any] = {"workbook_path": evidence_store_path}
            if process_stage_ids:
                reader_kwargs["process_stage_ids"] = process_stage_ids
            if document_type_name and pattern_name == "specific_doctype":
                reader_kwargs["document_type_names"] = [document_type_name]
            if date_from:
                reader_kwargs["date_from"] = date_from
            if date_to:
                reader_kwargs["date_to"] = date_to
            reader_kwargs["max_rows"] = 10000

            raw = reader._run(**reader_kwargs)
            rows = json.loads(raw)
            if isinstance(rows, dict) and "error" in rows:
                return json.dumps({"error": rows["error"], "tool": "expand_scope_by_pattern"})

            # Seed set always included
            seed_set = set(seed_transaction_ids or [])
            expanded: List[int] = list(seed_set)

            if pattern_name == "low_confidence_hard_negatives":
                for row in rows:
                    tid = row.get("TransactionID")
                    conf = row.get("Confidence")
                    if tid is None:
                        continue
                    try:
                        conf_f = float(conf) if conf not in (None, "") else None
                    except (TypeError, ValueError):
                        conf_f = None
                    if conf_f is not None and conf_f <= confidence_threshold:
                        expanded.append(int(tid))

            elif pattern_name == "specific_doctype":
                if not document_type_name:
                    return json.dumps({
                        "error": "document_type_name is required for specific_doctype pattern",
                        "tool": "expand_scope_by_pattern",
                    })
                for row in rows:
                    tid = row.get("TransactionID")
                    if tid is not None:
                        expanded.append(int(tid))

            elif pattern_name == "date_range":
                # Rows already filtered by date_from / date_to in the reader call
                for row in rows:
                    tid = row.get("TransactionID")
                    if tid is not None:
                        expanded.append(int(tid))

            elif pattern_name == "all_errors":
                # Use ExceptionLogs sheet for error transactions
                from .excel_reader import ReadExceptionLogsTool
                exc_reader = ReadExceptionLogsTool()
                exc_raw = exc_reader._run(workbook_path=evidence_store_path)
                exc_rows = json.loads(exc_raw)
                if isinstance(exc_rows, list):
                    for row in exc_rows:
                        tid = row.get("TransactionID")
                        if tid is not None:
                            expanded.append(int(tid))
                # Also add seed set transactions from main rows
                for row in rows:
                    tid = row.get("TransactionID")
                    if tid is not None and int(tid) in seed_set:
                        expanded.append(int(tid))

            elif pattern_name == "random_sample":
                import random
                all_tids = [int(r["TransactionID"]) for r in rows if r.get("TransactionID") is not None]
                random.shuffle(all_tids)
                expanded.extend(all_tids)

            else:
                return json.dumps({
                    "error": f"Unknown pattern_name '{pattern_name}'. Supported: {SUPPORTED_PATTERNS}",
                    "tool": "expand_scope_by_pattern",
                })

            # Deduplicate, preserve order, cap
            seen = set()
            deduped = []
            for tid in expanded:
                if tid not in seen:
                    seen.add(tid)
                    deduped.append(tid)
            final = deduped[:max_transactions]

            return json.dumps({
                "expanded_transaction_ids": final,
                "total_expanded": len(final),
                "seed_count": len(seed_set),
                "pattern_name": pattern_name,
                "capped_at": max_transactions,
                "was_capped": len(deduped) > max_transactions,
            })
        except Exception as e:
            return json.dumps({"error": str(e), "tool": "expand_scope_by_pattern"})


# ---------------------------------------------------------------------------
# RequestTargetedRerunTool
# ---------------------------------------------------------------------------

class RequestTargetedRerunInput(BaseModel):
    transaction_ids: List[int] = Field(..., description="Transaction IDs to rerun.")
    execution_artifact: Dict[str, Any] = Field(
        ...,
        description=(
            "Execution artifact dict describing the run configuration "
            "(prompt_version, model_name, model_version, process_id, etc.)."
        ),
    )
    rerun_reason: str = Field(default="", description="Human-readable reason for the rerun.")
    priority: str = Field(default="NORMAL", description="NORMAL | HIGH | CRITICAL")
    requested_by: str = Field(default="agentic_testing_system")


class RequestTargetedRerunTool(BaseTool):
    name: str = "request_targeted_rerun"
    description: str = (
        "Simulate a targeted rerun request for the given transaction IDs and execution artifact. "
        "Returns a structured rerun_request dict with a unique rerun_id and timestamp. "
        "In production deployment this would trigger a UiPath orchestrator process."
    )
    args_schema: Type[BaseModel] = RequestTargetedRerunInput

    def _run(
        self,
        transaction_ids: List[int],
        execution_artifact: Dict[str, Any],
        rerun_reason: str = "",
        priority: str = "NORMAL",
        requested_by: str = "agentic_testing_system",
    ) -> str:
        try:
            rerun_id = f"RERUN-{uuid.uuid4().hex[:12].upper()}"
            timestamp = datetime.datetime.utcnow().isoformat() + "Z"

            rerun_request = {
                "rerun_id": rerun_id,
                "timestamp_utc": timestamp,
                "status": "PENDING",
                "priority": priority,
                "requested_by": requested_by,
                "rerun_reason": rerun_reason,
                "transaction_ids": transaction_ids,
                "transaction_count": len(transaction_ids),
                "execution_artifact": execution_artifact,
                "uipath_trigger": {
                    "process_name": execution_artifact.get("process_name", "DocumentAI_Rerun"),
                    "queue_name": execution_artifact.get("queue_name", "RerunQueue"),
                    "input_arguments": {
                        "RerunID": rerun_id,
                        "TransactionIDs": json.dumps(transaction_ids),
                        "ModelVersion": execution_artifact.get("model_version", ""),
                        "PromptVersion": execution_artifact.get("prompt_version", ""),
                    },
                    "note": "Simulated — in production this triggers a UiPath orchestrator job.",
                },
            }

            return json.dumps(rerun_request)
        except Exception as e:
            return json.dumps({"error": str(e), "tool": "request_targeted_rerun"})


# ---------------------------------------------------------------------------
# WritePatchCandidateTool
# ---------------------------------------------------------------------------

class WritePatchCandidateInput(BaseModel):
    workspace_path: str = Field(..., description="Root workspace directory for this run.")
    patch_id: str = Field(..., description="Unique identifier for this patch candidate.")
    patch_data: Dict[str, Any] = Field(
        ...,
        description=(
            "Patch candidate data: affected_doc_types, affected_fields, "
            "root_cause_summary, suggested_prompt_change, confidence, etc."
        ),
    )


class WritePatchCandidateTool(BaseTool):
    name: str = "write_patch_candidate"
    description: str = (
        "Write a patch candidate JSON file to <workspace_path>/patch_candidates/<patch_id>.json. "
        "Creates the directory if needed. Returns JSON with status and written path."
    )
    args_schema: Type[BaseModel] = WritePatchCandidateInput

    def _run(
        self,
        workspace_path: str,
        patch_id: str,
        patch_data: Dict[str, Any],
    ) -> str:
        try:
            patch_dir = os.path.join(workspace_path, "patch_candidates")
            os.makedirs(patch_dir, exist_ok=True)
            file_path = os.path.join(patch_dir, f"{patch_id}.json")

            payload = {
                "patch_id": patch_id,
                "created_at_utc": datetime.datetime.utcnow().isoformat() + "Z",
                **patch_data,
            }

            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, default=str)

            return json.dumps({"status": "ok", "patch_id": patch_id, "path": file_path})
        except Exception as e:
            return json.dumps({"error": str(e), "tool": "write_patch_candidate"})


# ---------------------------------------------------------------------------
# Convenience instances
# ---------------------------------------------------------------------------
expand_scope_by_pattern = ExpandScopeByPatternTool()
request_targeted_rerun = RequestTargetedRerunTool()
write_patch_candidate = WritePatchCandidateTool()
