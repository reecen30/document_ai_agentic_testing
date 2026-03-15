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


def _normalize_maestro_payload(raw_payload: Any) -> dict:
    """
    Accept either:
      1) full Maestro payload dict
      2) JSON string of full Maestro payload
      3) wrapper {"maestro_payload": <dict-or-json-string>}
    and return a validated Maestro payload dict.
    """
    payload = raw_payload

    if isinstance(payload, dict) and "maestro_payload" in payload and len(payload.keys()) == 1:
        payload = payload["maestro_payload"]

    if isinstance(payload, str):
        payload = payload.strip()
        if not payload:
            raise ValueError("maestro_payload is empty.")
        payload = json.loads(payload)

    if not isinstance(payload, dict):
        raise ValueError("maestro_payload must be a JSON object or JSON string.")

    return MaestroInput(**payload).model_dump()


class MaestroSinglePayloadState(BaseModel):
    """
    Deployment state with ONE input field so AMP UI shows a single payload box.
    """

    maestro_payload: Any = Field(
        default_factory=dict,
        description="Full Maestro envelope JSON as object or JSON string.",
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
