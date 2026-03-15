"""
Reporting tools - write HTML reports, execution visuals, trace packs, final packets,
and audit log events.
"""
import datetime
import json
import os
from typing import Any, Dict, List, Type

from crewai.tools import BaseTool
from pydantic import BaseModel, Field


def _ensure_dir(path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)


def _ts() -> str:
    return datetime.datetime.utcnow().isoformat() + "Z"


def _escape(value: Any) -> str:
    text = str(value) if value is not None else ""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _as_list(value: Any) -> List[Any]:
    if isinstance(value, list):
        return value
    if value is None:
        return []
    return [value]


def _fmt_percent(value: Any) -> str:
    try:
        return f"{float(value) * 100:.1f}%"
    except (TypeError, ValueError):
        return "-"


def _render_bullets(items: List[Any], empty_msg: str) -> str:
    if not items:
        return f"<p class='muted'>{_escape(empty_msg)}</p>"
    li = "".join(f"<li>{_escape(item)}</li>" for item in items)
    return f"<ul>{li}</ul>"


def _render_metrics_rows(metrics: Dict[str, Any]) -> str:
    rows: List[str] = []
    for key, value in metrics.items():
        if isinstance(value, dict):
            baseline = _escape(value.get("baseline", ""))
            candidate = _escape(value.get("candidate", ""))
            raw_delta = value.get("delta", "")
            try:
                delta_num = float(raw_delta)
                cls = "delta-pos" if delta_num > 0 else "delta-neg" if delta_num < 0 else "delta-flat"
                delta = f"<span class='{cls}'>{delta_num:+.4f}</span>"
            except (TypeError, ValueError):
                delta = _escape(raw_delta)
            rows.append(
                f"<tr><td>{_escape(key)}</td><td>{baseline}</td><td>{candidate}</td><td>{delta}</td></tr>"
            )
        else:
            rows.append(f"<tr><td>{_escape(key)}</td><td colspan='3'>{_escape(value)}</td></tr>")
    return "".join(rows) if rows else "<tr><td colspan='4'>No metrics available.</td></tr>"


