# Maestro ↔ CrewAI Contract

## 1. Trigger Mechanism

The Document AI Agentic Testing flow is triggered from a Maestro workflow using one of three patterns:

### Pattern A — External Agent (Recommended)
In the Maestro workflow designer, add an **"External Agent"** step and configure it to call the CrewAI webhook endpoint:
- **Method**: POST
- **URL**: `http://<host>:8080/run`
- **Body**: The full Maestro JSON payload (see Section 2)
- **Wait for response**: Yes (synchronous; the step blocks until the flow returns)
- **Timeout**: Set to `time_budget_minutes * 60` seconds (e.g., 1200 seconds for a 20-minute budget)

### Pattern B — External Workflow Step
Use Maestro's **"Start and wait for external workflow"** action. Configure the payload as an HTTP POST body. The flow's final packet (see Section 3) is returned as the step's output JSON, which Maestro can then map to subsequent step inputs.

### Pattern C — API Workflow (Fire and Poll)
Use Maestro's **"API Workflow"** action to POST the payload, receive a `run_id` acknowledgement, then poll `GET /status/<run_id>` until the verdict is available. This pattern is suitable when time budgets exceed Maestro's synchronous step timeout.

---

## 2. Full Input Payload JSON Example

This is the complete Maestro input payload. All fields are required unless noted as optional.

```json
{
  "run_request": {
    "run_id": "RUN-2026-03-14-001",
    "process_name": "document_ai_agentic_testing",
    "run_mode": "release_candidate",
    "analysis_mode": "agentic_investigation",
    "time_budget_minutes": 20,
    "max_initial_transactions": 20,
    "max_total_transactions": 100,
    "max_targeted_reruns": 3,
    "triggered_by": "CLI_SAMPLE"
  },
  "scope": {
    "date_from": "2026-02-01",
    "date_to": "2026-03-14",
    "transaction_ids": [],
    "document_type_names": [],
    "process_stage_ids": [1, 2, 3, 4],
    "allow_agent_to_expand_scope": true
  },
  "current_execution_artifact": {
    "prompt_name": "classification_extraction_bundle",
    "prompt_version_label": "bundle_v17",
    "prompt_text": "You are a document classification and extraction AI. Classify the document type from: ApplicationForm, Resolution, Windeed, Passport, IdentityDocument, ProductFormsBTB, ProductFormsIFB, ProductFormsICIB, Income_Statement, Balance_Sheet, CashFlow, Debtors, Creditors, AFS, Other, RelatedPartyForm. Then extract all relevant fields. For IdentityDocument and Passport: extract IdentityNumber or PassportNumber. For ApplicationForm: extract EntityName, ApplicationDate. If the document is out of scope or unreadable, classify as Other.",
    "model_name": "deepseek-r1:8b",
    "artifact_hash": "sha256-current-bundle-v17"
  },
  "previous_execution_artifact": {
    "prompt_name": "classification_extraction_bundle",
    "prompt_version_label": "bundle_v16",
    "prompt_text": "You are a document classification and extraction AI. Classify the document type from: ApplicationForm, Resolution, Windeed, Passport, IdentityDocument, ProductFormsBTB, ProductFormsIFB, ProductFormsICIB, Income_Statement, Balance_Sheet, CashFlow, Debtors, Creditors, AFS, Other. Then extract all relevant fields. For IdentityDocument: extract IdentityNumber. For ApplicationForm: extract EntityName, ApplicationDate.",
    "model_name": "deepseek-r1:8b",
    "artifact_hash": "sha256-previous-bundle-v16"
  },
  "evidence_store": {
    "store_type": "excel",
    "store_ref": "DocumentAI_EvidenceStore",
    "sheet_names": {
      "document_data": "DocumentData",
      "model_data": "ai.ModelData",
      "document_types": "DocumentTypes",
      "process_stages": "ProcessStages",
      "model_names": "ai.ModelNames",
      "model_stages": "ai.ModelStages",
      "model_types": "ai.ModelTypes",
      "exception_logs": "ExceptionLogs",
      "api_data": "api.APIData"
    }
  },
  "storage": {
    "artifact_namespace": "agentic-testing",
    "run_workspace_key": "RUN-2026-03-14-001",
    "output_mode": "managed_workspace",
    "workspace_base_path": null
  },
  "policy": {
    "critical_doc_types": ["IdentityDocument", "Passport", "ApplicationForm"],
    "warn_weighted_f1_drop": 0.02,
    "block_weighted_f1_drop": 0.05,
    "block_empty_rate_increase": 0.03,
    "block_exception_rate_increase": 0.02
  },
  "requested_outputs": {
    "pdf_report": true,
    "html_report": true,
    "excel_log": true,
    "json_packet": true,
    "trace_pack": true,
    "patch_candidates": true,
    "audit_log_excel": true
  }
}
```

