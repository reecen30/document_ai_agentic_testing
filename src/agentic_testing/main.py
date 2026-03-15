"""
agentic_testing/main.py

CrewAI cloud entry point.

When deployed on CrewAI+, the platform calls `kickoff()` with an `inputs` dict.
The input may arrive as:
  - a dict (standard CrewAI)
  - a JSON string (Maestro/webhook passthrough)

This module handles both.
"""
import json
import os
import sys
from typing import Any

from crewai.flow.flow import Flow, start
from pydantic import BaseModel, Field

from agentic_testing.flow import run_flow_from_maestro_payload
from agentic_testing.schemas.maestro_input import MaestroInput


_ENVELOPE_KEYS = (
    "run_request",
    "scope",
    "current_execution_artifact",
    "previous_execution_artifact",
    "evidence_store",
    "storage",
    "policy",
    "requested_outputs",
)


def _try_parse_json_string(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text:
        return value
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return value


def _extract_payload_from_split_fields(source: dict) -> dict:
    """
    Extract legacy split fields from CrewAI training UI into one Maestro envelope.
    Supports each field as either object or JSON string.
    """
    candidate: dict = {}
    for key in _ENVELOPE_KEYS:
        if key in source:
            candidate[key] = _try_parse_json_string(source.get(key))
    return candidate


def _normalize_maestro_payload(raw_payload: Any) -> dict:
    """
    Accept either:
      1) full Maestro payload dict
      2) JSON string of full Maestro payload
      3) wrapper {"maestro_payload": <dict-or-json-string>}
    and return a validated Maestro payload dict.
    """
    payload = _try_parse_json_string(raw_payload)

    if not isinstance(payload, dict):
        raise ValueError(
            "Input must be a JSON object/string OR {\"maestro_payload\": <json object/string>}."
        )

    wrapped_value = payload.get("maestro_payload")
    wrapped_payload = _try_parse_json_string(wrapped_value)

    candidate: dict = {}

    # Preferred: one-field wrapper.
    if isinstance(wrapped_payload, dict) and wrapped_payload:
        candidate = wrapped_payload
    # Direct full envelope passed at root.
    elif all(k in payload for k in _ENVELOPE_KEYS):
        candidate = {k: _try_parse_json_string(payload.get(k)) for k in _ENVELOPE_KEYS}
    # Legacy split fields in UI (some or all keys present at root).
    else:
        candidate = _extract_payload_from_split_fields(payload)

    if not candidate:
        raise ValueError(
            "No valid Maestro payload found. Provide either:\n"
            "1) full envelope JSON,\n"
            "2) {\"maestro_payload\": <full envelope>}, or\n"
            "3) legacy split fields (run_request, scope, ... requested_outputs)."
        )

    return MaestroInput(**candidate).model_dump()


class MaestroSinglePayloadState(BaseModel):
    """
    Deployment state with ONE input field so AMP UI shows a single payload box.
    """

    maestro_payload: Any = Field(
        default=None,
        description="Full Maestro envelope JSON as object or JSON string.",
    )
    # Backward compatibility if old deployment UI still sends split fields.
    run_request: Any = Field(default_factory=dict)
    scope: Any = Field(default_factory=dict)
    current_execution_artifact: Any = Field(default_factory=dict)
    previous_execution_artifact: Any = Field(default_factory=dict)
    evidence_store: Any = Field(default_factory=dict)
    storage: Any = Field(default_factory=dict)
    policy: Any = Field(default_factory=dict)
    requested_outputs: Any = Field(default_factory=dict)


class AgenticTestingDeploymentFlow(Flow[MaestroSinglePayloadState]):
    """
    Deployment flow entry used by AMP.
    Exposes a SINGLE payload input and delegates execution to the real flow.
    """

    @start()
    def run_from_maestro_contract(self) -> dict:
        raw_inputs = {
            "maestro_payload": self.state.maestro_payload,
            "run_request": self.state.run_request,
            "scope": self.state.scope,
            "current_execution_artifact": self.state.current_execution_artifact,
            "previous_execution_artifact": self.state.previous_execution_artifact,
            "evidence_store": self.state.evidence_store,
            "storage": self.state.storage,
            "policy": self.state.policy,
            "requested_outputs": self.state.requested_outputs,
        }
        validated_payload = _normalize_maestro_payload(raw_inputs)
        return run_flow_from_maestro_payload(validated_payload)


def kickoff(inputs=None):
    """
    CrewAI cloud entry point.

    Args:
        inputs: dict or JSON string containing the MaestroInput payload.
                If None, falls back to CREWAI_INPUT env var or raises.

    Returns:
        dict: The final routing packet from the flow.
    """
    # Resolve payload from various sources
    if inputs is None:
        env_input = os.getenv("CREWAI_INPUT") or os.getenv("MAESTRO_PAYLOAD")
        if env_input:
            inputs = env_input
        else:
            raise ValueError(
                "No input provided. Pass a MaestroInput dict/JSON via `inputs` arg, "
                "CREWAI_INPUT env var, or MAESTRO_PAYLOAD env var."
            )

    # Normalize supported input shapes:
    # - full payload dict
    # - JSON string payload
    # - {"maestro_payload": <payload>}
    inputs = _normalize_maestro_payload(inputs)

    # Set workspace base path if not already configured
    if not os.getenv("AGENTIC_LLM_PROVIDER"):
        # AMP/cloud-safe default. Override to `ollama` for local-only runs.
        os.environ["AGENTIC_LLM_PROVIDER"] = "groq"
    if not os.getenv("WORKSPACE_BASE_PATH"):
        os.environ["WORKSPACE_BASE_PATH"] = os.path.join(
            os.path.dirname(__file__), "..", "..", "workspaces"
        )
    if not os.getenv("EVIDENCE_STORE_PATH"):
        os.environ["EVIDENCE_STORE_PATH"] = os.path.join(
            os.path.dirname(__file__), "..", "..", "data", "DocumentAI_EvidenceStore.xlsx"
        )

    return run_flow_from_maestro_payload(inputs)


if __name__ == "__main__":
    # Allow: python -m agentic_testing.main '{"run_request": ...}'
    if len(sys.argv) > 1:
        result = kickoff(inputs=sys.argv[1])
    else:
        from dotenv import load_dotenv
        load_dotenv()
        result = kickoff()
    print(json.dumps(result, indent=2, default=str))
