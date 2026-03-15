"""
Logging tools — append audit events and trace rows.
These write to the AgenticTesting_AuditLog.xlsx and ai.ModelData trace.
"""
import datetime
import json
import os
import uuid
from typing import Any, Dict, List, Optional, Type
from crewai.tools import BaseTool
from pydantic import BaseModel, Field


def _ts() -> str:
    return datetime.datetime.utcnow().isoformat()


class LogAgentEventInput(BaseModel):
    audit_log_path: str
    run_id: str
    agent_name: str
    event_type: str = Field(..., description="START | COMPLETE | ERROR | SCOPE_CHANGE | RERUN_REQUEST")
    summary: str
    duration_seconds: float = 0.0
    input_ref: str = ""
    output_ref: str = ""
    status: str = "OK"


class LogAgentEventTool(BaseTool):
    name: str = "log_agent_event"
    description: str = "Append an agent event row to the AgentEvents sheet of the audit log workbook."
    args_schema: Type[BaseModel] = LogAgentEventInput

    def _run(
        self,
        audit_log_path: str,
        run_id: str,
        agent_name: str,
        event_type: str,
        summary: str,
        duration_seconds: float = 0.0,
        input_ref: str = "",
        output_ref: str = "",
        status: str = "OK",
    ) -> str:
        try:
            from .excel_writer import append_rows
            row = {
                "RunID": run_id,
                "EventID": str(uuid.uuid4())[:8],
                "AgentName": agent_name,
                "EventType": event_type,
                "Timestamp": _ts(),
                "DurationSeconds": round(duration_seconds, 2),
                "InputRef": input_ref,
                "OutputRef": output_ref,
                "Summary": summary,
                "Status": status,
            }
            result = append_rows._run(workbook_path=audit_log_path, sheet_name="AgentEvents", rows=[row])
            return result
        except Exception as e:
            return json.dumps({"error": str(e), "tool": "log_agent_event"})


class LogToolCallInput(BaseModel):
    audit_log_path: str
    run_id: str
    agent_name: str
    tool_name: str
    input_summary: str
    rows_read: int = 0
    rows_written: int = 0
    duration_seconds: float = 0.0
    status: str = "OK"
    notes: str = ""


class LogToolCallTool(BaseTool):
    name: str = "log_tool_call"
    description: str = "Append a tool call row to the ToolCalls sheet of the audit log workbook."
    args_schema: Type[BaseModel] = LogToolCallInput

    def _run(
        self,
        audit_log_path: str,
        run_id: str,
        agent_name: str,
        tool_name: str,
        input_summary: str,
        rows_read: int = 0,
        rows_written: int = 0,
        duration_seconds: float = 0.0,
        status: str = "OK",
        notes: str = "",
    ) -> str:
        try:
            from .excel_writer import append_rows
            row = {
                "RunID": run_id,
                "ToolCallID": str(uuid.uuid4())[:8],
                "AgentName": agent_name,
                "ToolName": tool_name,
                "Timestamp": _ts(),
                "InputSummary": input_summary,
                "RowsRead": rows_read,
                "RowsWritten": rows_written,
                "DurationSeconds": round(duration_seconds, 2),
                "Status": status,
                "Notes": notes,
            }
            from .excel_writer import append_rows
            result = append_rows._run(workbook_path=audit_log_path, sheet_name="ToolCalls", rows=[row])
            return result
        except Exception as e:
            return json.dumps({"error": str(e), "tool": "log_tool_call"})


class LogWarningInput(BaseModel):
    audit_log_path: str
    run_id: str
    source: str
    severity: str = Field(default="WARNING", description="INFO | WARNING | ERROR | CRITICAL")
    message: str
    related_transaction_id: Optional[int] = None
    related_agent: str = ""


class LogWarningTool(BaseTool):
    name: str = "log_warning"
    description: str = "Append a warning or error row to the WarningsAndErrors sheet of the audit log workbook."
    args_schema: Type[BaseModel] = LogWarningInput

    def _run(
        self,
        audit_log_path: str,
        run_id: str,
        source: str,
        severity: str = "WARNING",
        message: str = "",
        related_transaction_id: Optional[int] = None,
        related_agent: str = "",
    ) -> str:
        try:
            from .excel_writer import append_rows
            row = {
                "RunID": run_id,
                "Timestamp": _ts(),
                "Source": source,
                "Severity": severity,
                "Message": message,
                "RelatedTransactionID": related_transaction_id or "",
                "RelatedAgent": related_agent,
            }
            result = append_rows._run(workbook_path=audit_log_path, sheet_name="WarningsAndErrors", rows=[row])
            return result
        except Exception as e:
            return json.dumps({"error": str(e), "tool": "log_warning"})


class WriteModelDataTraceInput(BaseModel):
    workbook_path: str = Field(..., description="Path to evidence store workbook for appending model data trace")
    transaction_id: int
    model_stage_id: int = Field(..., description="1=Input, 2=Output")
    model_type_id: int = Field(..., description="1=LLM, 2=Agent")
    model_name_id: int = Field(..., description="9001-9010 for agents")
    model_version: str
    in_argument_field: str
    in_argument_value: str


class WriteModelDataTraceTool(BaseTool):
    name: str = "write_model_data_trace"
    description: str = "Append a trace row to the ai.ModelData sheet. Used for auditability of agent inputs/outputs."
    args_schema: Type[BaseModel] = WriteModelDataTraceInput

    def _run(
        self,
        workbook_path: str,
        transaction_id: int,
        model_stage_id: int,
        model_type_id: int,
        model_name_id: int,
        model_version: str,
        in_argument_field: str,
        in_argument_value: str,
    ) -> str:
        try:
            from .excel_writer import append_rows
            row = {
                "TransactionID": transaction_id,
                "ModelStageID": model_stage_id,
                "ModelTypeID": model_type_id,
                "ModelNameID": model_name_id,
                "ModelVersion": model_version,
                "In_Argument_Field": in_argument_field,
                "In_Argument_Value": in_argument_value[:2000] if in_argument_value else "",
                "RecordDateTime": _ts(),
                "Active": 1,
            }
            result = append_rows._run(workbook_path=workbook_path, sheet_name="ai.ModelData", rows=[row])
            return result
        except Exception as e:
            return json.dumps({"error": str(e), "tool": "write_model_data_trace"})


log_agent_event = LogAgentEventTool()
log_tool_call = LogToolCallTool()
log_warning = LogWarningTool()
write_model_data_trace = WriteModelDataTraceTool()
