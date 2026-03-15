# CrewAI → Maestro Output Contract

## Overview

When the agentic testing flow completes, it produces a Final Run Packet — a structured JSON document that Maestro consumes to make branching decisions, trigger notifications, open defects, and store audit artifacts. This document defines the schema, verdict semantics, routing fields, artifact URI conventions, and Maestro branching logic.

---

## Final Run Packet JSON Schema

The Final Run Packet is serialized from the `FinalRoutingOutput` Pydantic model. All fields are required unless marked optional.

```json
{
  "run_id": "RUN-2026-03-14-001",
  "status": "COMPLETED",
  "verdict": "WARN",
  "confidence": 0.87,
  "analysis_scope": {
    "date_from": "2026-03-01",
    "date_to": "2026-03-14",
    "transaction_ids": [1001, 1002, 1003],
    "doc_types_analyzed": ["Passport", "IdentityDocument", "ApplicationForm"],
    "total_transactions": 25,
    "total_documents": 72,
    "rerun_count": 1
  },
  "change_summary": {
    "prompt_changed": true,
    "model_changed": false,
    "artifact_diff_summary": [
      "System instruction tone changed from directive to collaborative",
      "Added explicit null-handling instruction for DateOfBirth field"
    ],
    "artifact_diff_details": [
      {
        "section": "system_instruction",
        "change_type": "modified",
        "description": "Tone shift: directive → collaborative",
        "risk_level": "low"
      }
    ]
  },
  "summary_metrics": {
    "baseline_weighted_f1": 0.912,
    "candidate_weighted_f1": 0.934,
    "weighted_f1_delta": 0.022,
    "baseline_empty_rate": 0.031,
    "candidate_empty_rate": 0.028,
    "empty_rate_delta": -0.003,
    "baseline_exception_rate": 0.011,
    "candidate_exception_rate": 0.009,
    "exception_rate_delta": -0.002,
    "doc_type_breakdown": {
      "Passport": {"baseline_f1": 0.95, "candidate_f1": 0.97, "delta": 0.02},
      "IdentityDocument": {"baseline_f1": 0.88, "candidate_f1": 0.91, "delta": 0.03}
    }
  },
  "improvements": [
    "DateOfBirth extraction improved by 4.2% across Passport documents",
    "Empty rate for IdentityDocument reduced from 5.1% to 2.8%"
  ],
  "regressions": [
    "AddressLine2 extraction degraded by 1.8% for ApplicationForm"
  ],
  "hidden_risks": [
    "Confidence score distribution shifted for Balance_Sheet; may indicate model uncertainty increase"
  ],
  "root_causes": [
    {
      "cause": "Null-handling instruction change altered AddressLine2 parsing behavior",
      "cause_type": "prompt",
      "confidence": 0.82,
      "supporting_evidence": [
        "TransactionID 1042: AddressLine2 returned empty where baseline had value",
        "TransactionID 1078: Same pattern observed"
      ]
    }
  ],
  "agentic_actions_taken": [
    "Scope expanded from 20 to 25 transactions after Challenger flagged insufficient ApplicationForm sample",
    "Targeted rerun performed on 5 ApplicationForm transactions",
    "Trend analysis performed over last 30 days of historical runs"
  ],
  "recommended_actions": [
    "Review AddressLine2 null-handling instruction before release",
    "Request human review of ApplicationForm regression findings",
    "Run targeted experiment: revert null-handling change for AddressLine2 only"
  ],
  "patch_candidates": [
    {
      "patch_id": "PATCH-001",
      "patch_type": "prompt",
      "target": "system_instruction.null_handling",
      "description": "Scope null-handling instruction to exclude AddressLine2 field",
      "proposed_change": "Add exclusion: 'Do not apply null coercion to AddressLine2 fields'",
      "confidence": 0.79,
      "requires_human_approval": true,
      "priority": "high"
    }
  ],
  "routing": {
    "block_release": false,
    "request_human_review": true,
    "open_defect": true,
    "notify_roles": ["QA_Lead", "Prompt_Engineer"],
    "verdict": "WARN",
    "verdict_rationale": "Candidate shows net improvement but contains a medium-severity regression on AddressLine2 for ApplicationForm. Human review required before release."
  },
  "artifacts": {
    "pdf_report": "managed://agentic-testing/RUN-2026-03-14-001/report.pdf",
    "html_report": "managed://agentic-testing/RUN-2026-03-14-001/report.html",
    "excel_log": "managed://agentic-testing/RUN-2026-03-14-001/run_log.xlsx",
    "json_packet": "managed://agentic-testing/RUN-2026-03-14-001/final_packet.json",
    "trace_pack": "managed://agentic-testing/RUN-2026-03-14-001/trace_pack.zip",
    "patch_candidates": "managed://agentic-testing/RUN-2026-03-14-001/patch_candidates.json",
    "audit_log_excel": "managed://agentic-testing/RUN-2026-03-14-001/audit_log.xlsx"
  }
}
```

