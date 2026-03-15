"""
FastAPI deployment surface for UiPath and external orchestrators.

Usage:
    uvicorn agentic_testing.api:app --host 0.0.0.0 --port 8080
"""
from __future__ import annotations

import os
from typing import Dict, Any

from fastapi import Depends, FastAPI, Header, HTTPException, status

from .flow import run_flow_from_maestro_payload
from .schemas.deploy_contract import UiPathRunOutput, normalize_uipath_output
from .schemas.maestro_input import MaestroInput


TOKEN_ENV_VAR = "AGENTIC_API_TOKEN"


app = FastAPI(
    title="Document AI Agentic Testing API",
    version="1.0.0",
    description=(
        "Token-protected API for running Document AI agentic tests.\n\n"
        "Input contract: MaestroInput\n"
        "Output contract: UiPathRunOutput"
    ),
)


def verify_bearer_token(authorization: str | None = Header(default=None)) -> None:
    """
    Require Authorization: Bearer <AGENTIC_API_TOKEN>.
    """
    expected = os.getenv(TOKEN_ENV_VAR, "").strip()
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"{TOKEN_ENV_VAR} is not configured on the server.",
        )

    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header.",
        )

    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header must be in the form: Bearer <token>.",
        )

    provided = parts[1].strip()
    if provided != expected:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid token.",
        )


@app.get("/health")
def health() -> Dict[str, Any]:
    return {
        "status": "ok",
        "service": "document_ai_agentic_testing",
        "token_required": True,
        "token_env_var": TOKEN_ENV_VAR,
    }


@app.get("/contract/input")
def input_contract(_: None = Depends(verify_bearer_token)) -> Dict[str, Any]:
    return MaestroInput.model_json_schema()


@app.get("/contract/output")
def output_contract(_: None = Depends(verify_bearer_token)) -> Dict[str, Any]:
    return UiPathRunOutput.model_json_schema()


@app.post("/run", response_model=UiPathRunOutput)
def run(payload: MaestroInput, _: None = Depends(verify_bearer_token)) -> UiPathRunOutput:
    packet = run_flow_from_maestro_payload(payload.model_dump())
    return normalize_uipath_output(packet)