def _normalize_events(events: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    normal: List[Dict[str, str]] = []
    for event in events or []:
        if not isinstance(event, dict):
            continue
        normal.append(
            {
                "agent_name": str(event.get("agent_name") or event.get("AgentName") or "UnknownAgent"),
                "event_type": str(event.get("event_type") or event.get("EventType") or "INFO"),
                "timestamp": str(event.get("timestamp") or event.get("Timestamp") or ""),
                "summary": str(event.get("summary") or event.get("Summary") or ""),
                "status": str(event.get("status") or event.get("Status") or "OK"),
            }
        )
    normal.sort(key=lambda x: x.get("timestamp", ""))
    return normal


def _event_class(event_type: str, status: str) -> str:
    t = event_type.upper()
    s = status.upper()
    if "ERROR" in t or "ERROR" in s:
        return "event-error"
    if "COMPLETE" in t:
        return "event-complete"
    if "START" in t:
        return "event-start"
    return "event-info"


def _render_timeline(events: List[Dict[str, str]]) -> str:
    if not events:
        return "<p class='muted'>No execution events captured.</p>"
    html: List[str] = ["<div class='timeline'>"]
    for event in events:
        cls = _event_class(event.get("event_type", ""), event.get("status", ""))
        html.append(
            "<div class='timeline-item'>"
            f"<div class='dot {cls}'></div>"
            "<div class='timeline-body'>"
            f"<div class='timeline-title'>{_escape(event.get('agent_name'))} - {_escape(event.get('event_type'))}</div>"
            f"<div class='timeline-meta'>{_escape(event.get('timestamp'))}</div>"
            f"<div class='timeline-summary'>{_escape(event.get('summary'))}</div>"
            "</div></div>"
        )
    html.append("</div>")
    return "".join(html)


def _render_flow_strip(events: List[Dict[str, str]]) -> str:
    ordered_agents = [
        "Flow",
        "IntakeDiffAgent",
        "ScopePlannerAgent",
        "EvidenceCollectorAgent",
        "RegressionHunterAgent",
        "ChallengerAgent",
        "TargetedRerunAgent",
        "TrendDriftAgent",
        "RootCauseAgent",
        "PatchProposalAgent",
        "ReportRoutingAgent",
    ]

    latest_status: Dict[str, str] = {name: "pending" for name in ordered_agents}
    for event in events:
        agent = event.get("agent_name", "")
        if agent not in latest_status:
            continue
        etype = event.get("event_type", "").upper()
        status = event.get("status", "").upper()
        if "ERROR" in etype or "ERROR" in status:
            latest_status[agent] = "error"
        elif "COMPLETE" in etype:
            latest_status[agent] = "done"
        elif "START" in etype:
            latest_status[agent] = "active"

    cards: List[str] = ["<div class='flow-strip'>"]
    for agent in ordered_agents:
        state = latest_status[agent]
        label = agent.replace("Agent", "")
        cards.append(
            f"<div class='flow-card flow-{state}'>"
            f"<div class='flow-card-title'>{_escape(label)}</div>"
            f"<div class='flow-card-state'>{_escape(state.upper())}</div>"
            "</div>"
        )
    cards.append("</div>")
    return "".join(cards)


_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>Document AI Report - {run_id}</title>
  <style>
    :root {{
      --bg: #f4f7fb;
      --ink: #152033;
      --brand: #0f4c81;
      --card: #ffffff;
      --line: #d9e2ef;
      --ok: #1b8a4a;
      --warn: #f3a60a;
      --block: #c23b2a;
      --muted: #6b7280;
    }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; background: var(--bg); color: var(--ink); font-family: "Segoe UI", Tahoma, sans-serif; }}
    .hero {{
      background: linear-gradient(135deg, #0f4c81 0%, #155c9a 50%, #2d7ab8 100%);
      color: #fff;
      padding: 28px 36px;
    }}
    .hero h1 {{ margin: 0 0 8px; font-size: 1.5rem; }}
    .meta {{ opacity: 0.92; font-size: 0.9rem; }}
    .verdict {{
      display: inline-block;
      margin-top: 14px;
      padding: 8px 14px;
      border-radius: 999px;
      font-weight: 700;
      letter-spacing: 0.04em;
      background: rgba(255,255,255,0.2);
    }}
    .container {{ padding: 22px 24px 32px; max-width: 1200px; margin: 0 auto; }}
    .grid {{ display: grid; grid-template-columns: repeat(4, minmax(150px, 1fr)); gap: 12px; }}
    .kpi {{
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 14px;
      box-shadow: 0 6px 20px rgba(15, 76, 129, 0.06);
    }}
    .kpi .label {{ font-size: 0.78rem; color: var(--muted); }}
    .kpi .value {{ font-size: 1.2rem; font-weight: 700; margin-top: 4px; }}
    .section {{
      margin-top: 14px;
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 16px 18px;
      box-shadow: 0 6px 20px rgba(15, 76, 129, 0.05);
    }}
    .section h2 {{ margin: 0 0 10px; color: var(--brand); font-size: 1.02rem; }}
    .muted {{ color: var(--muted); }}
    table {{ width: 100%; border-collapse: collapse; font-size: 0.9rem; }}
    th {{ text-align: left; background: #edf3fb; color: #183452; font-weight: 700; border-bottom: 1px solid var(--line); padding: 9px; }}
    td {{ border-bottom: 1px solid var(--line); padding: 8px 9px; vertical-align: top; }}
    ul {{ margin: 0; padding-left: 20px; }}
    li {{ margin: 5px 0; }}
    .delta-pos {{ color: var(--ok); font-weight: 700; }}
    .delta-neg {{ color: var(--block); font-weight: 700; }}
    .delta-flat {{ color: var(--muted); font-weight: 700; }}
    .flow-strip {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
      gap: 10px;
    }}
    .flow-card {{
      border-radius: 10px;
      border: 1px solid var(--line);
      padding: 10px 11px;
      background: #fbfdff;
    }}
    .flow-card-title {{ font-weight: 700; font-size: 0.86rem; }}
    .flow-card-state {{ margin-top: 4px; font-size: 0.75rem; letter-spacing: 0.05em; color: var(--muted); }}
    .flow-done {{ border-color: #bfe3cd; background: #eefaf3; }}
    .flow-active {{ border-color: #bfdbff; background: #eef5ff; }}
    .flow-error {{ border-color: #f0bcbc; background: #fff2f2; }}
    .timeline {{ border-left: 2px solid var(--line); margin-left: 6px; padding-left: 14px; }}
    .timeline-item {{ display: grid; grid-template-columns: 14px 1fr; column-gap: 10px; margin-bottom: 12px; }}
    .dot {{ width: 10px; height: 10px; border-radius: 50%; margin-top: 5px; }}
    .event-start {{ background: #2d7ab8; }}
    .event-complete {{ background: #1b8a4a; }}
    .event-error {{ background: #c23b2a; }}
    .event-info {{ background: #7b8794; }}
    .timeline-title {{ font-weight: 700; font-size: 0.86rem; }}
    .timeline-meta {{ font-size: 0.74rem; color: var(--muted); margin-top: 1px; }}
    .timeline-summary {{ font-size: 0.84rem; margin-top: 3px; }}
    .footer {{ text-align: center; color: var(--muted); font-size: 0.78rem; margin-top: 16px; }}
    @media (max-width: 900px) {{
      .grid {{ grid-template-columns: repeat(2, minmax(150px, 1fr)); }}
    }}
  </style>
</head>
<body>
  <section class="hero">
    <h1>Document AI Agentic Testing Report</h1>
    <div class="meta">
      Run ID: <strong>{run_id}</strong> | Generated: <strong>{generated_at}</strong> | Date Range: <strong>{date_from}</strong> to <strong>{date_to}</strong>
    </div>
    <div class="verdict">Verdict: {verdict} | Confidence: {confidence_percent}</div>
  </section>

  <main class="container">
    <section class="grid">
      <article class="kpi"><div class="label">Transactions</div><div class="value">{transaction_count}</div></article>
      <article class="kpi"><div class="label">Improvements</div><div class="value">{improvement_count}</div></article>
      <article class="kpi"><div class="label">Regressions</div><div class="value">{regression_count}</div></article>
      <article class="kpi"><div class="label">Hidden Risks</div><div class="value">{risk_count}</div></article>
    </section>

    <section class="section">
      <h2>Execution Flow Overview</h2>
      {flow_strip_html}
    </section>

    <section class="section">
      <h2>Decision Narrative</h2>
      <p><strong>Routing:</strong> {routing_decision}</p>
      <p><strong>Trend Direction:</strong> {trend_direction}</p>
      <p><strong>Change Summary:</strong> {change_summary_text}</p>
      <h2 style="margin-top:16px;">Agentic Actions</h2>
      {agentic_actions_html}
      <h2 style="margin-top:16px;">Recommended Actions</h2>
      {recommended_actions_html}
    </section>

    <section class="section">
      <h2>Summary Metrics</h2>
      <table>
        <tr><th>Metric</th><th>Baseline</th><th>Candidate</th><th>Delta</th></tr>
        {metrics_rows}
      </table>
    </section>

    <section class="section">
      <h2>Improvements</h2>
      {improvements_html}
      <h2 style="margin-top:16px;">Regressions</h2>
      {regressions_html}
      <h2 style="margin-top:16px;">Hidden Risks</h2>
      {hidden_risks_html}
    </section>

    <section class="section">
      <h2>Root Causes and Patch Candidates</h2>
      <h2 style="margin-top:0;">Root Causes</h2>
      {root_causes_html}
      <h2 style="margin-top:16px;">Patch Candidates</h2>
      {patch_candidates_html}
    </section>

    <section class="section">
      <h2>Execution Timeline</h2>
      {timeline_html}
    </section>

    <div class="footer">Generated by Document AI Agentic Testing System</div>
  </main>
</body>
</html>
"""


_EXECUTION_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Execution Flow - {run_id}</title>
  <style>
    body {{ margin: 0; font-family: "Segoe UI", Tahoma, sans-serif; background: #f7fafc; color: #1f2a37; }}
    .wrap {{ max-width: 1200px; margin: 0 auto; padding: 20px; }}
    .title {{ background: #0f4c81; color: #fff; border-radius: 12px; padding: 18px 20px; }}
    .title h1 {{ margin: 0 0 4px; font-size: 1.35rem; }}
    .title p {{ margin: 0; opacity: 0.9; }}
    .card {{ margin-top: 14px; background: #fff; border: 1px solid #d9e2ef; border-radius: 12px; padding: 14px; }}
    .flow-strip {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap: 10px; }}
    .flow-card {{ border-radius: 10px; border: 1px solid #d9e2ef; padding: 10px; background: #fbfdff; }}
    .flow-done {{ border-color: #bfe3cd; background: #eefaf3; }}
    .flow-active {{ border-color: #bfdbff; background: #eef5ff; }}
    .flow-error {{ border-color: #f0bcbc; background: #fff2f2; }}
    .flow-card-title {{ font-weight: 700; font-size: 0.86rem; }}
    .flow-card-state {{ margin-top: 4px; font-size: 0.74rem; color: #6b7280; letter-spacing: 0.05em; }}
    .timeline {{ border-left: 2px solid #d9e2ef; margin-left: 6px; padding-left: 14px; }}
    .timeline-item {{ display: grid; grid-template-columns: 14px 1fr; column-gap: 10px; margin-bottom: 12px; }}
    .dot {{ width: 10px; height: 10px; border-radius: 50%; margin-top: 5px; }}
    .event-start {{ background: #2d7ab8; }}
    .event-complete {{ background: #1b8a4a; }}
    .event-error {{ background: #c23b2a; }}
    .event-info {{ background: #7b8794; }}
    .timeline-title {{ font-weight: 700; font-size: 0.86rem; }}
    .timeline-meta {{ font-size: 0.74rem; color: #6b7280; margin-top: 1px; }}
    .timeline-summary {{ font-size: 0.84rem; margin-top: 3px; }}
  </style>
</head>
<body>
  <main class="wrap">
    <section class="title">
      <h1>Agentic Execution Visual</h1>
      <p>Run ID: {run_id} | Generated: {generated_at} | Verdict: {verdict}</p>
    </section>

    <section class="card">
      <h2>Flow State Map</h2>
      {flow_strip_html}
    </section>

    <section class="card">
      <h2>Step Timeline</h2>
      {timeline_html}
    </section>
  </main>
</body>
</html>
"""


class WriteHtmlReportInput(BaseModel):
    run_state: Dict[str, Any] = Field(
        ...,
        description=(
            "Run state dict with reporting data including verdict, metrics, findings, "
            "routing rationale, and execution events."
        ),
    )


class WriteHtmlReportTool(BaseTool):
    name: str = "write_html_report"
    description: str = (
        "Generate a polished HTML report at <workspace_path>/report.html with verdict, "
        "metrics, findings, and execution timeline."
    )
    args_schema: Type[BaseModel] = WriteHtmlReportInput

    def _run(self, run_state: Dict[str, Any]) -> str:
        try:
            workspace_path = str(run_state.get("workspace_path", "."))
            report_path = os.path.join(workspace_path, "report.html")
            os.makedirs(workspace_path, exist_ok=True)

            run_id = str(run_state.get("run_id", "UNKNOWN"))
            verdict = str(run_state.get("verdict", "UNKNOWN")).upper()
            if verdict not in {"PASS", "WARN", "BLOCK"}:
                verdict = "UNKNOWN"

            confidence = run_state.get("confidence", 0.0)
            transaction_count = run_state.get("transaction_count", 0)
            date_from = run_state.get("date_from", "")
            date_to = run_state.get("date_to", "")
            generated_at = _ts()

            metrics = run_state.get("metrics") if isinstance(run_state.get("metrics"), dict) else {}
            improvements = _as_list(run_state.get("improvements"))
            regressions = _as_list(run_state.get("regressions"))
            hidden_risks = _as_list(run_state.get("hidden_risks"))
            root_causes = _as_list(run_state.get("root_causes"))
            patch_candidates = _as_list(run_state.get("patch_candidates"))
            agentic_actions = _as_list(run_state.get("agentic_actions"))
            recommended_actions = _as_list(run_state.get("recommended_actions"))

            events = _normalize_events(_as_list(run_state.get("execution_timeline")))
            flow_strip_html = _render_flow_strip(events)
            timeline_html = _render_timeline(events)

            routing_decision = _escape(run_state.get("routing_decision", "No routing decision provided."))
            trend_direction = _escape(run_state.get("trend_direction", "unknown"))
            change_summary_text = _escape(run_state.get("change_summary_text", "No change summary available."))

            html = _HTML_TEMPLATE.format(
                run_id=_escape(run_id),
                generated_at=_escape(generated_at),
                verdict=_escape(verdict),
                confidence_percent=_escape(_fmt_percent(confidence)),
                transaction_count=_escape(transaction_count),
                date_from=_escape(date_from),
                date_to=_escape(date_to),
                improvement_count=_escape(len(improvements)),
                regression_count=_escape(len(regressions)),
                risk_count=_escape(len(hidden_risks)),
                flow_strip_html=flow_strip_html,
                routing_decision=routing_decision,
                trend_direction=trend_direction,
                change_summary_text=change_summary_text,
                agentic_actions_html=_render_bullets(agentic_actions, "No agentic action notes."),
                recommended_actions_html=_render_bullets(recommended_actions, "No recommended actions."),
                metrics_rows=_render_metrics_rows(metrics),
                improvements_html=_render_bullets(improvements, "No improvements detected."),
                regressions_html=_render_bullets(regressions, "No regressions detected."),
                hidden_risks_html=_render_bullets(hidden_risks, "No hidden risks detected."),
                root_causes_html=_render_bullets(root_causes, "No root causes identified."),
                patch_candidates_html=_render_bullets(patch_candidates, "No patch candidates."),
                timeline_html=timeline_html,
            )

            with open(report_path, "w", encoding="utf-8") as f:
                f.write(html)

            return json.dumps({"status": "ok", "path": report_path, "verdict": verdict})
        except Exception as exc:
            return json.dumps({"error": str(exc), "tool": "write_html_report"})


class WriteExecutionVisualInput(BaseModel):
    run_state: Dict[str, Any] = Field(
        ...,
        description="Run state dict with run_id, workspace_path, verdict, and execution timeline events.",
    )


class WriteExecutionVisualTool(BaseTool):
    name: str = "write_execution_visual"
    description: str = (
        "Generate a dedicated execution visualization HTML artifact at "
        "<workspace_path>/execution_flow.html."
    )
    args_schema: Type[BaseModel] = WriteExecutionVisualInput

    def _run(self, run_state: Dict[str, Any]) -> str:
        try:
            workspace_path = str(run_state.get("workspace_path", "."))
            output_path = os.path.join(workspace_path, "execution_flow.html")
            os.makedirs(workspace_path, exist_ok=True)

            run_id = str(run_state.get("run_id", "UNKNOWN"))
            verdict = str(run_state.get("verdict", "UNKNOWN")).upper()
            generated_at = _ts()
            events = _normalize_events(_as_list(run_state.get("execution_timeline")))

            html = _EXECUTION_TEMPLATE.format(
                run_id=_escape(run_id),
                generated_at=_escape(generated_at),
                verdict=_escape(verdict),
                flow_strip_html=_render_flow_strip(events),
                timeline_html=_render_timeline(events),
            )

            with open(output_path, "w", encoding="utf-8") as f:
                f.write(html)

            return json.dumps({"status": "ok", "path": output_path})
        except Exception as exc:
            return json.dumps({"error": str(exc), "tool": "write_execution_visual"})


class WriteTracePackInput(BaseModel):
    run_state: Dict[str, Any] = Field(
        ...,
        description=(
            "Full run state dict. Expected keys: workspace_path, full_maestro_input, "
            "selected_transactions, all_agent_outputs, rerun_requests, final_packet."
        ),
    )


class WriteTracePackTool(BaseTool):
    name: str = "write_trace_pack"
    description: str = (
        "Write a full trace JSON artifact to <workspace_path>/trace_pack.json for audit "
        "and reproducibility."
    )
    args_schema: Type[BaseModel] = WriteTracePackInput

    def _run(self, run_state: Dict[str, Any]) -> str:
        try:
            workspace_path = str(run_state.get("workspace_path", "."))
            os.makedirs(workspace_path, exist_ok=True)
            trace_path = os.path.join(workspace_path, "trace_pack.json")

            trace_pack = {
                "generated_at_utc": _ts(),
                "run_id": run_state.get("run_id", "UNKNOWN"),
                "full_maestro_input": run_state.get("full_maestro_input"),
                "selected_transactions": run_state.get("selected_transactions") or [],
                "all_agent_outputs": run_state.get("all_agent_outputs") or {},
                "rerun_requests": run_state.get("rerun_requests") or [],
                "final_packet": run_state.get("final_packet") or {},
            }

            with open(trace_path, "w", encoding="utf-8") as f:
                json.dump(trace_pack, f, indent=2, default=str)

            return json.dumps({"status": "ok", "path": trace_path})
        except Exception as exc:
            return json.dumps({"error": str(exc), "tool": "write_trace_pack"})


class WriteFinalPacketInput(BaseModel):
    workspace_path: str = Field(..., description="Root workspace directory for this run.")
    final_packet: Dict[str, Any] = Field(
        ...,
        description="Final run packet to persist at <workspace_path>/latest_run.json.",
    )


class WriteFinalPacketTool(BaseTool):
    name: str = "write_final_packet"
    description: str = "Write final packet JSON to <workspace_path>/latest_run.json."
    args_schema: Type[BaseModel] = WriteFinalPacketInput

    def _run(self, workspace_path: str, final_packet: Dict[str, Any]) -> str:
        try:
            os.makedirs(workspace_path, exist_ok=True)
            output_path = os.path.join(workspace_path, "latest_run.json")

            payload = {
                "written_at_utc": _ts(),
                **final_packet,
            }

            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, default=str)

            return json.dumps({"status": "ok", "path": output_path})
        except Exception as exc:
            return json.dumps({"error": str(exc), "tool": "write_final_packet"})


class WriteAuditLogEventInput(BaseModel):
    audit_log_path: str = Field(..., description="Absolute path to the audit log workbook.")
    event_row: Dict[str, Any] = Field(
        ...,
        description=(
            "Event row dict with fields: RunID, EventID, AgentName, EventType, Timestamp, "
            "DurationSeconds, InputRef, OutputRef, Summary, Status."
        ),
    )


class WriteAuditLogEventTool(BaseTool):
    name: str = "write_audit_log_event"
    description: str = (
        "Append an event row to the AgentEvents sheet in the audit log workbook. "
        "Creates workbook/sheet if missing."
    )
    args_schema: Type[BaseModel] = WriteAuditLogEventInput

    def _run(self, audit_log_path: str, event_row: Dict[str, Any]) -> str:
        try:
            from .excel_writer import AppendRowsTool

            appender = AppendRowsTool()
            normalised = {
                "RunID": event_row.get("RunID", ""),
                "EventID": event_row.get("EventID", ""),
                "AgentName": event_row.get("AgentName", ""),
                "EventType": event_row.get("EventType", ""),
                "Timestamp": event_row.get("Timestamp", _ts()),
                "DurationSeconds": event_row.get("DurationSeconds", 0.0),
                "InputRef": event_row.get("InputRef", ""),
                "OutputRef": event_row.get("OutputRef", ""),
                "Summary": event_row.get("Summary", ""),
                "Status": event_row.get("Status", "OK"),
            }
            return appender._run(
                workbook_path=audit_log_path,
                sheet_name="AgentEvents",
                rows=[normalised],
            )
        except Exception as exc:
            return json.dumps({"error": str(exc), "tool": "write_audit_log_event"})


write_html_report = WriteHtmlReportTool()
write_execution_visual = WriteExecutionVisualTool()
write_trace_pack = WriteTracePackTool()
write_final_packet = WriteFinalPacketTool()
write_audit_log_event = WriteAuditLogEventTool()
