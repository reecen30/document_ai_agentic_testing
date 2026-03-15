"""
CrewAI Flow state — shared mutable state object passed between all flow steps.
"""
from __future__ import annotations
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class FlowState(BaseModel):
    # ── Input section ─────────────────────────────────────────────────────────
    run_id: str = ""
    run_request: Dict[str, Any] = Field(default_factory=dict)
    scope: Dict[str, Any] = Field(default_factory=dict)
    current_artifact: Dict[str, Any] = Field(default_factory=dict)
    previous_artifact: Dict[str, Any] = Field(default_factory=dict)
    evidence_store_config: Dict[str, Any] = Field(default_factory=dict)
    storage_config: Dict[str, Any] = Field(default_factory=dict)
    policy: Dict[str, Any] = Field(default_factory=dict)
    requested_outputs: Dict[str, Any] = Field(default_factory=dict)

    # ── Agent outputs ──────────────────────────────────────────────────────────
    # IntakeDiff
    change_summary: Optional[Dict[str, Any]] = None
    initial_risk_hypotheses: Optional[List[Dict[str, Any]]] = None

    # ScopePlanner
    selected_transaction_ids: Optional[List[int]] = None
    selected_doc_types: Optional[List[str]] = None
    analysis_plan: Optional[Dict[str, Any]] = None

    # EvidenceCollector
    case_bundles: Optional[List[Dict[str, Any]]] = None
    evidence_summary: Optional[Dict[str, Any]] = None

    # RegressionHunter
    improvement_findings: Optional[List[Dict[str, Any]]] = None
    regression_findings: Optional[List[Dict[str, Any]]] = None
    hidden_risk_findings: Optional[List[Dict[str, Any]]] = None
    summary_metrics: Optional[Dict[str, Any]] = None
    doc_type_breakdown: Optional[Dict[str, Any]] = None

    # Challenger
    confidence_assessment: Optional[Dict[str, Any]] = None
    needs_more_evidence: bool = False
    challenge_notes: Optional[List[str]] = None

    # TargetedRerun
    targeted_rerun_summary: Optional[Dict[str, Any]] = None
    scope_expansion_request: Optional[Dict[str, Any]] = None

    # TrendDrift
    trend_summary: Optional[Dict[str, Any]] = None
    drift_alerts: Optional[List[Dict[str, Any]]] = None
    trend_direction: Optional[str] = None
    trend_confidence: Optional[float] = None

    # RootCause
    root_causes: Optional[List[Dict[str, Any]]] = None

    # PatchProposal
    patch_candidates: Optional[List[Dict[str, Any]]] = None
    recommended_experiments: Optional[List[str]] = None
    patch_rationale: Optional[str] = None

    # ReportRouting
    final_run_packet: Optional[Dict[str, Any]] = None

    # ── Run metadata ───────────────────────────────────────────────────────────
    rerun_count: int = 0
    workspace_path: Optional[str] = None
    audit_events: List[Dict[str, Any]] = Field(default_factory=list)
    start_datetime: Optional[str] = None
    end_datetime: Optional[str] = None
    error_log: List[str] = Field(default_factory=list)

    def add_audit_event(self, agent_name: str, event_type: str, summary: str, status: str = "OK") -> None:
        import datetime
        self.audit_events.append({
            "run_id": self.run_id,
            "agent_name": agent_name,
            "event_type": event_type,
            "timestamp": datetime.datetime.utcnow().isoformat(),
            "summary": summary,
            "status": status,
        })
