"""
agents/report_routing.py

ReportRouting Agent — produces the final executive summary, technical HTML report,
routing decision packet, run report Excel workbook, trace pack, and audit log.
Applies policy thresholds to make routing decisions (PASS/WARN/BLOCK).
All outputs are grounded in prior agent findings only.
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


# ---------------------------------------------------------------------------
# Output schema
# ---------------------------------------------------------------------------

class RoutingDecision(BaseModel):
    block_release: bool = Field(..., description="True if the release should be blocked")
    request_human_review: bool = Field(..., description="True if human review is required")
    open_defect: bool = Field(..., description="True if a defect should be opened")
    notify_roles: List[str] = Field(
        default_factory=list,
        description="List of roles to notify: e.g., ['qa_lead', 'prompt_engineer', 'product_owner']",
    )
    verdict: str = Field(..., description="PASS | WARN | BLOCK")
    verdict_rationale: str = Field(..., description="Plain-English explanation of the verdict")


class ArtifactURIs(BaseModel):
    report_html_uri: str = Field(default="", description="URI of the HTML report artifact")
    run_json_uri: str = Field(default="", description="URI of the run JSON packet artifact")
    excel_log_uri: str = Field(default="", description="URI of the Excel run log artifact")
    audit_log_uri: str = Field(default="", description="URI of the audit log artifact")
    trace_pack_uri: str = Field(default="", description="URI of the trace pack artifact")


class AnalysisScope(BaseModel):
    transaction_ids: List[int] = Field(default_factory=list)
    doc_types: List[str] = Field(default_factory=list)
    date_from: str = Field(default="")
    date_to: str = Field(default="")
    total_transactions: int = Field(default=0)


class FinalRoutingOutput(BaseModel):
    run_id: str = Field(..., description="Unique identifier for this analysis run")
    status: str = Field(..., description="Run status: completed | failed | partial")
    verdict: str = Field(..., description="PASS | WARN | BLOCK")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Overall confidence in the verdict")
    analysis_scope: AnalysisScope = Field(..., description="Scope of the analysis performed")
    change_summary: Dict[str, Any] = Field(
        default_factory=dict, description="Summary of what changed (from IntakeDiff)"
    )
    summary_metrics: Dict[str, Any] = Field(
        default_factory=dict, description="Aggregate metrics from RegressionHunter"
    )
    improvements: List[Dict[str, Any]] = Field(
        default_factory=list, description="Improvement findings from RegressionHunter"
    )
    regressions: List[Dict[str, Any]] = Field(
        default_factory=list, description="Regression findings from RegressionHunter"
    )
    hidden_risks: List[Dict[str, Any]] = Field(
        default_factory=list, description="Hidden risk findings from RegressionHunter"
    )
    root_causes: List[Dict[str, Any]] = Field(
        default_factory=list, description="Root causes from RootCause agent"
    )
    agentic_actions_taken: List[str] = Field(
        default_factory=list,
        description="Summary of actions taken by each agent during this run",
    )
    recommended_actions: List[str] = Field(
        default_factory=list,
        description="Prioritized list of recommended actions for humans to take",
    )
    patch_candidates: List[Dict[str, Any]] = Field(
        default_factory=list, description="Patch candidates from PatchProposal agent"
    )
    routing: RoutingDecision = Field(..., description="Routing decision and verdict")
    artifacts: ArtifactURIs = Field(..., description="URIs of generated artifacts")


# ---------------------------------------------------------------------------
# Agent entry point
# ---------------------------------------------------------------------------

def run_report_routing(state_dict: Dict[str, Any]) -> Dict[str, Any]:
    """
    Run the ReportRouting agent.

    Args:
        state_dict: Full FlowState dict containing outputs from all prior agents. Key fields:
            - run_id (str)
            - workspace_path (str)
            - policy (dict): With keys block_weighted_f1_drop (float), warn_weighted_f1_drop (float),
              critical_doc_types (list[str])
            - requested_outputs (list[str]): e.g., ['html_report', 'excel_log', 'trace_pack']
            - change_summary (dict): From IntakeDiff
            - selected_transaction_ids (list[int]): From ScopePlanner
            - selected_doc_types (list[str]): From ScopePlanner
            - date_from (str), date_to (str): Scope period
            - total_transactions (int): From EvidenceCollector
            - summary_metrics (dict): From RegressionHunter
            - improvement_findings (list): From RegressionHunter
            - regression_findings (list): From RegressionHunter
            - hidden_risk_findings (list): From RegressionHunter
            - root_causes (list): From RootCause
            - patch_candidates (list): From PatchProposal
            - patch_rationale (str): From PatchProposal
            - trend_direction (str): From TrendDrift
            - drift_alerts (list): From TrendDrift
            - confidence_assessment (dict): From Challenger
            - targeted_rerun_summary (dict or None): From TargetedRerun

    Returns:
        dict conforming to FinalRoutingOutput schema, or error dict on failure.
    """
    from agentic_testing.tools.reporting_tools import (
        write_html_report,
        write_trace_pack,
        write_final_packet,
        write_audit_log_event,
    )
    from agentic_testing.tools.excel_writer import write_sheet, append_rows
    from agentic_testing.tools.logging_tools import write_model_data_trace, log_agent_event

    # --- Extract all prior agent outputs from state_dict ---
    run_id: str = state_dict.get("run_id", "unknown_run")
    workspace_path: str = state_dict.get("workspace_path", "")
    policy: Dict[str, Any] = state_dict.get("policy", {})
    requested_outputs: List[str] = state_dict.get("requested_outputs", ["html_report", "excel_log"])

    block_threshold: float = policy.get("block_weighted_f1_drop", 0.05)
    warn_threshold: float = policy.get("warn_weighted_f1_drop", 0.02)
    critical_doc_types: List[str] = policy.get(
        "critical_doc_types", ["IdentityDocument", "Passport", "ApplicationForm"]
    )

    change_summary: Dict[str, Any] = state_dict.get("change_summary", {})
    selected_transaction_ids: List[int] = state_dict.get("selected_transaction_ids", [])
    selected_doc_types: List[str] = state_dict.get("selected_doc_types", [])
    date_from: str = state_dict.get("date_from", "")
    date_to: str = state_dict.get("date_to", "")
    total_transactions: int = state_dict.get("total_transactions", 0)

    summary_metrics: Dict[str, Any] = state_dict.get("summary_metrics", {})
    improvement_findings: list = state_dict.get("improvement_findings", [])
    regression_findings: list = state_dict.get("regression_findings", [])
    hidden_risk_findings: list = state_dict.get("hidden_risk_findings", [])

    root_causes: list = state_dict.get("root_causes", [])
    patch_candidates: list = state_dict.get("patch_candidates", [])
    patch_rationale: str = state_dict.get("patch_rationale", "")

    trend_direction: str = state_dict.get("trend_direction", "unknown")
    drift_alerts: list = state_dict.get("drift_alerts", [])
    confidence_assessment: Dict[str, Any] = state_dict.get("confidence_assessment", {})
    targeted_rerun_summary: Optional[Dict[str, Any]] = state_dict.get("targeted_rerun_summary", None)

    # Pre-compute verdict for the agent to use as guidance
    weighted_f1_delta: float = summary_metrics.get("weighted_f1_delta", 0.0)
    doc_type_breakdown: Dict[str, Any] = state_dict.get("doc_type_breakdown", {})

    pre_computed_verdict = "PASS"
    if weighted_f1_delta < -block_threshold:
        pre_computed_verdict = "BLOCK"
    elif weighted_f1_delta < -warn_threshold:
        pre_computed_verdict = "WARN"

    # Override to BLOCK if any critical doc type has a regression
    critical_regression = False
    for finding in regression_findings:
        if finding.get("doc_type") in critical_doc_types:
            critical_regression = True
            pre_computed_verdict = "BLOCK"
            break

    llm = get_structured_llm()

    prompt_file = os.path.join(os.path.dirname(__file__), "..", "prompts", "report_routing.txt")
    backstory_extra = ""
    if os.path.exists(prompt_file):
        with open(prompt_file, "r", encoding="utf-8") as fh:
            backstory_extra = fh.read()

    agent = Agent(
        role="Report and Routing Orchestrator",
        goal=(
            "Produce the final executive summary, technical HTML report, routing decision packet, "
            "run report Excel workbook, trace pack, and audit log. Your outputs must be grounded "
            "in prior agent findings only."
        ),
        backstory=(
            "You are the final quality gate. You synthesize all prior findings into a clear, "
            "actionable output for humans and Maestro. You apply policy thresholds to make routing "
            "decisions (PASS/WARN/BLOCK). You are never optimistic beyond the evidence.\n\n"
            + backstory_extra
        ),
        tools=[
            write_html_report,
            write_trace_pack,
            write_final_packet,
            write_audit_log_event,
            write_sheet,
            append_rows,
            write_model_data_trace,
            log_agent_event,
        ],
        llm=llm,
        verbose=True,
        max_iter=3,
    )

    task_description = f"""
