# Deploying for UiPath (URL, Token, Inputs, Outputs)

This guide gives you a deploy-ready API contract for UiPath.

## 1) Start the API

Set your token first:

```powershell
$env:AGENTIC_API_TOKEN = "replace-with-strong-token"
```

Start server:

```powershell
python main.py --serve-api --port 8080
```

## 2) URL Endpoints

Base URL (local example):

```text
http://localhost:8080
```

Available endpoints:

- `GET /health`
- `GET /docs` (Swagger UI)
- `GET /openapi.json` (full schema)
- `GET /contract/input` (input schema only)
- `GET /contract/output` (output schema only)
- `POST /run` (execute flow)

## 3) Token Auth

All contract and run endpoints require:

```http
Authorization: Bearer <AGENTIC_API_TOKEN>
Content-Type: application/json
```

If token is missing/invalid:

- `401` missing or malformed auth header
- `403` invalid token

## 4) Input Contract (for UiPath request body)

`POST /run` expects the `MaestroInput` schema.

Top-level required fields:

- `run_request`
- `scope`
- `current_execution_artifact`
- `previous_execution_artifact`
- `evidence_store`
- `storage`
- `policy`
- `requested_outputs`

Minimal valid payload shape:

```json
{
  "run_request": {
    "run_id": "RUN-2026-03-15-001",
    "process_name": "document_ai_agentic_testing"
  },
  "scope": {
    "date_from": "2026-03-01",
    "date_to": "2026-03-15"
  },
  "current_execution_artifact": {
    "prompt_name": "classification_extraction_bundle",
    "prompt_version_label": "bundle_v17",
    "prompt_text": "prompt text here",
    "model_name": "deepseek-r1:8b",
    "artifact_hash": "sha256-current"
  },
  "previous_execution_artifact": {
    "prompt_name": "classification_extraction_bundle",
    "prompt_version_label": "bundle_v16",
    "prompt_text": "previous prompt text here",
    "model_name": "deepseek-r1:8b",
    "artifact_hash": "sha256-previous"
  },
  "evidence_store": {
    "store_type": "excel",
    "store_ref": "DocumentAI_EvidenceStore"
  },
  "storage": {
    "artifact_namespace": "agentic-testing",
    "run_workspace_key": "RUN-2026-03-15-001"
  },
  "policy": {},
  "requested_outputs": {}
}
```

## 5) Output Contract (for UiPath response parsing)

`POST /run` returns `UiPathRunOutput`:

- `run_id` (string)
- `status` (string)
- `verdict` (`PASS | WARN | BLOCK | ERROR`)
- `confidence` (number)
- `block_release` (bool)
- `request_human_review` (bool)
- `open_defect` (bool)
- `notify_roles` (array)
- `summary_metrics` (object)
- `regression_count` (number)
- `improvement_count` (number)
- `hidden_risk_count` (number)
- `artifact_uris` (object)
- `message` (string; populated on errors)
- `raw_packet` (full internal packet for traceability)

Example response:

```json
{
  "run_id": "RUN-2026-03-15-001",
  "status": "completed",
  "verdict": "WARN",
  "confidence": 0.81,
  "block_release": false,
  "request_human_review": true,
  "open_defect": false,
  "notify_roles": ["qa_lead"],
  "summary_metrics": {
    "weighted_f1_delta": -0.02
  },
  "regression_count": 2,
  "improvement_count": 1,
  "hidden_risk_count": 1,
  "artifact_uris": {
    "report_html_uri": "managed://reports/RUN-2026-03-15-001/report.html"
  },
  "message": "",
  "raw_packet": {}
}
```

## 6) UiPath HTTP Request Settings

For `HTTP Request` activity:

- Method: `POST`
- Endpoint: `http://localhost:8080/run` (or your deployed host)
- Headers:
  - `Authorization` = `Bearer <token>`
  - `Content-Type` = `application/json`
- Body: MaestroInput JSON payload
- Deserialize response as JSON and read:
  - `verdict`
  - `block_release`
  - `request_human_review`
  - `open_defect`
  - `artifact_uris`
