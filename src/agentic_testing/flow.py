"""
AgenticTestingFlow - main CrewAI Flow for document AI agentic testing.

Orchestration order:
  1. receive_maestro_payload  -> validate input, create workspace
  2. run_intake_diff          -> diff the execution artifacts
  3. run_scope_planner        -> select initial transactions
  4. run_evidence_collector   -> build case bundles
  5. run_regression_hunter    -> find improvements / regressions / hidden risks
  6. run_challenger           -> challenge weak evidence
  7. route_after_challenger   -> ROUTER: needs more evidence -> targeted_rerun; else -> trend_drift
  8. run_targeted_rerun       -> expand scope (if challenger said so)
  9. run_evidence_refresh     -> re-collect with expanded scope (if rerun happened)
 10. run_regression_refresh   -> re-hunt (if rerun happened)
 11. run_trend_drift          -> analyze trends
 12. run_root_cause           -> diagnose causes
 13. run_patch_proposal       -> propose fixes
 14. run_report_routing       -> write all outputs and return final packet
"""
from __future__ import annotations

import base64
import datetime
import json
import mimetypes
import os
from pathlib import Path
from typing import Any, Dict

from crewai.flow.flow import Flow, listen, router, start
from pydantic import ValidationError

from .runtime_logging import get_runtime_logger, log_event
from .schemas.crew_output import FlowState
from .schemas.maestro_input import MaestroInput

# Agent runners
from .agents.intake_diff import run_intake_diff
from .agents.scope_planner import run_scope_planner
from .agents.evidence_collector import run_evidence_collector
from .agents.regression_hunter import run_regression_hunter
from .agents.challenger import run_challenger
from .agents.targeted_rerun import run_targeted_rerun
from .agents.trend_drift import run_trend_drift
from .agents.root_cause import run_root_cause
from .agents.patch_proposal import run_patch_proposal
from .agents.report_routing import run_report_routing

LOGGER = get_runtime_logger("flow")


def _resolve_workspace_path(state: FlowState) -> str:
    """Resolve the workspace path for this run."""
    base = state.storage_config.get("workspace_base_path") or os.getenv("WORKSPACE_BASE_PATH", "workspaces")
    run_id = state.run_id or "unknown"
    return os.path.join(base, run_id)


def _resolve_evidence_store_path(state: FlowState) -> str:
    """Resolve the evidence store path."""
    store_ref = state.evidence_store_config.get("store_ref", "DocumentAI_EvidenceStore")
    return os.getenv("EVIDENCE_STORE_PATH", f"data/{store_ref}.xlsx")


def _resolve_audit_log_path(workspace_path: str) -> str:
    return os.path.join(workspace_path, "logs", "AgenticTesting_AuditLog.xlsx")


def _encode_file_base64(path: Path) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("ascii")


def _collect_artifact_candidates(workspace_path: str) -> Dict[str, Path]:
    ws = Path(workspace_path)
    candidates: Dict[str, Path] = {
        "report_html": ws / "report.html",
        "execution_visual": ws / "execution_flow.html",
        "run_json": ws / "latest_run.json",
        "trace_pack": ws / "trace_pack.json",
        "audit_log_excel": ws / "logs" / "AgenticTesting_AuditLog.xlsx",
    }

    optional_candidates = {
        "report_pdf": [
            ws / "outputs" / "Run_Report.pdf",
            ws / "outputs" / "run_report.pdf",
            ws / "report.pdf",
        ],
        "excel_log": [
            ws / "outputs" / "Run_REPORT.xlsx",
            ws / "outputs" / "Run_Report.xlsx",
            ws / "outputs" / "run_log.xlsx",
            ws / "run_log.xlsx",
        ],
    }
    for key, options in optional_candidates.items():
        for option in options:
            if option.exists():
                candidates[key] = option
                break

    return {k: p for k, p in candidates.items() if p.exists() and p.is_file()}


