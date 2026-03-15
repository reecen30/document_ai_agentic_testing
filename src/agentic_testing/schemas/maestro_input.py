"""
Maestro → CrewAI input contract.
This is the single payload envelope Maestro sends when triggering the agentic testing flow.
"""
from __future__ import annotations
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class RunRequest(BaseModel):
    run_id: str = Field(..., description="Unique run identifier, e.g. RUN-2026-03-14-001")
    process_name: str = Field(default="document_ai_agentic_testing")
    run_mode: str = Field(default="release_candidate", description="release_candidate | scheduled | manual")
    analysis_mode: str = Field(default="agentic_investigation")
    time_budget_minutes: int = Field(default=20)
    max_initial_transactions: int = Field(default=20)
    max_total_transactions: int = Field(default=100)
    max_targeted_reruns: int = Field(default=3)
    triggered_by: str = Field(default="Maestro")


class ScopeConfig(BaseModel):
    date_from: str = Field(..., description="ISO date string YYYY-MM-DD")
    date_to: str = Field(..., description="ISO date string YYYY-MM-DD")
    transaction_ids: List[int] = Field(default_factory=list, description="If empty, agent selects")
    document_type_names: List[str] = Field(default_factory=list, description="If empty, agent selects")
    process_stage_ids: List[int] = Field(default_factory=lambda: [1, 2, 3, 4])
    allow_agent_to_expand_scope: bool = Field(default=True)


class ExecutionArtifact(BaseModel):
    prompt_name: str
    prompt_version_label: str
    prompt_text: str = Field(..., description="Full resolved prompt text")
    model_name: str = Field(..., description="e.g. deepseek-r1:8b")
    artifact_hash: str = Field(..., description="sha256 of the artifact")


class EvidenceStoreConfig(BaseModel):
    store_type: str = Field(default="excel")
    store_ref: str = Field(..., description="Logical name or file path to the evidence workbook")
    sheet_names: Dict[str, str] = Field(
        default_factory=lambda: {
            "document_data": "DocumentData",
            "model_data": "ai.ModelData",
            "document_types": "DocumentTypes",
            "process_stages": "ProcessStages",
            "model_names": "ai.ModelNames",
            "model_stages": "ai.ModelStages",
            "model_types": "ai.ModelTypes",
            "exception_logs": "ExceptionLogs",
            "api_data": "api.APIData",
        }
    )


class StorageConfig(BaseModel):
    artifact_namespace: str = Field(default="agentic-testing")
    run_workspace_key: str
    output_mode: str = Field(default="managed_workspace")
    workspace_base_path: Optional[str] = Field(default=None, description="Local base path for workspaces")


class PolicyConfig(BaseModel):
    critical_doc_types: List[str] = Field(
        default_factory=lambda: ["IdentityDocument", "Passport", "ApplicationForm"]
    )
    warn_weighted_f1_drop: float = Field(default=0.02)
    block_weighted_f1_drop: float = Field(default=0.05)
    block_empty_rate_increase: float = Field(default=0.03)
    block_exception_rate_increase: float = Field(default=0.02)


class RequestedOutputs(BaseModel):
    pdf_report: bool = True
    html_report: bool = True
    excel_log: bool = True
    json_packet: bool = True
    trace_pack: bool = True
    patch_candidates: bool = True
    audit_log_excel: bool = True


class MaestroInput(BaseModel):
    """
    Full input envelope from Maestro → CrewAI flow.
    """
    run_request: RunRequest
    scope: ScopeConfig
    current_execution_artifact: ExecutionArtifact
    previous_execution_artifact: ExecutionArtifact
    evidence_store: EvidenceStoreConfig
    storage: StorageConfig
    policy: PolicyConfig
    requested_outputs: RequestedOutputs

    def to_flow_state_dict(self) -> Dict[str, Any]:
        """Convert to flat dict for FlowState initialisation."""
        return {
            "run_id": self.run_request.run_id,
            "run_request": self.run_request.model_dump(),
            "scope": self.scope.model_dump(),
            "current_artifact": self.current_execution_artifact.model_dump(),
            "previous_artifact": self.previous_execution_artifact.model_dump(),
            "evidence_store_config": self.evidence_store.model_dump(),
            "storage_config": self.storage.model_dump(),
            "policy": self.policy.model_dump(),
            "requested_outputs": self.requested_outputs.model_dump(),
        }
