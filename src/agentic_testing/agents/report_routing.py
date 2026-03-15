"""
agents/report_routing.py

ReportRouting Agent - produces final packet and writes demo-friendly artifacts.
"""

import json
import os
import uuid
from collections.abc import Mapping, Sequence
from typing import Any, Dict, List, Optional

from crewai import Agent, Crew, LLM, Task
from pydantic import BaseModel, Field, ValidationError

from agentic_testing.agent_mode import use_deterministic_mode
from agentic_testing.llm_factory import get_agent_llm
from agentic_testing.runtime_logging import get_runtime_logger, log_event
from agentic_testing.tools.excel_writer import write_sheet
from agentic_testing.tools.reporting_tools import (
    write_audit_log_event,
    write_execution_visual,
    write_final_packet,
    write_html_report,
    write_pdf_report,
    write_trace_pack,
)

LOGGER = get_runtime_logger("report_routing")


def get_reasoning_llm() -> LLM:
    return get_agent_llm("reasoning")


def get_structured_llm() -> LLM:
    return get_agent_llm("structured")


class RoutingDecision(BaseModel):
    block_release: bool = Field(...)
    request_human_review: bool = Field(...)
    open_defect: bool = Field(...)
    notify_roles: List[str] = Field(default_factory=list)
    verdict: str = Field(...)
    verdict_rationale: str = Field(...)


class ArtifactURIs(BaseModel):
    report_pdf_uri: str = Field(default="")
    report_html_uri: str = Field(default="")
    execution_visual_uri: str = Field(default="")
    run_json_uri: str = Field(default="")
    excel_log_uri: str = Field(default="")
    audit_log_uri: str = Field(default="")
    trace_pack_uri: str = Field(default="")


class AnalysisScope(BaseModel):
    transaction_ids: List[int] = Field(default_factory=list)
    doc_types: List[str] = Field(default_factory=list)
    date_from: str = Field(default="")
    date_to: str = Field(default="")
    total_transactions: int = Field(default=0)


class FinalRoutingOutput(BaseModel):
    run_id: str
    status: str
    verdict: str
    confidence: float = Field(..., ge=0.0, le=1.0)
    analysis_scope: AnalysisScope
    change_summary: Dict[str, Any] = Field(default_factory=dict)
    summary_metrics: Dict[str, Any] = Field(default_factory=dict)
    doc_type_breakdown: Dict[str, Any] = Field(default_factory=dict)
    improvements: List[Dict[str, Any]] = Field(default_factory=list)
    regressions: List[Dict[str, Any]] = Field(default_factory=list)
    hidden_risks: List[Dict[str, Any]] = Field(default_factory=list)
    root_causes: List[Dict[str, Any]] = Field(default_factory=list)
    agentic_actions_taken: List[str] = Field(default_factory=list)
    recommended_actions: List[str] = Field(default_factory=list)
    patch_candidates: List[Dict[str, Any]] = Field(default_factory=list)
    routing: RoutingDecision
    artifacts: ArtifactURIs