### Field Reference

| Field Path | Type | Required | Description |
|---|---|---|---|
| `run_request.run_id` | string | Yes | Unique run identifier. Used as workspace folder name. |
| `run_request.run_mode` | string | Yes | One of: `release_candidate`, `hotfix`, `regression_only`, `full_audit` |
| `run_request.analysis_mode` | string | Yes | One of: `agentic_investigation`, `fast_check`, `full_audit` |
| `run_request.time_budget_minutes` | int | Yes | Soft time budget. Agents respect this to limit scope. |
| `run_request.max_initial_transactions` | int | Yes | Max transactions in first ScopePlanner pass. |
| `run_request.max_total_transactions` | int | Yes | Hard cap across all reruns combined. |
| `run_request.max_targeted_reruns` | int | Yes | Max number of Challenger → TargetedRerun cycles allowed. |
| `scope.date_from` / `date_to` | string (ISO date) | Yes | Date window for transaction selection. |
| `scope.transaction_ids` | list[int] | No | If non-empty, overrides date-range selection. |
| `scope.document_type_names` | list[str] | No | If non-empty, restricts selection to these doc types. |
| `scope.allow_agent_to_expand_scope` | bool | Yes | If false, TargetedRerun is disabled even if Challenger requests it. |
| `current_execution_artifact.prompt_version_label` | string | Yes | Version label used to look up Stage 1/3 rows in DocumentData. |
| `previous_execution_artifact.prompt_version_label` | string | Yes | Version label for baseline Stage 1/3 rows. |
| `evidence_store.store_ref` | string | Yes | Filename stem of the evidence Excel workbook (without .xlsx). |
| `storage.workspace_base_path` | string or null | No | If null, falls back to `WORKSPACE_BASE_PATH` env var or `./workspaces`. |
| `policy.*` | float | Yes | Threshold values controlling WARN and BLOCK verdict assignment. |

---

## 3. Full Output Packet JSON Example

The flow returns this structure as `final_run_packet` after step 14 (ReportRouting). This is also the HTTP response body in webhook mode.

