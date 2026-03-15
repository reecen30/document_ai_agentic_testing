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
from collections.abc import Mapping
from typing import Any

from crewai.flow.flow import Flow, start
from pydantic import AliasChoices, BaseModel, Field

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


def _to_plain_obj(value: Any) -> Any:
    """
    Convert mapping-proxy style objects (e.g., LockedDictProxy) into plain Python
    dict/list primitives so validation behaves consistently.
    """
    parsed = _try_parse_json_string(value)
    if isinstance(parsed, Mapping):
        return {str(k): _to_plain_obj(v) for k, v in parsed.items()}
    if isinstance(parsed, list):
        return [_to_plain_obj(v) for v in parsed]
    if isinstance(parsed, tuple):
        return [_to_plain_obj(v) for v in parsed]
    return parsed


def _is_effectively_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    if isinstance(value, Mapping):
        return len(value) == 0
    if isinstance(value, (list, tuple, set)):
        return len(value) == 0
    return False


def _has_any_meaningful_envelope_value(envelope: dict) -> bool:
    for key in _ENVELOPE_KEYS:
        if key in envelope and not _is_effectively_empty(envelope.get(key)):
            return True
    return False


def _extract_payload_from_split_fields(source: dict) -> dict:
    """
    Extract legacy split fields from CrewAI training UI into one Maestro envelope.
    Supports each field as either object or JSON string.
    """
    candidate: dict = {}
    for key in _ENVELOPE_KEYS:
        if key in source:
            value = _to_plain_obj(source.get(key))
            if not _is_effectively_empty(value):
                candidate[key] = value
    return candidate


def _unwrap_envelope_wrappers(raw_payload: Any) -> Any:
    """
    Unwrap common transport wrappers used by different callers.
    Handles repeated nesting like:
      {"inputs": {"maestro_payload": {...}}}
      {"maestro_payload": {...}}
      {"inputs": {...full envelope...}}
    """
    current = _to_plain_obj(raw_payload)
    for _ in range(5):
        if not isinstance(current, dict):
            return current
        if "inputs" in current and len(current.keys()) == 1:
            current = _to_plain_obj(current.get("inputs"))
            continue
        if "input" in current and len(current.keys()) == 1:
            current = _to_plain_obj(current.get("input"))
            continue
        if "payload" in current and len(current.keys()) == 1:
            current = _to_plain_obj(current.get("payload"))
            continue
        if "maestro_payload" in current and len(current.keys()) == 1:
            current = _to_plain_obj(current.get("maestro_payload"))
            continue
        break
    return current


def _normalize_maestro_payload(raw_payload: Any) -> dict:
    """
    Accept either:
      1) full Maestro payload dict
      2) JSON string of full Maestro payload
      3) wrapper {"maestro_payload": <dict-or-json-string>}
    and return a validated Maestro payload dict.
    """
    payload = _unwrap_envelope_wrappers(raw_payload)

    if not isinstance(payload, dict):
        raise ValueError(
            "Input must be a JSON object/string OR {\"maestro_payload\": <json object/string>}."
        )

    wrapped_payload = _to_plain_obj(payload.get("maestro_payload"))

    candidate: dict = {}

    # Preferred: one-field wrapper.
    if isinstance(wrapped_payload, dict) and _has_any_meaningful_envelope_value(wrapped_payload):
        candidate = wrapped_payload
    # Direct full envelope passed at root.
    elif all(k in payload for k in _ENVELOPE_KEYS) and _has_any_meaningful_envelope_value(payload):
        candidate = {k: _to_plain_obj(payload.get(k)) for k in _ENVELOPE_KEYS}
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
        validation_alias=AliasChoices("maestro_payload", "inputs", "payload"),
    )


class AgenticTestingDeploymentFlow(Flow[MaestroSinglePayloadState]):
    """
    Deployment flow entry used by AMP.
    Exposes a SINGLE payload input and delegates execution to the real flow.
    """

    @start()
    def run_from_maestro_contract(self) -> dict:
        validated_payload = _normalize_maestro_payload(self.state.maestro_payload)
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