You are producing the final report and routing decision for run '{run_id}'.

--- POLICY THRESHOLDS ---
block_weighted_f1_drop: {block_threshold} (block if F1 drops by more than this)
warn_weighted_f1_drop: {warn_threshold} (warn if F1 drops by more than this)
critical_doc_types: {critical_doc_types}

--- PRE-COMPUTED VERDICT GUIDANCE ---
weighted_f1_delta: {weighted_f1_delta}
critical_doc_type_regression_detected: {critical_regression}
recommended_verdict: {pre_computed_verdict}

VERDICT LOGIC:
  IF weighted_f1_delta < -{block_threshold} → BLOCK
  ELSE IF weighted_f1_delta < -{warn_threshold} → WARN
  ELSE → PASS
  OVERRIDE: If ANY critical doc type has a regression finding → BLOCK regardless of F1 delta

--- WORKSPACE ---
workspace_path: {workspace_path}
requested_outputs: {requested_outputs}

--- CHANGE SUMMARY ---
{json.dumps(change_summary, indent=2)}

--- ANALYSIS SCOPE ---
selected_transaction_ids: {selected_transaction_ids}
selected_doc_types: {selected_doc_types}
date_from: {date_from}
date_to: {date_to}
total_transactions: {total_transactions}

--- SUMMARY METRICS ---
{json.dumps(summary_metrics, indent=2)}

