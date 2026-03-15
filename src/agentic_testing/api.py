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
from .runtime_logging import get_runtime_logger, log_event
from .schemas.deploy_contract import UiPathRunOutput, normalize_uipath_output
from .schemas.maestro_input import MaestroInput


TOKEN_ENV_VAR = "AGENTIC_API_TOKEN"
LOGGER = get_runtime_logger("api")


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
        log_event(
            LOGGER,
            event="api_auth_config_missing",
            level="ERROR",
            stage="verify_bearer_token",
            context={"token_env_var": TOKEN_ENV_VAR},
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"{TOKEN_ENV_VAR} is not configured on the server.",
        )

    if not authorization:
        log_event(LOGGER, event="api_auth_missing_header", level="WARNING", stage="verify_bearer_token", context={})
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header.",
        )

    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        log_event(LOGGER, event="api_auth_bad_format", level="WARNING", stage="verify_bearer_token", context={})
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header must be in the form: Bearer <token>.",
        )

    provided = parts[1].strip()
    if provided != expected:
        log_event(LOGGER, event="api_auth_invalid_token", level="WARNING", stage="verify_bearer_token", context={})
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
    run_id = payload.run_request.run_id
    log_event(
        LOGGER,
        event="api_run_received",
        level="INFO",
        run_id=run_id,
        stage="/run",
        context={"has_scope": bool(payload.scope), "requested_outputs": payload.requested_outputs.model_dump()},
    )
    try:
        packet = run_flow_from_maestro_payload(payload.model_dump())
        output = normalize_uipath_output(packet)
        log_event(
            LOGGER,
            event="api_run_completed",
            level="INFO",
            run_id=run_id,
            stage="/run",
            context={"status": output.status, "verdict": output.verdict},
        )
        return output
    except Exception as exc:
        log_event(
            LOGGER,
            event="api_run_failed",
            level="ERROR",
            run_id=run_id,
            stage="/run",
            context={},
            exc=exc,
        )
        raise HTTPException(status_code=500, detail=f"Run failed: {exc.__class__.__name__}: {exc}") from exc