```json
{
  "run_id": "RUN-2026-03-14-001",
  "verdict": "WARN",
  "confidence": 0.82,
  "block_release": false,
  "request_human_review": true,
  "open_defect": false,
  "notify_roles": ["QA_Lead", "ML_Engineer"],
  "artifact_uris": {
    "pdf_report": "managed://agentic-testing/RUN-2026-03-14-001/outputs/Run_Report.pdf",
    "html_report": "managed://agentic-testing/RUN-2026-03-14-001/outputs/Run_Report.html",
    "excel_log": "managed://agentic-testing/RUN-2026-03-14-001/outputs/Run_Report.xlsx",
    "json_packet": "managed://agentic-testing/RUN-2026-03-14-001/outputs/final_run_packet.json",
    "trace_pack": "managed://agentic-testing/RUN-2026-03-14-001/outputs/trace_pack.zip",
    "patch_candidates": "managed://agentic-testing/RUN-2026-03-14-001/patch_candidates/",
    "audit_log": "managed://agentic-testing/RUN-2026-03-14-001/logs/AgenticTesting_AuditLog.xlsx"
  },
  "summary_stats": {
    "weighted_f1_baseline": 0.87,
    "weighted_f1_candidate": 0.84,
    "weighted_f1_delta": -0.03,
    "missing_field_rate_baseline": 0.04,
    "missing_field_rate_candidate": 0.06,
    "missing_field_rate_delta": 0.02,
    "exception_rate_baseline": 0.01,
    "exception_rate_candidate": 0.01,
    "exception_rate_delta": 0.00
  },
  "regression_count": 2,
  "improvement_count": 1,
  "hidden_risk_count": 1,
  "transactions_analyzed": 5,
  "rerun_count": 0,
  "prompt_changed": true,
  "prompt_version_old": "bundle_v16",
  "prompt_version_new": "bundle_v17",
  "model_old": "deepseek-r1:8b",
  "model_new": "deepseek-r1:8b",
  "change_summary": {
    "prompt_changed": true,
    "model_changed": false,
    "added_classes": ["RelatedPartyForm"],
    "removed_classes": [],
    "modified_instructions": ["Passport extraction now includes PassportNumber alongside IdentityNumber"],
    "risk_level": "MEDIUM"
  },
  "regression_findings": [
    {
      "transaction_id": 1002,
      "doc_type": "IdentityDocument",
      "finding_type": "classification_regression",
      "baseline_correct": true,
      "candidate_correct": false,
      "baseline_value": "IdentityDocument",
      "candidate_value": "Passport",
      "confidence_candidate": 0.83,
      "severity": "HIGH",
      "note": "New Passport instruction may be causing confusion with IdentityDocument"
    },
    {
      "transaction_id": 1004,
      "doc_type": "ApplicationForm",
      "finding_type": "extraction_regression",
      "field": "EntityName",
      "baseline_correct": true,
      "candidate_correct": false,
      "baseline_value": "Acme Holdings Ltd",
      "candidate_value": "",
      "is_missing_candidate": true,
      "severity": "MEDIUM",
      "note": "EntityName extraction missing in candidate run"
    }
  ],
  "improvement_findings": [
    {
      "transaction_id": 1005,
      "doc_type": "ApplicationForm",
      "finding_type": "classification_improvement",
      "baseline_correct": false,
      "candidate_correct": true,
      "note": "Candidate correctly identified ApplicationForm where baseline returned Resolution"
    }
  ],
  "patch_candidates": [
    {
      "patch_id": "PATCH-001",
      "patch_type": "prompt_clause",
      "target": "IdentityDocument vs Passport disambiguation",
      "description": "Add a disambiguation clause: 'South African green barcoded IDs and smart IDs are IdentityDocument, not Passport, even if they contain photos.'",
      "confidence": 0.78,
      "requires_human_approval": true,
      "recommended_experiment": "A/B test bundle_v17 with disambiguation clause vs without, on 50 IdentityDocument transactions"
    }
  ],
  "root_causes": [
    {
      "cause_id": "RC-001",
      "cause": "Addition of Passport to the prompt class list broadened the decision boundary, causing misclassification of some IdentityDocument cases as Passport.",
      "confidence": 0.81,
      "severity": "HIGH",
      "related_findings": ["regression at TXN 1002"],
      "related_change": "RelatedPartyForm added to class list; PassportNumber extraction instruction added"
    }
  ],
  "drift_alerts": [],
  "start_datetime": "2026-03-14T10:00:00.000000",
  "end_datetime": "2026-03-14T10:04:37.812341",
  "workspace_path": "workspaces/RUN-2026-03-14-001"
}
```

---

## 4. Maestro Branching Table

Maestro reads the following fields from the output packet to drive conditional branches in the workflow:

| Output Field | Type | Value | Maestro Action |
|---|---|---|---|
| `verdict` | string | `"PASS"` | Continue release pipeline |
| `verdict` | string | `"WARN"` | Route to human review queue |
| `verdict` | string | `"BLOCK"` | Halt release; open defect ticket |
| `block_release` | bool | `true` | Trigger Maestro "Block Release" action |
| `block_release` | bool | `false` | Proceed to next stage |
| `request_human_review` | bool | `true` | Assign run packet to QA lead inbox |
| `request_human_review` | bool | `false` | Skip human review step |
| `open_defect` | bool | `true` | Create defect in issue tracker via Maestro connector |
| `open_defect` | bool | `false` | Skip defect creation |
| `notify_roles` | list | e.g. `["QA_Lead"]` | Send notification to each named role |
| `regression_count` | int | `> 0` | Optionally surface regression count in notification body |
| `patch_candidates` | list | non-empty | Optionally attach patch file URI to notification |
| `artifact_uris.pdf_report` | string | managed:// URI | Attach to email/Teams notification |
| `artifact_uris.excel_log` | string | managed:// URI | Link in defect ticket |

### Recommended Maestro Branch Configuration

