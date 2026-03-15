"""
Deployment-facing contracts for UiPath integration.
"""
from __future__ import annotations

from typing import Any, Dict, List, Literal

from pydantic import BaseModel, Field


VerdictType = Literal["PASS", "WARN", "BLOCK", "ERROR"]


class UiPathRunOutput(BaseModel):
    """
    Stable output contract returned by the deployment API.
    """

    run_id: str
    status: str = "completed"
    verdict: VerdictType = "ERROR"
    confidence: float = 0.0
    block_release: bool = False
    request_human_review: bool = False
    open_defect: bool = False
    notify_roles: List[str] = Field(default_factory=list)
    summary_metrics: Dict[str, Any] = Field(default_factory=dict)
    regression_count: int = 0
    improvement_count: int = 0
    hidden_risk_count: int = 0
    artifact_uris: Dict[str, str] = Field(default_factory=dict)
    message: str = ""
    raw_packet: Dict[str, Any] = Field(default_factory=dict)


def normalize_uipath_output(packet: Dict[str, Any]) -> UiPathRunOutput:
    """
    Normalize heterogeneous internal packet shapes to a single UiPath-friendly contract.
    """
    routing = packet.get("routing", {}) if isinstance(packet.get("routing"), dict) else {}
    verdict_raw = (packet.get("verdict") or routing.get("verdict") or "ERROR")
    verdict = str(verdict_raw).upper()
    if verdict not in {"PASS", "WARN", "BLOCK", "ERROR"}:
        verdict = "ERROR"

    artifacts = packet.get("artifact_uris") or packet.get("artifacts") or {}
    if not isinstance(artifacts, dict):
        artifacts = {}

    regressions = packet.get("regressions")
    if not isinstance(regressions, list):
        regressions = packet.get("regression_findings", [])
    improvements = packet.get("improvements")
    if not isinstance(improvements, list):
        improvements = packet.get("improvement_findings", [])
    hidden = packet.get("hidden_risks")
    if not isinstance(hidden, list):
        hidden = packet.get("hidden_risk_findings", [])

    top_notify_roles = packet.get("notify_roles")
    if not isinstance(top_notify_roles, list):
        top_notify_roles = routing.get("notify_roles", [])

    confidence = packet.get("confidence")
    if confidence is None:
        confidence = packet.get("confidence_assessment", {}).get("overall_confidence", 0.0)

    return UiPathRunOutput(
        run_id=str(packet.get("run_id", "unknown_run")),
        status=str(packet.get("status", "completed")).lower(),
        verdict=verdict,  # type: ignore[arg-type]
        confidence=float(confidence or 0.0),
        block_release=bool(packet.get("block_release", routing.get("block_release", verdict in {"BLOCK", "ERROR"}))),
        request_human_review=bool(
            packet.get("request_human_review", routing.get("request_human_review", verdict in {"WARN", "BLOCK", "ERROR"}))
        ),
        open_defect=bool(packet.get("open_defect", routing.get("open_defect", verdict == "BLOCK"))),
        notify_roles=[str(r) for r in top_notify_roles] if isinstance(top_notify_roles, list) else [],
        summary_metrics=packet.get("summary_metrics", {}) if isinstance(packet.get("summary_metrics"), dict) else {},
        regression_count=len(regressions) if isinstance(regressions, list) else int(packet.get("regression_count", 0) or 0),
        improvement_count=len(improvements) if isinstance(improvements, list) else int(packet.get("improvement_count", 0) or 0),
        hidden_risk_count=len(hidden) if isinstance(hidden, list) else int(packet.get("hidden_risk_count", 0) or 0),
        artifact_uris={str(k): str(v) for k, v in artifacts.items()},
        message=str(packet.get("error", "")),
        raw_packet=packet if isinstance(packet, dict) else {"raw": str(packet)},
    )