### Field Descriptions

| Field | Type | Description |
|-------|------|-------------|
| run_id | string | Unique run identifier from the Maestro input |
| status | string | Always `COMPLETED` on success; `FAILED` if the flow errored |
| verdict | string | `PASS`, `WARN`, or `BLOCK` (see Verdict Definitions) |
| confidence | float | Overall agent confidence in the verdict (0.0–1.0) |
| analysis_scope | object | Scope of the analysis including transaction IDs and doc types |
| change_summary | object | Diff between old and new execution artifacts |
| summary_metrics | object | Aggregated quality metrics for baseline and candidate |
| improvements | string[] | Human-readable list of confirmed improvement findings |
| regressions | string[] | Human-readable list of confirmed regression findings |
| hidden_risks | string[] | Findings that may indicate future risk without clear current regression |
| root_causes | object[] | Root cause analysis results (see RootCauseOutput schema) |
| agentic_actions_taken | string[] | Autonomous actions taken during the run (scope expansions, reruns, etc.) |
| recommended_actions | string[] | Actions recommended for human follow-up |
| patch_candidates | object[] | Proposed patches for human review (see PatchCandidateItem schema) |
| routing | object | Maestro routing decisions (see Routing Fields section) |
| artifacts | object | URI map of all generated output artifacts |

---

## Verdict Definitions

### PASS

**Meaning**: The candidate execution artifact (new prompt/model) shows no regressions relative to the current production baseline. The release is safe to proceed automatically.

**Conditions for PASS**:
- No regression findings of severity `medium`, `high`, or `critical`
- Weighted F1 delta >= 0.0 (no degradation)
- Empty rate delta <= `policy.block_empty_rate_increase` threshold
- Exception rate delta <= `policy.block_exception_rate_increase` threshold
- No critical document type degradation detected
- Challenger agent confirms sufficient evidence quality

**Maestro action**: Proceed with release pipeline; log audit record; no human gate required.

---

### WARN

**Meaning**: The candidate shows net improvement overall but contains caveats — minor regressions, insufficient evidence for some doc types, or hidden risks detected. Human review is recommended before release.

**Conditions for WARN** (any of the following):
- Regression findings present with severity `low` or `medium` only
- Weighted F1 delta is positive but Challenger flagged label noise concern
- Evidence quality note indicates missing truth labels for some transactions
- Hidden risk findings detected (behavioral changes without clear quality signal)
- Weighted F1 drop between `policy.warn_weighted_f1_drop` and `policy.block_weighted_f1_drop`
- Trend drift agent detected a concerning pattern not yet manifesting as hard regression

**Maestro action**: Pause automated release; notify designated roles; open review ticket; await human approval.

---

### BLOCK

**Meaning**: The candidate execution artifact contains critical regressions or violates policy thresholds. The release must not proceed.

**Conditions for BLOCK** (any of the following):
- Any regression finding of severity `high` or `critical`
- Weighted F1 drop >= `policy.block_weighted_f1_drop` (default 0.05)
- Empty rate increase >= `policy.block_empty_rate_increase` (default 0.03)
- Exception rate increase >= `policy.block_exception_rate_increase` (default 0.02)
- Critical document type (`IdentityDocument`, `Passport`, `ApplicationForm`) shows any regression of severity `medium` or higher
- Root cause analysis identifies a confirmed prompt or model defect causing quality loss