def _inject_artifact_base64(packet: Dict[str, Any], workspace_path: str) -> Dict[str, Any]:
    """
    Add base64-encoded artifact content under `artifacts.embedded_files`.
    """
    if not workspace_path or not isinstance(packet, dict):
        return packet

    embed_enabled = os.getenv("AGENTIC_EMBED_ARTIFACTS_BASE64", "true").strip().lower() in {"1", "true", "yes", "y"}
    if not embed_enabled:
        return packet

    try:
        max_bytes = int(os.getenv("AGENTIC_MAX_EMBED_FILE_BYTES", str(5 * 1024 * 1024)))
    except ValueError:
        max_bytes = 5 * 1024 * 1024

    artifacts = packet.get("artifacts")
    if not isinstance(artifacts, dict):
        artifacts = {}

    embedded_files: Dict[str, Dict[str, Any]] = {}
    for key, file_path in _collect_artifact_candidates(workspace_path).items():
        file_size = file_path.stat().st_size
        mime_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"

        if file_size > max_bytes:
            embedded_files[key] = {
                "filename": file_path.name,
                "mime_type": mime_type,
                "encoding": "base64",
                "data": None,
                "size_bytes": file_size,
                "skipped": True,
                "reason": f"File exceeds AGENTIC_MAX_EMBED_FILE_BYTES ({max_bytes}).",
            }
            continue

        embedded_files[key] = {
            "filename": file_path.name,
            "mime_type": mime_type,
            "encoding": "base64",
            "data": _encode_file_base64(file_path),
            "size_bytes": file_size,
            "skipped": False,
        }

    artifacts["embedded_files"] = embedded_files
    packet["artifacts"] = artifacts
    return packet


