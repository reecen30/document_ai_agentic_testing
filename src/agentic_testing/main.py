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
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, ValidationError

from agentic_testing.flow import run_flow_from_maestro_payload
from agentic_testing.runtime_logging import get_runtime_logger, log_event
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
LOGGER = get_runtime_logger("main")


def _guess_run_id(value: Any) -> str:
    obj = _to_plain_obj(value)
    if isinstance(obj, dict):
        run_request = obj.get("run_request")
        if isinstance(run_request, dict):
            run_id = run_request.get("run_id")
            if isinstance(run_id, str) and run_id.strip():
                return run_id.strip()

        for wrapper_key in ("inputs", "input", "payload", "maestro_payload"):
            if wrapper_key in obj:
                nested = _guess_run_id(obj.get(wrapper_key))
                if nested != "unknown_run":
                    return nested

    return "unknown_run"


def _top_level_keys(value: Any) -> list[str]:
    obj = _to_plain_obj(value)
    if isinstance(obj, dict):
        return sorted(str(k) for k in obj.keys())
    return []


def _build_error_packet(raw_input: Any, exc: Exception, stage: str) -> dict:
    log_event(
        LOGGER,
        event="input_error",
        level="ERROR",
        run_id=_guess_run_id(raw_input),
        stage=stage,
        context={
            "detected_top_level_keys": _top_level_keys(raw_input),
            "accepted_shapes_count": 5,
        },
        exc=exc,
    )
    return {
        "run_id": _guess_run_id(raw_input),
        "status": "failed",
        "verdict": "ERROR",
        "block_release": True,
        "request_human_review": True,
        "error": {
            "type": exc.__class__.__name__,
            "message": str(exc),
            "stage": stage,
            "detected_top_level_keys": _top_level_keys(raw_input),
            "accepted_input_shapes": [
                "{run_request, scope, current_execution_artifact, previous_execution_artifact, evidence_store, storage, policy, requested_outputs}",
                "{\"maestro_payload\": <full envelope object>}",
                "{\"maestro_payload\": \"<full envelope JSON string>\"}",
                "{\"inputs\": {\"maestro_payload\": <full envelope object>}}",
                "{\"inputs\": <full envelope object>}",
            ],
        },
    }


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

    missing_sections = [k for k in _ENVELOPE_KEYS if k not in candidate]
    if missing_sections:
        raise ValueError(
            "Parsed payload is missing required top-level sections: "
            + ", ".join(missing_sections)
            + "."
        )

    try:
        return MaestroInput(**candidate).model_dump()
    except ValidationError as exc:
        # Re-raise as ValueError with concise context so downstream gets cleaner diagnostics.
        details = []
        for err in exc.errors()[:12]:
            loc = ".".join(str(x) for x in err.get("loc", []))
            msg = err.get("msg", "validation error")
            details.append(f"{loc}: {msg}")
        details_text = "; ".join(details) if details else str(exc)
        raise ValueError(f"MaestroInput validation failed: {details_text}") from exc


class MaestroSinglePayloadState(BaseModel):
    """
    Deployment state with ONE input field so AMP UI shows a single payload box.
    """

    model_config = ConfigDict(extra="allow")

    maestro_payload: Any = Field(
        default=None,
        description="Full Maestro envelope JSON as object or JSON string.",
        validation_alias=AliasChoices("maestro_payload", "inputs", "payload"),
    )


def _extract_raw_input_from_state(state: "MaestroSinglePayloadState") -> Any:
    """
    CrewAI may pass payloads in different shapes depending on UI/API/runtime wrappers.
    Prefer the explicit single field, but gracefully fall back to any extra keys
    captured by pydantic when available.
    """
    raw = _to_plain_obj(getattr(state, "maestro_payload", None))
    if not _is_effectively_empty(raw):
        return raw

    extra = getattr(state, "__pydantic_extra__", None)
    if isinstance(extra, dict) and extra:
        return _to_plain_obj(extra)

    dumped = state.model_dump(by_alias=True, exclude_none=True)
    if isinstance(dumped, dict) and dumped:
        if not (len(dumped) == 1 and _is_effectively_empty(dumped.get("maestro_payload"))):
            return _to_plain_obj(dumped)

    return raw


class AgenticTestingDeploymentFlow(Flow[MaestroSinglePayloadState]):
    """
    Deployment flow entry used by AMP.
    Exposes a SINGLE payload input and delegates execution to the real flow.
    """

    @start()
    def run_from_maestro_contract(self) -> dict:
        raw = _extract_raw_input_from_state(self.state)
        log_event(
            LOGGER,
            event="deploy_start_received",
            level="INFO",
            run_id=_guess_run_id(raw),
            stage="run_from_maestro_contract",
            context={"detected_top_level_keys": _top_level_keys(raw)},
        )
        try:
            validated_payload = _normalize_maestro_payload(raw)
            log_event(
                LOGGER,
                event="payload_normalized",
                level="INFO",
                run_id=validated_payload.get("run_request", {}).get("run_id"),
                stage="run_from_maestro_contract",
                context={"sections": sorted(validated_payload.keys())},
            )
            return run_flow_from_maestro_payload(validated_payload)
        except Exception as exc:
            return _build_error_packet(raw, exc, stage="run_from_maestro_contract")


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
            log_event(
                LOGGER,
                event="kickoff_input_from_env",
                level="INFO",
                stage="kickoff",
                context={"env_source": "CREWAI_INPUT/MAESTRO_PAYLOAD"},
            )
        else:
            raise ValueError(
                "No input provided. Pass a MaestroInput dict/JSON via `inputs` arg, "
                "CREWAI_INPUT env var, or MAESTRO_PAYLOAD env var."
            )

    try:
        # Normalize supported input shapes:
        # - full payload dict
        # - JSON string payload
        # - {"maestro_payload": <payload>}
        inputs = _normalize_maestro_payload(inputs)
        log_event(
            LOGGER,
            event="kickoff_payload_normalized",
            level="INFO",
            run_id=inputs.get("run_request", {}).get("run_id"),
            stage="kickoff.normalize",
            context={"sections": sorted(inputs.keys())},
        )
    except Exception as exc:
        return _build_error_packet(inputs, exc, stage="kickoff.normalize")

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

    try:
        result = run_flow_from_maestro_payload(inputs)
        log_event(
            LOGGER,
            event="kickoff_completed",
            level="INFO",
            run_id=result.get("run_id") if isinstance(result, dict) else inputs.get("run_request", {}).get("run_id"),
            stage="kickoff.run_flow",
            context={"result_keys": sorted(result.keys()) if isinstance(result, dict) else []},
        )
        return result
    except Exception as exc:
        return _build_error_packet(inputs, exc, stage="kickoff.run_flow")


if __name__ == "__main__":
    # Allow: python -m agentic_testing.main '{"run_request": ...}'
    if len(sys.argv) > 1:
        result = kickoff(inputs=sys.argv[1])
    else:
        from dotenv import load_dotenv
        load_dotenv()
        result = kickoff()
    print(json.dumps(result, indent=2, default=str))