**Maestro action**: Block release pipeline; open defect ticket; notify all designated roles; require explicit override to proceed.

---

## Routing Fields

The `routing` object within the Final Run Packet drives all Maestro branching decisions.

| Field | Type | Description |
|-------|------|-------------|
| block_release | bool | If `true`, Maestro must halt the release pipeline |
| request_human_review | bool | If `true`, Maestro creates a human review task/ticket |
| open_defect | bool | If `true`, Maestro opens a defect record in the issue tracker |
| notify_roles | string[] | List of role identifiers that must be notified (e.g. `QA_Lead`, `Prompt_Engineer`, `Model_Owner`) |
| verdict | string | Duplicate of the top-level verdict for routing convenience |
| verdict_rationale | string | Human-readable explanation of why this verdict was reached |

### Routing Field Semantics by Verdict

| Verdict | block_release | request_human_review | open_defect | notify_roles |
|---------|---------------|---------------------|-------------|-------------|
| PASS | false | false | false | [] |
| WARN | false | true | true | ["QA_Lead"] + agent-determined roles |
| BLOCK | true | true | true | ["QA_Lead", "Prompt_Engineer"] + agent-determined roles |

Note: The agent may add additional roles to `notify_roles` based on the nature of the findings (e.g. `Model_Owner` if a model change caused a regression).

---

## Artifact URIs

All generated output artifacts are referenced using the `managed://` URI scheme. Maestro is responsible for resolving these URIs to actual storage locations using the `artifact_namespace` and `run_workspace_key` from the input `StorageConfig`.

### URI Format

```
managed://{artifact_namespace}/{run_workspace_key}/{filename}
```

### Standard Artifact Keys

| Key | Filename | Description |
|-----|----------|-------------|
| pdf_report | `report.pdf` | Full formatted PDF report with charts and findings |
| html_report | `report.html` | Self-contained HTML version of the report |
| excel_log | `run_log.xlsx` | Excel workbook with per-transaction findings detail |
| json_packet | `final_packet.json` | The Final Run Packet itself (for archival and downstream processing) |
| trace_pack | `trace_pack.zip` | ZIP archive of all agent reasoning traces and intermediate outputs |
| patch_candidates | `patch_candidates.json` | Machine-readable patch proposals for integration with prompt management systems |
| audit_log_excel | `audit_log.xlsx` | Full audit log workbook (see Audit Log Workbook Schema) |

---

## Maestro Branching Logic

The following pseudocode describes how Maestro should process the Final Run Packet:

```
receive final_run_packet from CrewAI flow

if final_run_packet.status == "FAILED":
    notify ["Platform_Team", "QA_Lead"]
    open_incident()
    halt_release()
    return

routing = final_run_packet.routing

if routing.block_release == true:
    halt_release_pipeline(run_id=final_run_packet.run_id)

if routing.open_defect == true:
    create_defect(
        title=f"[{final_run_packet.verdict}] Agentic Testing: {final_run_packet.run_id}",
        description=routing.verdict_rationale,
        severity=derive_severity(final_run_packet.verdict),
        attachments=[
            resolve_uri(final_run_packet.artifacts.pdf_report),
            resolve_uri(final_run_packet.artifacts.json_packet)
        ]
    )

if routing.request_human_review == true:
    create_review_task(
        assignee_roles=routing.notify_roles,
        run_id=final_run_packet.run_id,
        verdict=final_run_packet.verdict,
        patch_candidates=final_run_packet.patch_candidates,
        report_uri=resolve_uri(final_run_packet.artifacts.html_report)
    )

for role in routing.notify_roles:
    send_notification(
        role=role,
        verdict=final_run_packet.verdict,
        rationale=routing.verdict_rationale,
        report_uri=resolve_uri(final_run_packet.artifacts.pdf_report)
    )

write_audit_record(
    run_id=final_run_packet.run_id,
    verdict=final_run_packet.verdict,
    confidence=final_run_packet.confidence,
    artifacts=final_run_packet.artifacts
)
```

### Severity Mapping for Defect Creation

| Verdict | Defect Severity |
|---------|----------------|
| PASS | N/A (no defect opened) |
| WARN | Medium |
| BLOCK | High |