class AgenticTestingFlow(Flow[FlowState]):
    """
    Stateful CrewAI Flow for document AI agentic testing.
    Accepts a MaestroInput payload and returns a final routing packet.
    """

    def _record_step_error(self, agent_name: str, exc: Exception) -> None:
        msg = f"{agent_name} failed: {exc.__class__.__name__}: {exc}"
        self.state.error_log.append(msg)
        self.state.add_audit_event(agent_name, "ERROR", msg, status="ERROR")
        log_event(
            LOGGER,
            event="flow_step_error",
            level="ERROR",
            run_id=self.state.run_id,
            stage=agent_name,
            workspace_path=self.state.workspace_path,
            context={"error_count": len(self.state.error_log)},
            exc=exc,
        )
        print(f"[Flow][ERROR] {msg}")

    def _safe_fallback_packet(self, extra_error: str = "") -> Dict[str, Any]:
        all_errors = list(self.state.error_log or [])
        if extra_error:
            all_errors.append(extra_error)
        return {
            "run_id": self.state.run_id or "unknown_run",
            "status": "failed",
            "verdict": "ERROR",
            "block_release": True,
            "request_human_review": True,
            "open_defect": True,
            "errors": all_errors,
            "routing": {
                "block_release": True,
                "request_human_review": True,
                "open_defect": True,
                "notify_roles": ["AI_LEAD", "DELIVERY_OWNER"],
                "verdict": "ERROR",
                "verdict_rationale": "Flow failed due to runtime errors. See errors list.",
            },
            "artifacts": {},
        }

    @start()
    def receive_maestro_payload(self) -> None:
        """Step 1 - Validate and unpack Maestro input, create runtime workspace."""
        self.state.start_datetime = datetime.datetime.utcnow().isoformat()

        self.state.workspace_path = _resolve_workspace_path(self.state)
        os.makedirs(self.state.workspace_path, exist_ok=True)
        os.makedirs(os.path.join(self.state.workspace_path, "logs"), exist_ok=True)
        os.makedirs(os.path.join(self.state.workspace_path, "outputs"), exist_ok=True)
        os.makedirs(os.path.join(self.state.workspace_path, "patch_candidates"), exist_ok=True)

        input_path = os.path.join(self.state.workspace_path, "maestro_input.json")
        with open(input_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "run_id": self.state.run_id,
                    "run_request": self.state.run_request,
                    "scope": self.state.scope,
                    "current_artifact": self.state.current_artifact,
                    "previous_artifact": self.state.previous_artifact,
                    "storage_config": self.state.storage_config,
                    "policy": self.state.policy,
                    "requested_outputs": self.state.requested_outputs,
                },
                f,
                indent=2,
                default=str,
            )

        self.state.add_audit_event(
            agent_name="Flow",
            event_type="FLOW_START",
            summary=f"Run {self.state.run_id} started. Workspace: {self.state.workspace_path}",
        )
        log_event(
            LOGGER,
            event="flow_started",
            level="INFO",
            run_id=self.state.run_id,
            stage="receive_maestro_payload",
            workspace_path=self.state.workspace_path,
            context={
                "workspace_path": self.state.workspace_path,
                "requested_outputs_keys": sorted((self.state.requested_outputs or {}).keys()),
                "scope_keys": sorted((self.state.scope or {}).keys()),
            },
        )
        print(f"[Flow] Run {self.state.run_id} started -> {self.state.workspace_path}")

    @listen(receive_maestro_payload)
    def run_intake_diff_step(self) -> None:
        """Step 2 - Diff the execution artifacts."""
        self.state.add_audit_event("IntakeDiffAgent", "START", "Diffing execution artifacts")
        try:
            result = run_intake_diff(
                {
                    "run_id": self.state.run_id,
                    "current_prompt_text": self.state.current_artifact.get("prompt_text", ""),
                    "previous_prompt_text": self.state.previous_artifact.get("prompt_text", ""),
                    "current_model": self.state.current_artifact.get("model_name", "unknown"),
                    "previous_model": self.state.previous_artifact.get("model_name", "unknown"),
                    "current_version": self.state.current_artifact.get("prompt_version_label", ""),
                    "previous_version": self.state.previous_artifact.get("prompt_version_label", ""),
                    "evidence_store_path": _resolve_evidence_store_path(self.state),
                    "workspace_path": self.state.workspace_path,
                    "audit_log_path": _resolve_audit_log_path(self.state.workspace_path),
                }
            )
        except Exception as exc:
            self._record_step_error("IntakeDiffAgent", exc)
            result = {}
        self.state.change_summary = result.get("change_summary") or result
        self.state.initial_risk_hypotheses = result.get("initial_risk_hypotheses", [])
        self.state.add_audit_event("IntakeDiffAgent", "COMPLETE", f"Prompt changed: {result.get('prompt_changed')}")
        print(f"[Flow] IntakeDiff done. Prompt changed: {result.get('prompt_changed')}")

    @listen(run_intake_diff_step)
    def run_scope_planner_step(self) -> None:
        """Step 3 - Select initial transaction scope."""
        self.state.add_audit_event("ScopePlannerAgent", "START", "Planning analysis scope")
        try:
            result = run_scope_planner(
                {
                    "run_id": self.state.run_id,
                    "scope": self.state.scope,
                    "change_summary": self.state.change_summary,
                    "initial_risk_hypotheses": self.state.initial_risk_hypotheses,
                    "evidence_store_path": _resolve_evidence_store_path(self.state),
                    "evidence_store_config": self.state.evidence_store_config,
                    "max_initial_transactions": self.state.run_request.get("max_initial_transactions", 20),
                    "workspace_path": self.state.workspace_path,
                }
            )
        except Exception as exc:
            self._record_step_error("ScopePlannerAgent", exc)
            result = {}
        self.state.selected_transaction_ids = result.get("selected_transaction_ids", [])
        self.state.selected_doc_types = result.get("selected_doc_types", [])
        self.state.analysis_plan = result.get("analysis_plan", {})
        self.state.add_audit_event(
            "ScopePlannerAgent",
            "COMPLETE",
            f"Selected {len(self.state.selected_transaction_ids)} transactions, {len(self.state.selected_doc_types)} doc types",
        )
        print(f"[Flow] ScopePlanner: {len(self.state.selected_transaction_ids)} transactions selected")

    @listen(run_scope_planner_step)
    def run_evidence_collector_step(self) -> None:
        """Step 4 - Collect and assemble evidence bundles."""
        self.state.add_audit_event("EvidenceCollectorAgent", "START", "Collecting evidence bundles")
        try:
            result = run_evidence_collector(
                {
                    "run_id": self.state.run_id,
                    "selected_transaction_ids": self.state.selected_transaction_ids,
                    "evidence_store_path": _resolve_evidence_store_path(self.state),
                    "evidence_store_config": self.state.evidence_store_config,
                    "workspace_path": self.state.workspace_path,
                }
            )
        except Exception as exc:
            self._record_step_error("EvidenceCollectorAgent", exc)
            result = {}
        self.state.case_bundles = result.get("case_bundles", [])
        self.state.evidence_summary = result.get("evidence_summary") or {
            "total_transactions": len(self.state.case_bundles),
            "doc_type_distribution": result.get("doc_type_distribution", {}),
            "evidence_quality_note": result.get("evidence_quality_note", ""),
            "missing_truth_count": result.get("missing_truth_count", 0),
            "missing_candidate_count": result.get("missing_candidate_count", 0),
        }
        self.state.add_audit_event("EvidenceCollectorAgent", "COMPLETE", f"Assembled {len(self.state.case_bundles)} bundles")
        print(f"[Flow] EvidenceCollector: {len(self.state.case_bundles)} bundles")

    @listen(run_evidence_collector_step)
    def run_regression_hunter_step(self) -> None:
        """Step 5 - Hunt for regressions, improvements, hidden risks."""
        self._run_regression_hunter_internal()

    def _run_regression_hunter_internal(self) -> None:
        self.state.add_audit_event("RegressionHunterAgent", "START", "Hunting regressions")
        try:
            result = run_regression_hunter(
                {
                    "run_id": self.state.run_id,
                    "case_bundles": self.state.case_bundles,
                    "policy": self.state.policy,
                    "workspace_path": self.state.workspace_path,
                }
            )
        except Exception as exc:
            self._record_step_error("RegressionHunterAgent", exc)
            result = {}
        self.state.improvement_findings = result.get("improvement_findings", [])
        self.state.regression_findings = result.get("regression_findings", [])
        self.state.hidden_risk_findings = result.get("hidden_risk_findings", [])
        self.state.summary_metrics = result.get("summary_metrics", {})
        self.state.doc_type_breakdown = result.get("doc_type_breakdown", {})
        self.state.add_audit_event(
            "RegressionHunterAgent",
            "COMPLETE",
            f"{len(self.state.regression_findings)} regressions, {len(self.state.improvement_findings)} improvements",
        )
        print(f"[Flow] RegressionHunter: {len(self.state.regression_findings)} regressions")

    @listen(run_regression_hunter_step)
    def run_challenger_step(self) -> None:
        """Step 6 - Challenge the evidence quality."""
        self.state.add_audit_event("ChallengerAgent", "START", "Challenging evidence")
        try:
            result = run_challenger(
                {
                    "run_id": self.state.run_id,
                    "evidence_summary": self.state.evidence_summary,
                    "improvement_findings": self.state.improvement_findings,
                    "regression_findings": self.state.regression_findings,
                    "hidden_risk_findings": self.state.hidden_risk_findings,
                    "total_transactions": (self.state.evidence_summary or {}).get(
                        "total_transactions",
                        len(self.state.case_bundles or []),
                    ),
                    "doc_type_distribution": (self.state.evidence_summary or {}).get("doc_type_distribution", {}),
                }
            )
        except Exception as exc:
            self._record_step_error("ChallengerAgent", exc)
            result = {}
        self.state.confidence_assessment = result.get("confidence_assessment", {})
        self.state.needs_more_evidence = bool(result.get("needs_more_evidence", False))
        self.state.challenge_notes = result.get("challenge_notes", [])
        self.state.add_audit_event("ChallengerAgent", "COMPLETE", f"Needs more evidence: {self.state.needs_more_evidence}")
        print(f"[Flow] Challenger: needs_more_evidence={self.state.needs_more_evidence}")

    @router(run_challenger_step)
    def route_after_challenger(self) -> str:
        """ROUTER - branch on whether more evidence is needed."""
        if self.state.error_log:
            return "trend_drift_branch"
        max_reruns = self.state.run_request.get("max_targeted_reruns", 3)
        if self.state.needs_more_evidence and self.state.rerun_count < max_reruns:
            return "targeted_rerun_branch"
        return "trend_drift_branch"

    @listen("targeted_rerun_branch")
    def run_targeted_rerun_step(self) -> None:
        """Step 8 (optional) - Expand scope and request targeted rerun."""
        self.state.add_audit_event("TargetedRerunAgent", "START", "Running targeted rerun")
        self.state.rerun_count += 1
        try:
            result = run_targeted_rerun(
                {
                    "run_id": self.state.run_id,
                    "needs_more_evidence": self.state.needs_more_evidence,
                    "challenge_notes": self.state.challenge_notes,
                    "hidden_risk_findings": self.state.hidden_risk_findings,
                    "change_summary": self.state.change_summary,
                    "current_scope": {
                        "transaction_ids": self.state.selected_transaction_ids,
                        "selected_transaction_ids": self.state.selected_transaction_ids,
                        "document_type_names": self.state.selected_doc_types,
                        "selected_doc_types": self.state.selected_doc_types,
                        "scope": self.state.scope,
                    },
                    "evidence_store_path": _resolve_evidence_store_path(self.state),
                    "max_total_transactions": self.state.run_request.get("max_total_transactions", 100),
                    "workspace_path": self.state.workspace_path,
                }
            )
        except Exception as exc:
            self._record_step_error("TargetedRerunAgent", exc)
            result = {}
        self.state.targeted_rerun_summary = result.get("targeted_rerun_summary", {})
        self.state.scope_expansion_request = result.get("scope_expansion_request", {})

        new_ids = result.get("transactions_added", [])
        if new_ids:
            existing = set(self.state.selected_transaction_ids or [])
            self.state.selected_transaction_ids = list(existing | set(new_ids))

        self.state.add_audit_event(
            "TargetedRerunAgent",
            "COMPLETE",
            f"Added {len(new_ids)} transactions. Total: {len(self.state.selected_transaction_ids)}",
        )
        print(f"[Flow] TargetedRerun: {len(new_ids)} new transactions added")

    @listen(run_targeted_rerun_step)
    def run_evidence_refresh_step(self) -> None:
        """Step 9 - Re-collect evidence after scope expansion."""
        self.run_evidence_collector_step()

    @listen(run_evidence_refresh_step)
    def run_regression_refresh_step(self) -> None:
        """Step 10 - Re-run regression hunter on expanded evidence."""
        self._run_regression_hunter_internal()

    @router(run_regression_refresh_step)
    def route_after_regression_refresh(self) -> str:
        """After rerun refresh, continue through the standard trend branch."""
        return "trend_drift_branch"

    @listen("trend_drift_branch")
    def run_trend_drift_step(self) -> None:
        """Step 11 - Analyze trends and drift."""
        self.state.add_audit_event("TrendDriftAgent", "START", "Analyzing trends")
        try:
            result = run_trend_drift(
                {
                    "run_id": self.state.run_id,
                    "date_from": self.state.scope.get("date_from", ""),
                    "date_to": self.state.scope.get("date_to", ""),
                    "evidence_store_path": _resolve_evidence_store_path(self.state),
                    "evidence_store_config": self.state.evidence_store_config,
                    "summary_metrics": self.state.summary_metrics or {},
                    "improvement_findings": self.state.improvement_findings,
                    "regression_findings": self.state.regression_findings,
                    "workspace_path": self.state.workspace_path,
                }
            )
        except Exception as exc:
            self._record_step_error("TrendDriftAgent", exc)
            result = {}
        self.state.trend_summary = result.get("trend_summary", {})
        self.state.drift_alerts = result.get("drift_alerts", [])
        self.state.trend_direction = result.get("trend_direction")
        self.state.trend_confidence = result.get("trend_confidence")
        self.state.add_audit_event("TrendDriftAgent", "COMPLETE", f"Trend: {result.get('trend_direction')}")
        print(f"[Flow] TrendDrift: {result.get('trend_direction')}")

    @listen(run_trend_drift_step)
    def run_root_cause_step(self) -> None:
        """Step 12 - Diagnose root causes."""
        self.state.add_audit_event("RootCauseAgent", "START", "Diagnosing root causes")
        try:
            result = run_root_cause(
                {
                    "run_id": self.state.run_id,
                    "change_summary": self.state.change_summary,
                    "regression_findings": self.state.regression_findings,
                    "targeted_rerun_summary": self.state.targeted_rerun_summary,
                    "trend_summary": self.state.trend_summary,
                    "workspace_path": self.state.workspace_path,
                }
            )
        except Exception as exc:
            self._record_step_error("RootCauseAgent", exc)
            result = {}
        self.state.root_causes = result.get("root_causes", [])
        self.state.add_audit_event("RootCauseAgent", "COMPLETE", f"{len(self.state.root_causes)} causes identified")
        print(f"[Flow] RootCause: {len(self.state.root_causes)} causes")

    @listen(run_root_cause_step)
    def run_patch_proposal_step(self) -> None:
        """Step 13 - Propose safe patches."""
        self.state.add_audit_event("PatchProposalAgent", "START", "Proposing patches")
        try:
            result = run_patch_proposal(
                {
                    "run_id": self.state.run_id,
                    "root_causes": self.state.root_causes,
                    "change_summary": self.state.change_summary,
                    "regression_findings": self.state.regression_findings,
                    "workspace_path": self.state.workspace_path,
                }
            )
        except Exception as exc:
            self._record_step_error("PatchProposalAgent", exc)
            result = {}
        self.state.patch_candidates = result.get("patch_candidates", [])
        self.state.recommended_experiments = result.get("recommended_experiments", [])
        self.state.patch_rationale = result.get("patch_rationale", "")
        self.state.add_audit_event("PatchProposalAgent", "COMPLETE", f"{len(self.state.patch_candidates)} patches proposed")
        print(f"[Flow] PatchProposal: {len(self.state.patch_candidates)} patches")

    @listen(run_patch_proposal_step)
    def run_report_routing_step(self) -> None:
        """Step 14 - Write all outputs and produce final packet."""
        self.state.end_datetime = datetime.datetime.utcnow().isoformat()
        self.state.add_audit_event("ReportRoutingAgent", "START", "Writing all outputs")
        try:
            result = run_report_routing(
                {
                    "run_id": self.state.run_id,
                    "workspace_path": self.state.workspace_path,
                    "policy": self.state.policy,
                    "requested_outputs": self.state.requested_outputs,
                    "run_request": self.state.run_request,
                    "scope": self.state.scope,
                    "date_from": self.state.scope.get("date_from", ""),
                    "date_to": self.state.scope.get("date_to", ""),
                    "current_artifact": self.state.current_artifact,
                    "previous_artifact": self.state.previous_artifact,
                    "change_summary": self.state.change_summary,
                    "selected_transaction_ids": self.state.selected_transaction_ids,
                    "selected_doc_types": self.state.selected_doc_types,
                    "case_bundles": self.state.case_bundles,
                    "evidence_summary": self.state.evidence_summary,
                    "total_transactions": (self.state.evidence_summary or {}).get(
                        "total_transactions",
                        len(self.state.case_bundles or []),
                    ),
                    "improvement_findings": self.state.improvement_findings,
                    "regression_findings": self.state.regression_findings,
                    "hidden_risk_findings": self.state.hidden_risk_findings,
                    "summary_metrics": self.state.summary_metrics,
                    "doc_type_breakdown": self.state.doc_type_breakdown,
                    "confidence_assessment": self.state.confidence_assessment,
                    "challenge_notes": self.state.challenge_notes,
                    "targeted_rerun_summary": self.state.targeted_rerun_summary,
                    "scope_expansion_request": self.state.scope_expansion_request,
                    "trend_summary": self.state.trend_summary,
                    "trend_direction": self.state.trend_direction,
                    "trend_confidence": self.state.trend_confidence,
                    "drift_alerts": self.state.drift_alerts,
                    "root_causes": self.state.root_causes,
                    "patch_candidates": self.state.patch_candidates,
                    "patch_rationale": self.state.patch_rationale,
                    "recommended_experiments": self.state.recommended_experiments,
                    "rerun_count": self.state.rerun_count,
                    "start_datetime": self.state.start_datetime,
                    "end_datetime": self.state.end_datetime,
                    "audit_events": self.state.audit_events,
                    "storage_config": self.state.storage_config,
                    "evidence_store_config": self.state.evidence_store_config,
                    "error_log": self.state.error_log,
                }
            )
        except Exception as exc:
            self._record_step_error("ReportRoutingAgent", exc)
            result = self._safe_fallback_packet(str(exc))
        result = _inject_artifact_base64(result, self.state.workspace_path or "")

        self.state.final_run_packet = result
        self.state.add_audit_event("ReportRoutingAgent", "COMPLETE", f"Verdict: {result.get('verdict')}")
        log_event(
            LOGGER,
            event="flow_completed",
            level="INFO",
            run_id=self.state.run_id,
            stage="run_report_routing_step",
            workspace_path=self.state.workspace_path,
            context={
                "verdict": result.get("verdict"),
                "status": result.get("status"),
                "error_count": len(self.state.error_log),
            },
        )
        print(f"[Flow] ReportRouting done. Verdict: {result.get('verdict')}")


