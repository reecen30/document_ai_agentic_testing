"""
agentic_testing.tools — CrewAI BaseTool implementations for Document AI testing.
"""
from .excel_reader import (
    ReadDocumentDataTool,
    ReadModelDataTool,
    ReadExceptionLogsTool,
    ReadApiDataTool,
    ReadLookupSheetTool,
    read_document_data,
    read_model_data,
    read_exception_logs,
    read_api_data,
    read_lookup_sheet,
)
from .excel_writer import (
    WriteSheetTool,
    AppendRowsTool,
    WriteJsonFileTool,
    write_sheet,
    append_rows,
    write_json_file,
)
from .evidence_tools import (
    BuildCaseBundleTool,
    SummarizeEvidenceTool,
    build_case_bundle,
    summarize_evidence,
)
from .metrics_tools import (
    CompareBaselineToTruthTool,
    CompareCandidateToTruthTool,
    CalculateDocTypeMetricsTool,
    CalculateFieldMetricsTool,
    DetectMissingFieldSpikesTool,
    DetectConfidenceMismatchTool,
    compare_baseline_to_truth,
    compare_candidate_to_truth,
    calculate_doc_type_metrics,
    calculate_field_metrics,
    detect_missing_field_spikes,
    detect_confidence_mismatch,
)
from .diff_tools import (
    DiffPromptArtifactsTool,
    CompareModelChangeTool,
    diff_prompt_artifacts,
    compare_model_change,
)
from .rerun_tools import (
    ExpandScopeByPatternTool,
    RequestTargetedRerunTool,
    WritePatchCandidateTool,
    expand_scope_by_pattern,
    request_targeted_rerun,
    write_patch_candidate,
)
from .reporting_tools import (
    WriteHtmlReportTool,
    WriteTracePackTool,
    WriteFinalPacketTool,
    WriteAuditLogEventTool,
    write_html_report,
    write_trace_pack,
    write_final_packet,
    write_audit_log_event,
)
from .logging_tools import (
    LogAgentEventTool,
    LogToolCallTool,
    LogWarningTool,
    WriteModelDataTraceTool,
    log_agent_event,
    log_tool_call,
    log_warning,
    write_model_data_trace,
)

__all__ = [
    # excel_reader
    "ReadDocumentDataTool", "ReadModelDataTool", "ReadExceptionLogsTool",
    "ReadApiDataTool", "ReadLookupSheetTool",
    "read_document_data", "read_model_data", "read_exception_logs",
    "read_api_data", "read_lookup_sheet",
    # excel_writer
    "WriteSheetTool", "AppendRowsTool", "WriteJsonFileTool",
    "write_sheet", "append_rows", "write_json_file",
    # evidence_tools
    "BuildCaseBundleTool", "SummarizeEvidenceTool",
    "build_case_bundle", "summarize_evidence",
    # metrics_tools
    "CompareBaselineToTruthTool", "CompareCandidateToTruthTool",
    "CalculateDocTypeMetricsTool", "CalculateFieldMetricsTool",
    "DetectMissingFieldSpikesTool", "DetectConfidenceMismatchTool",
    "compare_baseline_to_truth", "compare_candidate_to_truth",
    "calculate_doc_type_metrics", "calculate_field_metrics",
    "detect_missing_field_spikes", "detect_confidence_mismatch",
    # diff_tools
    "DiffPromptArtifactsTool", "CompareModelChangeTool",
    "diff_prompt_artifacts", "compare_model_change",
    # rerun_tools
    "ExpandScopeByPatternTool", "RequestTargetedRerunTool", "WritePatchCandidateTool",
    "expand_scope_by_pattern", "request_targeted_rerun", "write_patch_candidate",
    # reporting_tools
    "WriteHtmlReportTool", "WriteTracePackTool", "WriteFinalPacketTool", "WriteAuditLogEventTool",
    "write_html_report", "write_trace_pack", "write_final_packet", "write_audit_log_event",
    # logging_tools
    "LogAgentEventTool", "LogToolCallTool", "LogWarningTool", "WriteModelDataTraceTool",
    "log_agent_event", "log_tool_call", "log_warning", "write_model_data_trace",
]
