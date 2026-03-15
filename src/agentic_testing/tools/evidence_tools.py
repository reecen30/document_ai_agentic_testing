"""
Evidence assembly tools — build per-transaction case bundles from raw evidence rows.
"""
import json
from typing import Any, Dict, List, Optional, Type
import pandas as pd
from crewai.tools import BaseTool
from pydantic import BaseModel, Field

# ProcessStageID constants
STAGE_BASELINE_CLASSIFY = 1
STAGE_TRUTH_CLASSIFY = 2
STAGE_BASELINE_EXTRACT = 3
STAGE_TRUTH_EXTRACT = 4


class BuildCaseBundleInput(BaseModel):
    transaction_id: int
    document_data_rows: List[Dict[str, Any]] = Field(..., description="All DocumentData rows for this transaction")
    exception_rows: List[Dict[str, Any]] = Field(default_factory=list)
    api_rows: List[Dict[str, Any]] = Field(default_factory=list)
    candidate_rows: List[Dict[str, Any]] = Field(default_factory=list, description="Candidate prediction rows (same schema as DocumentData)")


class BuildCaseBundleTool(BaseTool):
    name: str = "build_case_bundle"
    description: str = (
        "Build a structured per-transaction case bundle from raw DocumentData rows. "
        "Separates baseline (stage 1/3), truth (stage 2/4), and candidate rows. "
        "Returns a JSON object with classification and extraction evidence."
    )
    args_schema: Type[BaseModel] = BuildCaseBundleInput

    def _run(
        self,
        transaction_id: int,
        document_data_rows: List[Dict[str, Any]],
        exception_rows: List[Dict[str, Any]] = None,
        api_rows: List[Dict[str, Any]] = None,
        candidate_rows: List[Dict[str, Any]] = None,
    ) -> str:
        exception_rows = exception_rows or []
        api_rows = api_rows or []
        candidate_rows = candidate_rows or []
        try:
            rows = [r for r in document_data_rows if int(r.get("TransactionID", 0)) == transaction_id]

            def get_rows_by_stage(stage_id):
                return [r for r in rows if int(r.get("ProcessStageID", 0)) == stage_id]

            baseline_classify = get_rows_by_stage(STAGE_BASELINE_CLASSIFY)
            truth_classify = get_rows_by_stage(STAGE_TRUTH_CLASSIFY)
            baseline_extract = get_rows_by_stage(STAGE_BASELINE_EXTRACT)
            truth_extract = get_rows_by_stage(STAGE_TRUTH_EXTRACT)

            def first_val(stage_rows, field, default=None):
                return stage_rows[0].get(field, default) if stage_rows else default

            bundle = {
                "transaction_id": transaction_id,
                "document_id": first_val(rows, "DocumentID", ""),
                # Classification
                "doc_type_baseline": first_val(baseline_classify, "DocumentTypeName"),
                "doc_type_truth": first_val(truth_classify, "DocumentTypeName"),
                "doc_type_candidate": first_val(
                    [r for r in candidate_rows if int(r.get("TransactionID", 0)) == transaction_id and int(r.get("ProcessStageID", 0)) == STAGE_BASELINE_CLASSIFY],
                    "DocumentTypeName"
                ),
                "classification_confidence_baseline": first_val(baseline_classify, "Confidence"),
                "classification_confidence_candidate": first_val(
                    [r for r in candidate_rows if int(r.get("TransactionID", 0)) == transaction_id],
                    "Confidence"
                ),
                # Extraction
                "fields_baseline": [
                    {"field": r.get("Field"), "value": r.get("Value"), "is_missing": r.get("IsMissing", 0), "confidence": r.get("FieldConfidence")}
                    for r in baseline_extract
                ],
                "fields_truth": [
                    {"field": r.get("Field"), "value": r.get("Value"), "is_missing": r.get("IsMissing", 0), "confidence": r.get("FieldConfidence")}
                    for r in truth_extract
                ],
                "fields_candidate": [
                    {"field": r.get("Field"), "value": r.get("Value"), "is_missing": r.get("IsMissing", 0), "confidence": r.get("FieldConfidence")}
                    for r in [r for r in candidate_rows if int(r.get("TransactionID", 0)) == transaction_id and int(r.get("ProcessStageID", 0)) == STAGE_BASELINE_EXTRACT]
                ],
                # Exceptions and API
                "exceptions": [r for r in exception_rows if int(r.get("TransactionID", 0)) == transaction_id],
                "api_calls": [r for r in api_rows if int(r.get("TransactionID", 0)) == transaction_id],
                # Raw counts
                "raw_row_counts": {
                    "baseline_classify": len(baseline_classify),
                    "truth_classify": len(truth_classify),
                    "baseline_extract": len(baseline_extract),
                    "truth_extract": len(truth_extract),
                    "candidate": len([r for r in candidate_rows if int(r.get("TransactionID", 0)) == transaction_id]),
                    "exceptions": len([r for r in exception_rows if int(r.get("TransactionID", 0)) == transaction_id]),
                }
            }
            return json.dumps(bundle)
        except Exception as e:
            return json.dumps({"error": str(e), "transaction_id": transaction_id, "tool": "build_case_bundle"})


class SummarizeEvidenceInput(BaseModel):
    case_bundles: List[Dict[str, Any]]


class SummarizeEvidenceTool(BaseTool):
    name: str = "summarize_evidence"
    description: str = "Summarize a list of case bundles: counts, doc type distribution, data quality notes. Returns JSON."
    args_schema: Type[BaseModel] = SummarizeEvidenceInput

    def _run(self, case_bundles: List[Dict[str, Any]]) -> str:
        try:
            doc_type_dist = {}
            missing_truth = 0
            missing_candidate = 0
            for b in case_bundles:
                dt = b.get("doc_type_truth") or b.get("doc_type_baseline") or "Unknown"
                doc_type_dist[dt] = doc_type_dist.get(dt, 0) + 1
                if not b.get("doc_type_truth"):
                    missing_truth += 1
                if not b.get("doc_type_candidate") and not b.get("fields_candidate"):
                    missing_candidate += 1

            summary = {
                "total_transactions": len(case_bundles),
                "doc_type_distribution": doc_type_dist,
                "missing_truth_count": missing_truth,
                "missing_candidate_count": missing_candidate,
                "evidence_quality_note": (
                    "POOR - many missing truth labels" if missing_truth > len(case_bundles) * 0.3
                    else "ACCEPTABLE" if missing_truth == 0 and missing_candidate == 0
                    else "PARTIAL"
                ),
            }
            return json.dumps(summary)
        except Exception as e:
            return json.dumps({"error": str(e), "tool": "summarize_evidence"})


build_case_bundle = BuildCaseBundleTool()
summarize_evidence = SummarizeEvidenceTool()