def run_flow_from_maestro_payload(payload) -> Dict[str, Any]:
    """
    Entry point: accept the Maestro JSON payload as a dict OR a JSON string,
    validate it, initialise FlowState, run the flow, and return the final packet.
    """
    if isinstance(payload, str):
        payload = json.loads(payload)

    run_id = payload.get("run_request", {}).get("run_id", "unknown_run") if isinstance(payload, dict) else "unknown_run"
    log_event(
        LOGGER,
        event="run_flow_entry",
        level="INFO",
        run_id=run_id,
        stage="run_flow_from_maestro_payload",
        context={"payload_type": type(payload).__name__, "top_level_keys": sorted(payload.keys()) if isinstance(payload, dict) else []},
    )

    try:
        maestro_input = MaestroInput(**payload)
    except ValidationError as exc:
        log_event(
            LOGGER,
            event="run_flow_validation_failed",
            level="ERROR",
            run_id=run_id,
            stage="run_flow_from_maestro_payload",
            context={"error_count": len(exc.errors())},
            exc=exc,
        )
        return {
            "error": "validation_error",
            "detail": exc.errors(),
            "run_id": run_id,
            "verdict": "ERROR",
            "block_release": True,
            "request_human_review": True,
        }

    state_dict = maestro_input.to_flow_state_dict()

    try:
        flow = AgenticTestingFlow()
        flow.kickoff(inputs=state_dict)
        result = flow.state.final_run_packet or {
            "error": "Flow completed but final_run_packet is None",
            "run_id": run_id,
            "verdict": "ERROR",
            "block_release": True,
            "request_human_review": True,
        }
        log_event(
            LOGGER,
            event="run_flow_exit",
            level="INFO",
            run_id=run_id,
            stage="run_flow_from_maestro_payload",
            context={
                "result_verdict": result.get("verdict"),
                "result_status": result.get("status"),
                "has_artifacts": isinstance(result.get("artifacts"), dict),
            },
            workspace_path=flow.state.workspace_path,
        )
        return result
    except Exception as exc:
        error_message = f"{exc.__class__.__name__}: {exc}"
        log_event(
            LOGGER,
            event="run_flow_crashed",
            level="ERROR",
            run_id=run_id,
            stage="run_flow_from_maestro_payload",
            context={},
            exc=exc,
        )
        return {
            "error": error_message,
            "run_id": run_id,
            "verdict": "ERROR",
            "block_release": True,
            "request_human_review": True,
        }