--- IMPROVEMENTS ({len(improvement_findings)}) ---
{json.dumps(improvement_findings, indent=2)}

--- REGRESSIONS ({len(regression_findings)}) ---
{json.dumps(regression_findings, indent=2)}

--- HIDDEN RISKS ({len(hidden_risk_findings)}) ---
{json.dumps(hidden_risk_findings, indent=2)}

--- ROOT CAUSES ---
{json.dumps(root_causes, indent=2)}

--- PATCH CANDIDATES ---
{json.dumps(patch_candidates, indent=2)}

--- TREND ---
trend_direction: {trend_direction}
drift_alerts: {json.dumps(drift_alerts, indent=2)}

--- CHALLENGER CONFIDENCE ---
{json.dumps(confidence_assessment, indent=2)}

--- TARGETED RERUN SUMMARY ---
{json.dumps(targeted_rerun_summary, indent=2) if targeted_rerun_summary else "(none)"}

Your tasks:
1. Apply the verdict logic above to determine the final verdict (PASS/WARN/BLOCK).
2. Generate a human-readable verdict_rationale that cites specific evidence.
3. Determine routing actions: block_release, request_human_review, open_defect, notify_roles.
   - BLOCK → block_release=true, request_human_review=true, open_defect=true
   - WARN → block_release=false, request_human_review=true, open_defect=false
   - PASS → block_release=false, request_human_review=false, open_defect=false
4. Build recommended_actions list (3–8 items) based on root causes and patch candidates.
5. Build agentic_actions_taken list summarizing what each agent did.
6. Generate artifacts using the tools:
   a. Use `write_html_report` to generate the HTML report → store URI as managed://reports/{run_id}/report.html
   b. Use `write_final_packet` to write the routing JSON packet → managed://packets/{run_id}/routing.json
   c. Use `write_sheet` and `append_rows` to write the Excel run log → managed://excel/{run_id}/run_log.xlsx
   d. Use `write_trace_pack` to write the trace pack → managed://traces/{run_id}/trace.zip
   e. Use `write_audit_log_event` to log the final verdict event
   f. Use `write_model_data_trace` to persist run metrics
   g. Use `log_agent_event` to log the report routing completion
7. Return a single valid JSON object matching the FinalRoutingOutput schema.

CRITICAL: Only include findings that prior agents actually reported. Do not invent improvements,
regressions, or root causes. Synthesize — do not fabricate.

Return ONLY valid JSON. Do not include markdown fences, explanations, or commentary.
"""

    task = Task(
        description=task_description,
        expected_output=(
            "A single valid JSON object conforming to FinalRoutingOutput with keys: run_id, "
            "status, verdict, confidence, analysis_scope, change_summary, summary_metrics, "
            "improvements, regressions, hidden_risks, root_causes, agentic_actions_taken, "
            "recommended_actions, patch_candidates, routing (with block_release, "
            "request_human_review, open_defect, notify_roles, verdict, verdict_rationale), "
            "artifacts (with report_html_uri, run_json_uri, excel_log_uri, audit_log_uri, "
            "trace_pack_uri)."
        ),
        agent=agent,
        output_pydantic=FinalRoutingOutput,
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
