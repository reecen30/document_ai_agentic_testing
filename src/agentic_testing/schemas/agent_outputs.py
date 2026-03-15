"""
Per-agent structured output types.
Each agent task returns JSON matching one of these models.
"""
from __future__ import annotations
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class ArtifactDiffItem(BaseModel):
    section: str
    change_type: str  # added | removed | modified
    description: str
    risk_level: str = "medium"  # low | medium | high


class ChangeSummaryOutput(BaseModel):
    prompt_changed: bool
    model_changed: bool
    artifact_diff_summary: List[str] = Field(default_factory=list)
    artifact_diff_details: List[ArtifactDiffItem] = Field(default_factory=list)
    initial_risk_hypotheses: List[Dict[str, Any]] = Field(default_factory=list)
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)


class ScopePlanOutput(BaseModel):
    selected_transaction_ids: List[int]
    selected_doc_types: List[str]
    analysis_plan: Dict[str, Any]
    scope_rationale: str
    initial_transaction_count: int
    expansion_allowed: bool = True


# Backward-compatible alias used by legacy imports/tests.
class ScopePlannerOutput(ScopePlanOutput):
    pass


class CaseBundle(BaseModel):
    transaction_id: int
    document_id: str
    doc_type_truth: Optional[str] = None
    doc_type_baseline: Optional[str] = None
    doc_type_candidate: Optional[str] = None
    baseline_classification_confidence: Optional[float] = None
    candidate_classification_confidence: Optional[float] = None
    fields_baseline: List[Dict[str, Any]] = Field(default_factory=list)
    fields_candidate: List[Dict[str, Any]] = Field(default_factory=list)
    fields_truth: List[Dict[str, Any]] = Field(default_factory=list)
    exceptions: List[Dict[str, Any]] = Field(default_factory=list)
    api_calls: List[Dict[str, Any]] = Field(default_factory=list)


class EvidenceSummaryOutput(BaseModel):
    case_bundles: List[Dict[str, Any]]
    total_transactions: int
    doc_type_distribution: Dict[str, int]
    evidence_quality_note: str
    missing_truth_count: int = 0
    missing_candidate_count: int = 0


class FindingItem(BaseModel):
    transaction_id: Optional[int] = None
    doc_type: Optional[str] = None
    field: Optional[str] = None
    finding_type: str  # improvement | regression | hidden_risk
    description: str
    severity: str = "medium"  # low | medium | high | critical
    confidence: float = Field(default=0.75, ge=0.0, le=1.0)
    evidence_ref: Optional[str] = None


class RegressionHunterOutput(BaseModel):
    improvement_findings: List[Dict[str, Any]]
    regression_findings: List[Dict[str, Any]]
    hidden_risk_findings: List[Dict[str, Any]]
    summary_metrics: Dict[str, Any]
    doc_type_breakdown: Dict[str, Any]


class ChallengerOutput(BaseModel):
    confidence_assessment: Dict[str, Any]
    needs_more_evidence: bool
    challenge_notes: List[str]
    sample_size_adequate: bool
    label_noise_concern: bool
    recommended_expansion: Optional[str] = None


class TargetedRerunOutput(BaseModel):
    targeted_rerun_summary: Dict[str, Any]
    scope_expansion_request: Dict[str, Any]
    transactions_added: List[int]
    expansion_rationale: str
    rerun_findings: List[Dict[str, Any]]


class TrendDriftOutput(BaseModel):
    trend_summary: Dict[str, Any]
    drift_alerts: List[Dict[str, Any]]
    trend_direction: str  # improving | declining | plateau | sudden_regression | converging
    trend_confidence: float = Field(default=0.7, ge=0.0, le=1.0)


class RootCauseItem(BaseModel):
    cause: str
    cause_type: str  # prompt | model | label | evidence | configuration
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)
    supporting_evidence: List[str] = Field(default_factory=list)


class RootCauseOutput(BaseModel):
    root_causes: List[Dict[str, Any]]
    primary_cause: Optional[str] = None
    confidence: float = Field(default=0.75, ge=0.0, le=1.0)


class PatchCandidateItem(BaseModel):
    patch_id: str
    patch_type: str  # prompt | model | benchmark | experiment
    target: str
    description: str
    proposed_change: Optional[str] = None
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)
    requires_human_approval: bool = True
    priority: str = "medium"  # low | medium | high | critical


class PatchProposalOutput(BaseModel):
    patch_candidates: List[Dict[str, Any]]
    recommended_experiments: List[str]
    patch_rationale: str


class RoutingDecision(BaseModel):
    block_release: bool
    request_human_review: bool
    open_defect: bool
    notify_roles: List[str]
    verdict: str  # PASS | WARN | BLOCK
    verdict_rationale: str


class FinalRoutingOutput(BaseModel):
    run_id: str
    status: str = "COMPLETED"
    verdict: str
    confidence: float
    analysis_scope: Dict[str, Any]
    change_summary: Dict[str, Any]
    summary_metrics: Dict[str, Any]
    improvements: List[str]
    regressions: List[str]
    hidden_risks: List[str]
    root_causes: List[Dict[str, Any]]
    agentic_actions_taken: List[str]
    recommended_actions: List[str]
    patch_candidates: List[Dict[str, Any]]
    routing: Dict[str, Any]
    artifacts: Dict[str, str]