def _as_list(value: Any) -> List[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return list(value)
    if value is None:
        return []
    return [value]


def _as_dict(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, Mapping):
        return {str(k): v for k, v in value.items()}
    return {}


def _to_plain_data(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(k): _to_plain_data(v) for k, v in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_to_plain_data(v) for v in value]
    return value


def _parse_json_or_empty(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            return {}
    return {}


def _requested_output(requested_outputs: Any, key: str, default: bool = True) -> bool:
    if isinstance(requested_outputs, dict):
        return bool(requested_outputs.get(key, default))
    if isinstance(requested_outputs, list):
        return key in requested_outputs
    return default


def _severity(verdict: str) -> int:
    ranking = {"PASS": 0, "WARN": 1, "BLOCK": 2, "ERROR": 3}
    return ranking.get(str(verdict).upper(), 0)


def _compute_pre_verdict(
    weighted_f1_delta: float,
    warn_threshold: float,
    block_threshold: float,
    regression_findings: List[Dict[str, Any]],
    critical_doc_types: List[str],
) -> (str, bool):
    verdict = "PASS"
    if weighted_f1_delta < -block_threshold:
        verdict = "BLOCK"
    elif weighted_f1_delta < -warn_threshold:
        verdict = "WARN"

    critical_hit = any(
        str((item or {}).get("doc_type", "")) in set(critical_doc_types)
        for item in regression_findings
        if isinstance(item, dict)
    )
    if critical_hit:
        verdict = "BLOCK"

    return verdict, critical_hit


def _default_routing(verdict: str, rationale: str) -> Dict[str, Any]:
    v = str(verdict).upper()
    if v == "ERROR":
        return {
            "block_release": True,
            "request_human_review": True,
            "open_defect": True,
            "notify_roles": ["AI_LEAD", "DELIVERY_OWNER"],
            "verdict": v,
            "verdict_rationale": rationale,
        }
    if v == "BLOCK":
        return {
            "block_release": True,
            "request_human_review": True,
            "open_defect": True,
            "notify_roles": ["AI_LEAD", "DELIVERY_OWNER"],
            "verdict": v,
            "verdict_rationale": rationale,
        }
    if v == "WARN":
        return {
            "block_release": False,
            "request_human_review": True,
            "open_defect": False,
            "notify_roles": ["AI_LEAD"],
            "verdict": v,
            "verdict_rationale": rationale,
        }
    return {
        "block_release": False,
        "request_human_review": False,
        "open_defect": False,
        "notify_roles": [],
        "verdict": "PASS",
        "verdict_rationale": rationale,
    }


def _build_agentic_actions(audit_events: List[Dict[str, Any]], rerun_count: int) -> List[str]:
    actions: List[str] = []
    for event in audit_events:
        if not isinstance(event, dict):
            continue
        agent = str(event.get("agent_name", "Agent"))
        summary = str(event.get("summary", "")).strip()
        etype = str(event.get("event_type", "")).upper()
        if summary and etype in {"COMPLETE", "FLOW_START"}:
            actions.append(f"{agent}: {summary}")
    if rerun_count > 0:
        actions.append(f"Targeted reruns executed: {rerun_count}")
    deduped: List[str] = []
    seen = set()
    for item in actions:
        if item not in seen:
            seen.add(item)
            deduped.append(item)
    return deduped[:10]


def _build_recommended_actions(
    root_causes: List[Dict[str, Any]],
    patch_candidates: List[Dict[str, Any]],
    recommended_experiments: List[str],
    verdict: str,
) -> List[str]:
    items: List[str] = []
    for cause in root_causes:
        if isinstance(cause, dict) and cause.get("cause"):
            items.append(f"Investigate root cause: {cause.get('cause')}")
    for patch in patch_candidates:
        if isinstance(patch, dict) and patch.get("description"):
            items.append(f"Review patch candidate: {patch.get('description')}")
    for exp in recommended_experiments:
        items.append(f"Run follow-up experiment: {exp}")

    verdict_upper = str(verdict).upper()
    if verdict_upper == "BLOCK":
        items.insert(0, "Pause release and start human review before promotion.")
    elif verdict_upper == "WARN":
        items.insert(0, "Proceed only with human sign-off and monitor critical doc types.")

    if not items:
        items = ["No immediate action required. Continue monitoring scheduled runs."]

    deduped: List[str] = []
    seen = set()
    for item in items:
        if item not in seen:
            seen.add(item)
            deduped.append(item)
    return deduped[:8]


def _build_artifact_uris(state_dict: Dict[str, Any], run_id: str) -> Dict[str, str]:
    storage = _as_dict(state_dict.get("storage_config"))
    namespace = str(storage.get("artifact_namespace", "agentic-testing"))
    workspace_key = str(storage.get("run_workspace_key", run_id))
    base = f"managed://{namespace}/{workspace_key}"
    return {
        "report_pdf_uri": f"{base}/outputs/Run_Report.pdf",
        "report_html_uri": f"{base}/report.html",
        "execution_visual_uri": f"{base}/execution_flow.html",
        "run_json_uri": f"{base}/latest_run.json",
        "excel_log_uri": f"{base}/outputs/Run_Report.xlsx",
        "audit_log_uri": f"{base}/logs/AgenticTesting_AuditLog.xlsx",
        "trace_pack_uri": f"{base}/trace_pack.json",
    }


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _hydrate_packet_from_latest_run(packet: Dict[str, Any], workspace_path: str) -> Dict[str, Any]:
    """
    Ensure runtime response matches persisted packet content for critical sections.
    """
    latest_run_path = os.path.join(workspace_path, "latest_run.json")
    if not os.path.exists(latest_run_path):
        return packet
    try:
        with open(latest_run_path, "r", encoding="utf-8") as fh:
            persisted = json.load(fh)
    except Exception:
        return packet

    for key in ("summary_metrics", "doc_type_breakdown", "change_summary"):
        if not _as_dict(packet.get(key)) and _as_dict(persisted.get(key)):
            packet[key] = _as_dict(persisted.get(key))

    if not _as_list(packet.get("improvements")) and _as_list(persisted.get("improvements")):
        packet["improvements"] = _as_list(persisted.get("improvements"))
    if not _as_list(packet.get("regressions")) and _as_list(persisted.get("regressions")):
        packet["regressions"] = _as_list(persisted.get("regressions"))
    if not _as_list(packet.get("hidden_risks")) and _as_list(persisted.get("hidden_risks")):
        packet["hidden_risks"] = _as_list(persisted.get("hidden_risks"))

    return packet


def _write_excel_run_report(
    workspace_path: str,
    packet: Dict[str, Any],
    audit_events: List[Dict[str, Any]],
) -> str:
    report_path = os.path.join(workspace_path, "outputs", "Run_Report.xlsx")
    run_summary = [
        {
            "RunID": packet.get("run_id", ""),
            "Status": packet.get("status", ""),
            "Verdict": packet.get("verdict", ""),
            "Confidence": packet.get("confidence", 0.0),
            "TransactionsAnalyzed": _as_dict(packet.get("analysis_scope")).get("total_transactions", 0),
            "DateFrom": _as_dict(packet.get("analysis_scope")).get("date_from", ""),
            "DateTo": _as_dict(packet.get("analysis_scope")).get("date_to", ""),
            "RegressionCount": len(_as_list(packet.get("regressions"))),
            "ImprovementCount": len(_as_list(packet.get("improvements"))),
            "HiddenRiskCount": len(_as_list(packet.get("hidden_risks"))),
        }
    ]
    write_sheet._run(workbook_path=report_path, sheet_name="RunSummary", rows=run_summary, overwrite=True)

    findings_rows: List[Dict[str, Any]] = []
    for item in _as_list(packet.get("improvements")):
        findings_rows.append({"Type": "improvement", "Finding": json.dumps(item, default=str)})
    for item in _as_list(packet.get("regressions")):
        findings_rows.append({"Type": "regression", "Finding": json.dumps(item, default=str)})
    for item in _as_list(packet.get("hidden_risks")):
        findings_rows.append({"Type": "hidden_risk", "Finding": json.dumps(item, default=str)})
    if not findings_rows:
        findings_rows = [{"Type": "info", "Finding": "No findings generated."}]
    write_sheet._run(workbook_path=report_path, sheet_name="Findings", rows=findings_rows, overwrite=True)

    timeline_rows: List[Dict[str, Any]] = []
    for event in audit_events:
        if not isinstance(event, dict):
            continue
        timeline_rows.append(
            {
                "Agent": event.get("agent_name", ""),
                "EventType": event.get("event_type", ""),
                "Timestamp": event.get("timestamp", ""),
                "Summary": event.get("summary", ""),
                "Status": event.get("status", ""),
            }
        )
    if timeline_rows:
        write_sheet._run(workbook_path=report_path, sheet_name="ExecutionTimeline", rows=timeline_rows, overwrite=True)

    summary_metrics = _as_dict(packet.get("summary_metrics"))
    metrics_rows = [{"Metric": k, "Value": v} for k, v in summary_metrics.items()]
    if metrics_rows:
        write_sheet._run(workbook_path=report_path, sheet_name="SummaryMetrics", rows=metrics_rows, overwrite=True)

    doc_type_breakdown = _as_dict(packet.get("doc_type_breakdown"))
    breakdown_rows: List[Dict[str, Any]] = []
    for doc_type, info in doc_type_breakdown.items():
        info = info if isinstance(info, dict) else {}
        breakdown_rows.append(
            {
                "DocType": doc_type,
                "WeightedF1Delta": info.get("weighted_f1_delta", 0.0),
                "ImprovementCount": info.get("improvement_count", 0),
                "RegressionCount": info.get("regression_count", 0),
            }
        )
    if breakdown_rows:
        write_sheet._run(workbook_path=report_path, sheet_name="DocTypeBreakdown", rows=breakdown_rows, overwrite=True)

    patch_rows = []
    for patch in _as_list(packet.get("patch_candidates")):
        if not isinstance(patch, dict):
            continue
        patch_rows.append(
            {
                "PatchID": patch.get("patch_id", ""),
                "PatchType": patch.get("patch_type", ""),
                "Target": patch.get("target", ""),
                "Description": patch.get("description", ""),
                "Confidence": patch.get("confidence", 0.0),
                "RequiresHumanApproval": patch.get("requires_human_approval", True),
            }
        )
    if patch_rows:
        write_sheet._run(workbook_path=report_path, sheet_name="PatchCandidates", rows=patch_rows, overwrite=True)

    return report_path


def _write_artifacts(packet: Dict[str, Any], state_dict: Dict[str, Any]) -> Dict[str, Any]:
    run_id = str(state_dict.get("run_id", packet.get("run_id", "unknown_run")))
    workspace_path = str(state_dict.get("workspace_path", "") or ".")
    os.makedirs(workspace_path, exist_ok=True)

    audit_events = _as_list(state_dict.get("audit_events"))
    policy = _as_dict(state_dict.get("policy"))
    summary_metrics = _as_dict(packet.get("summary_metrics"))
    doc_type_breakdown = _as_dict(state_dict.get("doc_type_breakdown"))
    analysis_scope = _as_dict(packet.get("analysis_scope"))
    scope_doc_types = _as_list(analysis_scope.get("doc_types"))
    evidence_summary = _as_dict(state_dict.get("evidence_summary"))

    html_state = {
        "run_id": run_id,
        "workspace_path": workspace_path,
        "verdict": packet.get("verdict", "UNKNOWN"),
        "confidence": packet.get("confidence", 0.0),
        "transaction_count": analysis_scope.get("total_transactions", 0),
        "date_from": analysis_scope.get("date_from", ""),
        "date_to": analysis_scope.get("date_to", ""),
        "metrics": _as_dict(packet.get("summary_metrics")),
        "doc_type_breakdown": doc_type_breakdown,
        "improvements": _as_list(packet.get("improvements")),
        "regressions": _as_list(packet.get("regressions")),
        "hidden_risks": _as_list(packet.get("hidden_risks")),
        "root_causes": _as_list(packet.get("root_causes")),
        "patch_candidates": _as_list(packet.get("patch_candidates")),
        "doc_type_count": len(doc_type_breakdown) or len(scope_doc_types) or len(_as_dict(evidence_summary.get("doc_type_distribution"))),
        "rerun_count": int(state_dict.get("rerun_count", 0) or 0),
        "weighted_f1_delta": summary_metrics.get("weighted_f1_delta", "-"),
        "warn_threshold": policy.get("warn_weighted_f1_drop", 0.02),
        "block_threshold": policy.get("block_weighted_f1_drop", 0.05),
        "routing_decision": _as_dict(packet.get("routing")).get("verdict_rationale", ""),
        "trend_direction": state_dict.get("trend_direction", "unknown"),
        "trend_confidence": state_dict.get("trend_confidence", 0.0),
        "agentic_actions": _as_list(packet.get("agentic_actions_taken")),
        "recommended_actions": _as_list(packet.get("recommended_actions")),
        "execution_timeline": audit_events,
        "change_summary_text": json.dumps(_as_dict(packet.get("change_summary")), default=str)[:500],
    }

    artifact_errors: List[str] = []

    def _record_tool_result(tool_name: str, raw_result: Any) -> None:
        parsed = _parse_json_or_empty(raw_result)
        if parsed.get("error"):
            msg = f"{tool_name} error: {parsed.get('error')}"
            artifact_errors.append(msg)
            log_event(
                LOGGER,
                event="artifact_tool_error",
                level="ERROR",
                run_id=run_id,
                stage=tool_name,
                workspace_path=workspace_path,
                context={"tool_result": parsed},
            )
        else:
            log_event(
                LOGGER,
                event="artifact_tool_ok",
                level="INFO",
                run_id=run_id,
                stage=tool_name,
                workspace_path=workspace_path,
                context={"tool_result": parsed},
            )

    _record_tool_result("write_html_report", write_html_report._run(run_state=html_state))
    _record_tool_result("write_execution_visual", write_execution_visual._run(run_state=html_state))

    pdf_enabled = _requested_output(state_dict.get("requested_outputs"), "pdf_report", True)
    if pdf_enabled:
        _record_tool_result("write_pdf_report", write_pdf_report._run(run_state=html_state))

    excel_enabled = _requested_output(state_dict.get("requested_outputs"), "excel_log", True)
    if excel_enabled:
        try:
            report_path = _write_excel_run_report(workspace_path=workspace_path, packet=packet, audit_events=audit_events)
            log_event(
                LOGGER,
                event="artifact_tool_ok",
                level="INFO",
                run_id=run_id,
                stage="write_excel_run_report",
                workspace_path=workspace_path,
                context={"path": report_path},
            )
        except Exception as exc:
            artifact_errors.append(f"write_excel_run_report error: {exc}")
            log_event(
                LOGGER,
                event="artifact_tool_error",
                level="ERROR",
                run_id=run_id,
                stage="write_excel_run_report",
                workspace_path=workspace_path,
                context={},
                exc=exc,
            )

    trace_state = {
        "workspace_path": workspace_path,
        "run_id": run_id,
        "full_maestro_input": {
            "run_request": state_dict.get("run_request", {}),
            "scope": state_dict.get("scope", {}),
            "current_artifact": state_dict.get("current_artifact", {}),
            "previous_artifact": state_dict.get("previous_artifact", {}),
            "policy": state_dict.get("policy", {}),
            "requested_outputs": state_dict.get("requested_outputs", {}),
        },
        "selected_transactions": _as_dict(packet.get("analysis_scope")).get("transaction_ids", []),
        "all_agent_outputs": {
            "change_summary": state_dict.get("change_summary", {}),
            "summary_metrics": state_dict.get("summary_metrics", {}),
            "improvements": state_dict.get("improvement_findings", []),
            "regressions": state_dict.get("regression_findings", []),
            "hidden_risks": state_dict.get("hidden_risk_findings", []),
            "root_causes": state_dict.get("root_causes", []),
            "patch_candidates": state_dict.get("patch_candidates", []),
            "trend_summary": state_dict.get("trend_summary", {}),
            "confidence_assessment": state_dict.get("confidence_assessment", {}),
        },
        "rerun_requests": [state_dict.get("scope_expansion_request", {})] if state_dict.get("scope_expansion_request") else [],
        "final_packet": packet,
    }
    _record_tool_result("write_trace_pack", write_trace_pack._run(run_state=trace_state))

    _record_tool_result("write_final_packet", write_final_packet._run(workspace_path=workspace_path, final_packet=packet))

    audit_log_path = os.path.join(workspace_path, "logs", "AgenticTesting_AuditLog.xlsx")
    _record_tool_result(
        "write_audit_log_event",
        write_audit_log_event._run(
        audit_log_path=audit_log_path,
        event_row={
            "RunID": run_id,
            "EventID": str(uuid.uuid4())[:8],
            "AgentName": "ReportRoutingAgent",
            "EventType": "COMPLETE",
            "Summary": f"Final packet generated with verdict {packet.get('verdict', 'UNKNOWN')}",
            "Status": "OK",
        },
        ),
    )

    if artifact_errors:
        packet.setdefault("errors", [])
        packet["errors"].extend(artifact_errors)

    return packet


def run_report_routing(state_dict: Dict[str, Any]) -> Dict[str, Any]:
    run_id: str = str(state_dict.get("run_id", "unknown_run"))
    workspace_path: str = str(state_dict.get("workspace_path", ""))
    log_event(
        LOGGER,
        event="report_routing_start",
        level="INFO",
        run_id=run_id,
        stage="run_report_routing",
        workspace_path=workspace_path or None,
        context={
            "has_policy": isinstance(state_dict.get("policy"), dict),
            "requested_outputs_type": type(state_dict.get("requested_outputs")).__name__,
            "error_log_count": len(_as_list(state_dict.get("error_log"))),
        },
    )
    policy: Dict[str, Any] = _as_dict(state_dict.get("policy"))

    block_threshold: float = _to_float(policy.get("block_weighted_f1_drop", 0.05), 0.05)
    warn_threshold: float = _to_float(policy.get("warn_weighted_f1_drop", 0.02), 0.02)
    warn_confidence_below: float = _to_float(policy.get("warn_confidence_below", 0.60), 0.60)
    block_confidence_below: float = _to_float(policy.get("block_confidence_below", 0.35), 0.35)
    if block_confidence_below > warn_confidence_below:
        block_confidence_below = warn_confidence_below
    critical_doc_types: List[str] = [str(x) for x in _as_list(policy.get("critical_doc_types"))]

    change_summary: Dict[str, Any] = _as_dict(state_dict.get("change_summary"))
    selected_transaction_ids: List[int] = [int(x) for x in _as_list(state_dict.get("selected_transaction_ids")) if str(x).isdigit()]
    selected_doc_types: List[str] = [str(x) for x in _as_list(state_dict.get("selected_doc_types"))]
    date_from: str = str(state_dict.get("date_from", ""))
    date_to: str = str(state_dict.get("date_to", ""))

    summary_metrics: Dict[str, Any] = _as_dict(state_dict.get("summary_metrics"))
    improvement_findings: List[Dict[str, Any]] = [x for x in _as_list(state_dict.get("improvement_findings")) if isinstance(x, dict)]
    regression_findings: List[Dict[str, Any]] = [x for x in _as_list(state_dict.get("regression_findings")) if isinstance(x, dict)]
    hidden_risk_findings: List[Dict[str, Any]] = [x for x in _as_list(state_dict.get("hidden_risk_findings")) if isinstance(x, dict)]
    root_causes: List[Dict[str, Any]] = [x for x in _as_list(state_dict.get("root_causes")) if isinstance(x, dict)]
    patch_candidates: List[Dict[str, Any]] = [x for x in _as_list(state_dict.get("patch_candidates")) if isinstance(x, dict)]

    confidence_assessment: Dict[str, Any] = _as_dict(state_dict.get("confidence_assessment"))
    recommended_experiments: List[str] = [str(x) for x in _as_list(state_dict.get("recommended_experiments"))]
    rerun_count: int = int(state_dict.get("rerun_count", 0) or 0)
    audit_events: List[Dict[str, Any]] = [x for x in _as_list(state_dict.get("audit_events")) if isinstance(x, dict)]
    flow_errors: List[str] = [str(x) for x in _as_list(state_dict.get("error_log")) if str(x).strip()]

    total_transactions = int(
        _as_dict(state_dict.get("evidence_summary")).get("total_transactions", len(_as_list(state_dict.get("case_bundles"))))
    )

    weighted_f1_delta = _to_float(summary_metrics.get("weighted_f1_delta", 0.0), 0.0)
    pre_verdict, critical_regression = _compute_pre_verdict(
        weighted_f1_delta=weighted_f1_delta,
        warn_threshold=warn_threshold,
        block_threshold=block_threshold,
        regression_findings=regression_findings,
        critical_doc_types=critical_doc_types,
    )
    if flow_errors:
        pre_verdict = "ERROR"

    llm_output: Dict[str, Any] = {}
    llm_error: Optional[str] = None

    if not use_deterministic_mode():
        try:
            llm = get_structured_llm()
            prompt_file = os.path.join(os.path.dirname(__file__), "..", "prompts", "report_routing.txt")
            backstory_extra = ""
            if os.path.exists(prompt_file):
                with open(prompt_file, "r", encoding="utf-8") as fh:
                    backstory_extra = fh.read()

            agent = Agent(
                role="Report and Routing Orchestrator",
                goal=(
                    "Synthesize findings into a final routing decision and produce a valid packet."
                ),
                backstory=(
                    "You are the final quality gate. Use evidence only and keep decisions policy-aligned.\n\n"
                    + backstory_extra
                ),
                tools=[
                    write_html_report,
                    write_execution_visual,
                    write_trace_pack,
                    write_final_packet,
                    write_audit_log_event,
                    write_sheet,
                ],
                llm=llm,
                verbose=True,
                max_iter=2,
            )

            task = Task(
                description=(
                    f"Run ID: {run_id}. "
                    f"Policy thresholds block={block_threshold}, warn={warn_threshold}. "
                    f"weighted_f1_delta={weighted_f1_delta}. "
                    f"critical_regression={critical_regression}. "
                    "Return valid JSON for FinalRoutingOutput only."
                ),
                expected_output="A valid FinalRoutingOutput JSON object.",
                agent=agent,
            )

            result = Crew(agents=[agent], tasks=[task], verbose=True).kickoff()
            raw = result.raw if hasattr(result, "raw") else str(result)
            llm_output = _parse_json_or_empty(raw)
        except Exception as exc:
            llm_error = str(exc)
            llm_output = {}
            log_event(
                LOGGER,
                event="report_routing_llm_synthesis_failed",
                level="ERROR",
                run_id=run_id,
                stage="run_report_routing",
                workspace_path=workspace_path or None,
                context={"pre_verdict": pre_verdict},
                exc=exc,
            )
    else:
        log_event(
            LOGGER,
            event="report_routing_llm_synthesis_skipped",
            level="INFO",
            run_id=run_id,
            stage="run_report_routing",
            workspace_path=workspace_path or None,
            context={"reason": "deterministic_mode_enabled"},
        )

    llm_verdict = str(llm_output.get("verdict", pre_verdict)).upper()
    if llm_verdict not in {"PASS", "WARN", "BLOCK", "ERROR"}:
        llm_verdict = pre_verdict

    final_verdict = pre_verdict if _severity(pre_verdict) >= _severity(llm_verdict) else llm_verdict

    confidence = _to_float(
        llm_output.get("confidence", confidence_assessment.get("overall_confidence", 0.0)),
        _to_float(confidence_assessment.get("overall_confidence", 0.0), 0.0),
    )
    confidence = max(0.0, min(1.0, confidence))
    if final_verdict == "ERROR":
        confidence = min(confidence, 0.2)
    confidence_gate_note = ""
    if final_verdict != "ERROR":
        if confidence < block_confidence_below and final_verdict in {"PASS", "WARN"}:
            final_verdict = "BLOCK"
            confidence_gate_note = (
                f"Confidence-gated to BLOCK because overall_confidence={confidence:.2f} "
                f"is below block_confidence_below={block_confidence_below:.2f}."
            )
        elif confidence < warn_confidence_below and final_verdict == "PASS":
            final_verdict = "WARN"
            confidence_gate_note = (
                f"Confidence-gated to WARN because overall_confidence={confidence:.2f} "
                f"is below warn_confidence_below={warn_confidence_below:.2f}."
            )

    rationale = (
        _as_dict(llm_output.get("routing")).get("verdict_rationale")
        or f"Policy-evaluated verdict is {final_verdict} with weighted_f1_delta={weighted_f1_delta:.4f}."
    )
    if confidence_gate_note:
        rationale = f"{rationale} {confidence_gate_note}"

    routing = _default_routing(final_verdict, str(rationale))
    llm_routing = _as_dict(llm_output.get("routing"))
    if llm_routing:
        routing["notify_roles"] = [str(x) for x in _as_list(llm_routing.get("notify_roles", routing["notify_roles"]))]
        routing["verdict_rationale"] = str(llm_routing.get("verdict_rationale", routing["verdict_rationale"]))

    agentic_actions = [str(x) for x in _as_list(llm_output.get("agentic_actions_taken"))]
    if not agentic_actions:
        agentic_actions = _build_agentic_actions(audit_events=audit_events, rerun_count=rerun_count)

    recommended_actions = [str(x) for x in _as_list(llm_output.get("recommended_actions"))]
    if not recommended_actions:
        recommended_actions = _build_recommended_actions(
            root_causes=root_causes,
            patch_candidates=patch_candidates,
            recommended_experiments=recommended_experiments,
            verdict=final_verdict,
        )
    if flow_errors:
        recommended_actions.insert(0, "Fix runtime/agent execution errors before trusting analysis metrics.")

    packet: Dict[str, Any] = {
        "run_id": run_id,
        "status": "failed" if final_verdict == "ERROR" else "completed",
        "verdict": final_verdict,
        "confidence": confidence,
        "analysis_scope": {
            "transaction_ids": selected_transaction_ids,
            "doc_types": selected_doc_types,
            "date_from": date_from,
            "date_to": date_to,
            "total_transactions": total_transactions,
        },
        "change_summary": change_summary,
        "summary_metrics": summary_metrics,
        "doc_type_breakdown": _as_dict(state_dict.get("doc_type_breakdown")),
        "improvements": improvement_findings,
        "regressions": regression_findings,
        "hidden_risks": hidden_risk_findings,
        "root_causes": root_causes,
        "agentic_actions_taken": agentic_actions,
        "recommended_actions": recommended_actions,
        "patch_candidates": patch_candidates,
        "routing": routing,
        "artifacts": _build_artifact_uris(state_dict=state_dict, run_id=run_id),
    }
    if flow_errors:
        packet["errors"] = flow_errors[:50]

    if llm_error:
        packet.setdefault("routing", {})
        packet["routing"]["verdict_rationale"] = (
            str(packet["routing"].get("verdict_rationale", ""))
            + f" (LLM synthesis warning: {llm_error})"
        )
        packet.setdefault("errors", [])
        packet["errors"].append(f"LLM synthesis warning: {llm_error}")

    try:
        packet = _write_artifacts(packet=packet, state_dict=state_dict)
        packet = _hydrate_packet_from_latest_run(packet, workspace_path=workspace_path)
        packet = _to_plain_data(packet)
    except Exception as exc:
        log_event(
            LOGGER,
            event="report_routing_artifact_write_failed",
            level="ERROR",
            run_id=run_id,
            stage="run_report_routing",
            workspace_path=workspace_path or None,
            context={},
            exc=exc,
        )
        packet.setdefault("errors", [])
        packet["errors"].append(f"Artifact write failure: {exc.__class__.__name__}: {exc}")
        packet["status"] = "failed"
        packet["verdict"] = "ERROR"
        packet["routing"] = _default_routing("ERROR", "Artifact writing failed; see errors list.")

    try:
        validated = FinalRoutingOutput(**packet)
        validated_payload = validated.model_dump()
        # Guard against provider/runtime proxy coercion stripping populated sections.
        if not _as_dict(validated_payload.get("summary_metrics")) and _as_dict(packet.get("summary_metrics")):
            validated_payload["summary_metrics"] = _as_dict(packet.get("summary_metrics"))
        if not _as_dict(validated_payload.get("doc_type_breakdown")) and _as_dict(packet.get("doc_type_breakdown")):
            validated_payload["doc_type_breakdown"] = _as_dict(packet.get("doc_type_breakdown"))
        log_event(
            LOGGER,
            event="report_routing_complete",
            level="INFO",
            run_id=run_id,
            stage="run_report_routing",
            workspace_path=workspace_path or None,
            context={
                "verdict": validated.verdict,
                "status": validated.status,
                "error_count": len(_as_list(packet.get("errors"))),
            },
        )
        return validated_payload
    except ValidationError as exc:
        packet["error"] = "final_output_validation_failed"
        packet["detail"] = exc.errors()
        log_event(
            LOGGER,
            event="report_routing_output_validation_failed",
            level="ERROR",
            run_id=run_id,
            stage="run_report_routing",
            workspace_path=workspace_path or None,
            context={"error_count": len(exc.errors())},
            exc=exc,
        )
        return packet
