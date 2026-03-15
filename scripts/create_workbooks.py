"""
create_workbooks.py

Run this script once to set up the three Excel workbooks:
  1. DocumentAI_EvidenceStore.xlsx  — source evidence (with mock data)
  2. AgenticTesting_AuditLog.xlsx   — empty audit log (pre-structured sheets)
  3. Run_TEMPLATE_Report.xlsx       — empty run report template

Usage:
    python scripts/create_workbooks.py [--output-dir ./data]
"""

import argparse
import os
from datetime import datetime
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _write_sheet(wb: Workbook, name: str, headers: list, rows: list = None) -> None:
    """
    Create a worksheet with styled headers and optional data rows.

    - Headers: row 1, blue background (#1F4E79), white bold font, centered.
    - Auto-fits column widths based on the max content length in each column.
    """
    ws = wb.create_sheet(title=name)

    header_fill = PatternFill(start_color="1F4E79", end_color="1F4E79", fill_type="solid")
    header_font = Font(color="FFFFFF", bold=True, name="Calibri", size=11)
    header_align = Alignment(horizontal="center", vertical="center", wrap_text=False)

    # Write headers
    for col_idx, header in enumerate(headers, start=1):
        cell = ws.cell(row=1, column=col_idx, value=header)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = header_align

    # Write data rows
    if rows:
        for row_idx, row_data in enumerate(rows, start=2):
            for col_idx, value in enumerate(row_data, start=1):
                ws.cell(row=row_idx, column=col_idx, value=value)

    # Auto-fit column widths
    col_widths = [len(str(h)) for h in headers]
    if rows:
        for row_data in rows:
            for col_idx, value in enumerate(row_data):
                col_widths[col_idx] = max(col_widths[col_idx], len(str(value)) if value is not None else 0)

    for col_idx, width in enumerate(col_widths, start=1):
        # Add a small buffer and cap at 60
        adjusted = min(width + 4, 60)
        ws.column_dimensions[get_column_letter(col_idx)].width = adjusted

    # Freeze the header row
    ws.freeze_panes = ws["A2"]


# ---------------------------------------------------------------------------
# Workbook 1 — DocumentAI_EvidenceStore.xlsx
# ---------------------------------------------------------------------------