```
[CrewAI Run Step]
        |
        +-- block_release == true  --> [Block Release] --> [Open Defect] --> [Notify: ML_Engineer, QA_Lead]
        |
        +-- request_human_review == true AND block_release == false
        |       --> [Assign to QA Inbox] --> [Notify: QA_Lead]
        |
        +-- verdict == "PASS"
                --> [Approve Release] --> [Continue Pipeline]
```

---

## 5. Artifact URI Scheme

All output artifacts are referenced using the `managed://` URI scheme:

```
managed://<namespace>/<run_id>/<relative_path>
```

| Component | Example | Description |
|---|---|---|
| `namespace` | `agentic-testing` | From `storage.artifact_namespace` in the input payload |
| `run_id` | `RUN-2026-03-14-001` | From `run_request.run_id` |
| `relative_path` | `outputs/Run_Report.pdf` | Path relative to the workspace root |

### Artifact Types and Paths

| Artifact Key | URI Pattern | Description |
|---|---|---|
| `pdf_report` | `managed://.../outputs/Run_Report.pdf` | Full PDF summary report |
| `html_report` | `managed://.../outputs/Run_Report.html` | Interactive HTML report |
| `excel_log` | `managed://.../outputs/Run_Report.xlsx` | Excel run report (all sheets) |
| `json_packet` | `managed://.../outputs/final_run_packet.json` | Complete JSON output packet |
| `trace_pack` | `managed://.../outputs/trace_pack.zip` | Agent trace logs and intermediate outputs |
| `patch_candidates` | `managed://.../patch_candidates/` | Directory of per-patch JSON files |
| `audit_log` | `managed://.../logs/AgenticTesting_AuditLog.xlsx` | Full audit log workbook |

### Resolving a managed:// URI

To resolve a `managed://` URI to a local file path, the consuming system applies:

```
local_path = <workspace_base_path> / <run_id> / <relative_path>
```

Where `workspace_base_path` is resolved from `storage.workspace_base_path` in the input payload, or from the `WORKSPACE_BASE_PATH` environment variable, or defaults to `./workspaces`.

---

## 6. Error Handling

### Flow-Level Exception

If any unhandled exception occurs during flow execution, the flow catches it at the `run_flow_from_maestro_payload` entry point and returns a structured error packet:

```json
{
  "error": "Detailed exception message string",
  "run_id": "RUN-2026-03-14-001",
  "verdict": "ERROR",
  "block_release": true,
  "request_human_review": true,
  "start_datetime": "2026-03-14T10:00:00.000000",
  "end_datetime": "2026-03-14T10:00:04.123456",
  "failed_at_step": "run_evidence_collector_step"
}
```

The HTTP server in `--serve` mode returns this as a **500 response** with `Content-Type: application/json`.

### Agent-Level Errors

Individual agents handle their own errors gracefully. If an agent fails:

1. The agent returns an empty or default output dict (e.g., `{"regression_findings": [], "error_note": "..."}`)
2. The flow continues with degraded state
3. The error is recorded in `state.audit_events` with `event_type="ERROR"`
4. The ReportRouting agent detects the degraded state and sets `verdict="WARN"` with a note about incomplete analysis

### Validation Errors (Pydantic)

If the Maestro input payload fails `MaestroInput` schema validation, a `ValidationError` is raised immediately before the flow starts. The HTTP server returns a **400 response**:

```json
{
  "error": "validation_error",
  "detail": [
    {
      "loc": ["run_request", "run_id"],
      "msg": "field required",
      "type": "value_error.missing"
    }
  ]
}
```

### Timeout Handling

If the flow exceeds `time_budget_minutes`, agents check the elapsed time before starting expensive operations and may short-circuit to produce a partial result. The ReportRouting agent always runs, even in a short-circuit scenario, to ensure Maestro always receives a valid routing packet. The verdict in a timed-out run is set to `"WARN"` with a note indicating incomplete analysis.

### Missing Evidence Store

If the evidence store Excel file cannot be found at the configured path, the flow raises a `FileNotFoundError` at the first tool call that attempts to read it. The error packet will include:

```json
{
  "error": "Evidence store not found at: data/DocumentAI_EvidenceStore.xlsx",
  "remediation": "Run: python scripts/create_workbooks.py --output-dir ./data",
  "block_release": true
}
```
