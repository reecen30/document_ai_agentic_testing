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

from crewai.flow.flow import Flow, start
from pydantic import BaseModel, Field

from agentic_testing.flow import run_flow_from_maestro_payload
from agentic_testing.schemas.maestro_input import MaestroInput


class MaestroEnvelopeState(BaseModel):
    """
    Slim deployment state so AMP exposes only the intended input envelope fields.
    """

    run_request: dict = Field(default_factory=dict)
    scope: dict = Field(default_factory=dict)
    current_execution_artifact: dict = Field(default_factory=dict)
    previous_execution_artifact: dict = Field(default_factory=dict)
    evidence_store: dict = Field(default_factory=dict)
    storage: dict = Field(default_factory=dict)
    policy: dict = Field(default_factory=dict)
    requested_outputs: dict = Field(default_factory=dict)


class AgenticTestingDeploymentFlow(Flow[MaestroEnvelopeState]):
    """
    Deployment flow entry used by AMP.
    Exposes a clean Maestro envelope and delegates execution to the real flow.
    """

    @start()
    def run_from_maestro_contract(self) -> dict:
        payload = {
            "run_request": self.state.run_request,
            "scope": self.state.scope,
            "current_execution_artifact": self.state.current_execution_artifact,
            "previous_execution_artifact": self.state.previous_execution_artifact,
            "evidence_store": self.state.evidence_store,
            "storage": self.state.storage,
            "policy": self.state.policy,
            "requested_outputs": self.state.requested_outputs,
        }

        # Validate envelope shape before deeper flow execution.
        validated_payload = MaestroInput(**payload).model_dump()
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

    # Parse JSON string if needed
    if isinstance(inputs, str):
        inputs = json.loads(inputs)

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