def _create_evidence_store(output_dir: str) -> str:
    wb = Workbook()
    # Remove default sheet
    wb.remove(wb.active)

    # --- DocumentTypes ---
    _write_sheet(
        wb,
        "DocumentTypes",
        headers=["DocumentTypeID", "DocumentType"],
        rows=[
            (1, "ApplicationForm"),
            (2, "Resolution"),
            (3, "Windeed"),
            (4, "Passport"),
            (5, "IdentityDocument"),
            (6, "ProductFormsBTB"),
            (7, "ProductFormsIFB"),
            (8, "ProductFormsICIB"),
            (9, "Income_Statement"),
            (10, "Balance_Sheet"),
            (11, "CashFlow"),
            (12, "Debtors"),
            (13, "Creditors"),
            (14, "AFS"),
            (15, "Other"),
            (16, "RelatedPartyForm"),
        ],
    )

    # --- ProcessStages ---
    _write_sheet(
        wb,
        "ProcessStages",
        headers=["ProcessStageID", "ProcessStageName"],
        rows=[
            (1, "Pre Classify"),
            (2, "Validated Post Classified"),
            (3, "Pre Extract"),
            (4, "Validated Post Extracted"),
        ],
    )

    # --- ai.ModelStages ---
    _write_sheet(
        wb,
        "ai.ModelStages",
        headers=["ModelStageID", "ModelStageName"],
        rows=[
            (1, "Input"),
            (2, "Output"),
        ],
    )

    # --- ai.ModelTypes ---
    _write_sheet(
        wb,
        "ai.ModelTypes",
        headers=["ModelTypeID", "ModelTypeName"],
        rows=[
            (1, "LLM"),
            (2, "Agent"),
        ],
    )

    # --- ai.ModelNames ---
    _write_sheet(
        wb,
        "ai.ModelNames",
        headers=["ModelNameID", "ModelName"],
        rows=[
            (9001, "Agentic_IntakeDiff"),
            (9002, "Agentic_ScopePlanner"),
            (9003, "Agentic_EvidenceCollector"),
            (9004, "Agentic_RegressionHunter"),
            (9005, "Agentic_Challenger"),
            (9006, "Agentic_TargetedRerun"),
            (9007, "Agentic_TrendDrift"),
            (9008, "Agentic_RootCause"),
            (9009, "Agentic_PatchProposal"),
            (9010, "Agentic_ReportRouting"),
        ],
    )

    # --- DocumentData ---
    doc_data_headers = [
        "DocumentDataID", "TransactionID", "DocumentID", "ProcessStageID",
        "DocumentTypeID", "DocumentTypeName", "StartPage", "Confidence",
        "OcrConfidence", "Field", "IsMissing", "Value",
        "FieldConfidence", "FieldOcrConfidence", "Created_By",
        "CreatedDateTime", "Active",
    ]

    doc_data_rows = [
        # ---------------------------------------------------------------
        # Scenario 1: TXN 1001 — stable gold (IdentityDocument correct)
        # ---------------------------------------------------------------
        (1, 1001, "1001_pack", 1, 5, "IdentityDocument", 1, 0.91, 0.98,
         "DocumentType", 0, "IdentityDocument", 0.91, 0.98, "system",
         "2026-03-14 10:00:00", 1),
        (2, 1001, "1001_pack", 2, 5, "IdentityDocument", 1, 1.00, 0.98,
         "DocumentType", 0, "IdentityDocument", 1.00, 0.98, "validator",
         "2026-03-14 10:05:00", 1),
        (3, 1001, "1001_pack", 3, 5, "IdentityDocument", 1, 0.89, 0.98,
         "IdentityNumber", 0, "8001015009087", 0.89, 0.98, "system",
         "2026-03-14 10:00:00", 1),
        (4, 1001, "1001_pack", 4, 5, "IdentityDocument", 1, 1.00, 0.98,
         "IdentityNumber", 0, "8001015009087", 1.00, 0.98, "validator",
         "2026-03-14 10:05:00", 1),

        # ---------------------------------------------------------------
        # Scenario 2: TXN 1002 — ID/Passport confusion
        # Baseline classifies as Passport; truth is IdentityDocument
        # ---------------------------------------------------------------
        (5, 1002, "1002_pack", 1, 4, "Passport", 1, 0.83, 0.97,
         "DocumentType", 0, "Passport", 0.83, 0.97, "system",
         "2026-03-14 10:00:00", 1),
        (6, 1002, "1002_pack", 2, 5, "IdentityDocument", 1, 1.00, 0.97,
         "DocumentType", 0, "IdentityDocument", 1.00, 0.97, "validator",
         "2026-03-14 10:05:00", 1),
        (7, 1002, "1002_pack", 3, 4, "Passport", 1, 0.72, 0.97,
         "PassportNumber", 0, "A1234567", 0.72, 0.97, "system",
         "2026-03-14 10:00:00", 1),
        (8, 1002, "1002_pack", 4, 5, "IdentityDocument", 1, 1.00, 0.97,
         "IdentityNumber", 0, "9002026009088", 1.00, 0.97, "validator",
         "2026-03-14 10:05:00", 1),

        # ---------------------------------------------------------------
        # Scenario 3: TXN 1003 — out-of-scope (both agree: Other)
        # ---------------------------------------------------------------
        (9, 1003, "1003_pack", 1, 15, "Other", 1, 0.88, 0.95,
         "DocumentType", 0, "Other", 0.88, 0.95, "system",
         "2026-03-14 10:00:00", 1),
        (10, 1003, "1003_pack", 2, 15, "Other", 1, 1.00, 0.95,
         "DocumentType", 0, "Other", 1.00, 0.95, "validator",
         "2026-03-14 10:05:00", 1),
        (11, 1003, "1003_pack", 3, 15, "Other", 1, 0.81, 0.95,
         "Comment", 0, "Out of scope brochure", 0.81, 0.95, "system",
         "2026-03-14 10:00:00", 1),
        (12, 1003, "1003_pack", 4, 15, "Other", 1, 1.00, 0.95,
         "Comment", 0, "Out of scope brochure", 1.00, 0.95, "validator",
         "2026-03-14 10:05:00", 1),

        # ---------------------------------------------------------------
        # Scenario 4: TXN 1004 — extraction completeness issue
        # Baseline has a missing field (EntityName)
        # ---------------------------------------------------------------
        (13, 1004, "1004_pack", 1, 1, "ApplicationForm", 1, 0.92, 0.96,
         "DocumentType", 0, "ApplicationForm", 0.92, 0.96, "system",
         "2026-03-14 10:00:00", 1),
        (14, 1004, "1004_pack", 2, 1, "ApplicationForm", 1, 1.00, 0.96,
         "DocumentType", 0, "ApplicationForm", 1.00, 0.96, "validator",
         "2026-03-14 10:05:00", 1),
        (15, 1004, "1004_pack", 3, 1, "ApplicationForm", 1, 0.00, 0.96,
         "EntityName", 1, "", 0.00, 0.96, "system",
         "2026-03-14 10:00:00", 1),
        (16, 1004, "1004_pack", 4, 1, "ApplicationForm", 1, 1.00, 0.96,
         "EntityName", 0, "Acme Holdings Ltd", 1.00, 0.96, "validator",
         "2026-03-14 10:05:00", 1),

        # ---------------------------------------------------------------
        # Scenario 5: TXN 1005 — high confidence wrong answer
        # Baseline confident but wrong (Resolution vs ApplicationForm)
        # ---------------------------------------------------------------
        (17, 1005, "1005_pack", 1, 2, "Resolution", 1, 0.94, 0.97,
         "DocumentType", 0, "Resolution", 0.94, 0.97, "system",
         "2026-03-14 10:00:00", 1),
        (18, 1005, "1005_pack", 2, 1, "ApplicationForm", 1, 1.00, 0.97,
         "DocumentType", 0, "ApplicationForm", 1.00, 0.97, "validator",
         "2026-03-14 10:05:00", 1),
        (19, 1005, "1005_pack", 3, 2, "Resolution", 1, 0.91, 0.97,
         "ResolutionDate", 0, "2026-01-15", 0.91, 0.97, "system",
         "2026-03-14 10:00:00", 1),
        (20, 1005, "1005_pack", 4, 1, "ApplicationForm", 1, 1.00, 0.97,
         "ApplicationDate", 0, "2026-01-15", 1.00, 0.97, "validator",
         "2026-03-14 10:05:00", 1),
    ]

    _write_sheet(wb, "DocumentData", headers=doc_data_headers, rows=doc_data_rows)

    # --- ai.ModelData ---
    model_data_headers = [
        "ModelDataID", "TransactionID", "ModelStageID", "ModelTypeID",
        "ModelNameID", "ModelVersion", "In_Argument_Field",
        "In_Argument_Value", "RecordDateTime", "Active",
    ]

    model_data_rows = [
        (1, 1001, 1, 2, 9001, "bundle_v17", "run_request_json",
         '{"run_id":"RUN-2026-03-14-001"}', "2026-03-14 10:00:00", 1),
        (2, 1001, 2, 2, 9001, "bundle_v17", "change_summary_json",
         '{"prompt_changed":true}', "2026-03-14 10:00:02", 1),
        (3, 1001, 2, 2, 9002, "bundle_v17", "selected_transaction_ids_json",
         "[1001,1002,1003,1004,1005]", "2026-03-14 10:00:04", 1),
        (4, 1001, 2, 2, 9004, "bundle_v17", "regression_findings_json",
         '{"count":2}', "2026-03-14 10:00:06", 1),
        (5, 1001, 2, 2, 9008, "bundle_v17", "root_causes_json",
         '{"primary":"prompt broadened"}', "2026-03-14 10:00:08", 1),
        (6, 1001, 2, 2, 9010, "bundle_v17", "final_run_packet_json",
         '{"verdict":"WARN"}', "2026-03-14 10:00:10", 1),
    ]

    _write_sheet(wb, "ai.ModelData", headers=model_data_headers, rows=model_data_rows)

    # --- ExceptionLogs (headers only) ---
    _write_sheet(
        wb,
        "ExceptionLogs",
        headers=[
            "ExceptionLogID", "TransactionID", "ExceptionType",
            "ExceptionMessage", "ExceptionDateTime",
            "RelatedProcessStageID", "Active",
        ],
    )

    # --- api.APIData (headers only) ---
    _write_sheet(
        wb,
        "api.APIData",
        headers=[
            "APIDataID", "TransactionID", "APIName", "StatusCode",
            "RequestDateTime", "ResponseDateTime", "ResponseTimeMs", "Active",
        ],
    )

    path = os.path.join(output_dir, "DocumentAI_EvidenceStore.xlsx")
    wb.save(path)
    print(f"  Created: {path}")
    return path


# ---------------------------------------------------------------------------
# Workbook 2 — AgenticTesting_AuditLog.xlsx
# ---------------------------------------------------------------------------

def _create_audit_log(output_dir: str) -> str:
    wb = Workbook()
    wb.remove(wb.active)

    _write_sheet(
        wb,
        "RunRegistry",
        headers=[
            "RunID", "ProcessName", "RunMode", "StartDateTime", "EndDateTime",
            "Status", "Verdict", "Confidence", "TransactionsAnalyzed",
            "InitialTransactionCount", "FinalTransactionCount",
            "PromptVersionLabel_Old", "PromptVersionLabel_New",
            "Model_Old", "Model_New", "WorkspaceKey", "TriggeredBy", "Notes",
        ],
    )

    _write_sheet(
        wb,
        "MaestroInput",
        headers=[
            "RunID", "ReceivedDateTime", "InputSection",
            "FieldName", "FieldValue", "ValueType",
        ],
    )

    _write_sheet(
        wb,
        "AgentEvents",
        headers=[
            "RunID", "EventID", "AgentName", "EventType", "Timestamp",
            "DurationSeconds", "InputRef", "OutputRef", "Summary", "Status",
        ],
    )

    _write_sheet(
        wb,
        "ToolCalls",
        headers=[
            "RunID", "ToolCallID", "AgentName", "ToolName", "Timestamp",
            "InputSummary", "RowsRead", "RowsWritten",
            "DurationSeconds", "Status", "Notes",
        ],
    )

    _write_sheet(
        wb,
        "ScopeChanges",
        headers=[
            "RunID", "Timestamp", "Reason",
            "OldScope", "NewScope", "RequestedByAgent",
        ],
    )

    _write_sheet(
        wb,
        "RerunRequests",
        headers=[
            "RunID", "Timestamp", "RequestedByAgent",
            "PatternName", "TransactionIDs", "Reason", "Status",
        ],
    )

    _write_sheet(
        wb,
        "WarningsAndErrors",
        headers=[
            "RunID", "Timestamp", "Source", "Severity",
            "Message", "RelatedTransactionID", "RelatedAgent",
        ],
    )

    _write_sheet(
        wb,
        "OutputArtifacts",
        headers=[
            "RunID", "Timestamp", "ArtifactType",
            "ArtifactURI", "CreatedByAgent", "Status",
        ],
    )

    path = os.path.join(output_dir, "AgenticTesting_AuditLog.xlsx")
    wb.save(path)
    print(f"  Created: {path}")
    return path


# ---------------------------------------------------------------------------
# Workbook 3 — Run_TEMPLATE_Report.xlsx
# ---------------------------------------------------------------------------

def _create_run_template_report(output_dir: str) -> str:
    wb = Workbook()
    wb.remove(wb.active)

    _write_sheet(
        wb,
        "RunSummary",
        headers=[
            "RunID", "StartDateTime", "EndDateTime", "RunMode",
            "Verdict", "Confidence", "TransactionsAnalyzed",
            "PromptVersionOld", "PromptVersionNew",
            "ModelOld", "ModelNew",
        ],
    )

    _write_sheet(
        wb,
        "Scope",
        headers=[
            "RunID", "DateFrom", "DateTo",
            "InitialTransactionCount", "FinalTransactionCount",
            "InitialDocTypes", "ExpandedScope", "ExpansionReason",
        ],
    )

    _write_sheet(
        wb,
        "TransactionsAnalyzed",
        headers=[
            "RunID", "TransactionID", "DocumentID",
            "DocTypeTruth", "DocTypeBaseline", "DocTypeCandidate",
            "ClassificationStatus", "ExtractionStatus",
            "ExceptionPresent", "APIImpactPresent",
        ],
    )

    _write_sheet(
        wb,
        "ClassificationDeltas",
        headers=[
            "RunID", "TransactionID", "DocumentTypeName",
            "BaselineCorrect", "CandidateCorrect", "Changed",
            "ConfidenceBaseline", "ConfidenceCandidate", "Notes",
        ],
    )

    _write_sheet(
        wb,
        "ExtractionDeltas",
        headers=[
            "RunID", "TransactionID", "Field",
            "BaselineValue", "CandidateValue", "TruthValue",
            "BaselineMatch", "CandidateMatch",
            "IsMissingBaseline", "IsMissingCandidate",
        ],
    )

    _write_sheet(
        wb,
        "MissingFieldAnalysis",
        headers=[
            "RunID", "Field", "DocumentTypeName",
            "BaselineMissingRate", "CandidateMissingRate",
            "Delta", "RiskLevel",
        ],
    )

    _write_sheet(
        wb,
        "ExceptionCorrelation",
        headers=[
            "RunID", "TransactionID", "ExceptionType",
            "ExceptionMessage", "RelatedModelFinding", "APIStatusCode",
        ],
    )

    _write_sheet(
        wb,
        "PatchCandidates",
        headers=[
            "RunID", "PatchID", "PatchType", "Target",
            "Description", "Confidence", "RequiresHumanApproval",
            "RecommendedExperiment",
        ],
    )

    _write_sheet(
        wb,
        "FinalRouting",
        headers=[
            "RunID", "BlockRelease", "RequestHumanReview",
            "OpenDefect", "NotifyRoles",
            "ArtifactPDF", "ArtifactHTML", "ArtifactJSON",
        ],
    )

    path = os.path.join(output_dir, "Run_TEMPLATE_Report.xlsx")
    wb.save(path)
    print(f"  Created: {path}")
    return path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create all three Excel workbooks for Document AI Agentic Testing."
    )
    parser.add_argument(
        "--output-dir",
        default="./data",
        metavar="DIR",
        help="Directory to write workbooks into (default: ./data)",
    )
    args = parser.parse_args()

    output_dir = os.path.abspath(args.output_dir)
    os.makedirs(output_dir, exist_ok=True)

    print(f"\nCreating workbooks in: {output_dir}\n")

    _create_evidence_store(output_dir)
    _create_audit_log(output_dir)
    _create_run_template_report(output_dir)

    print("\nDone. All workbooks created successfully.")


if __name__ == "__main__":
    main()
