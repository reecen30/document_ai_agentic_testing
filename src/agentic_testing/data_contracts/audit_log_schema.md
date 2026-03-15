# Audit Log Workbook Schema

## Overview

The Audit Log Workbook (`AgenticTesting_AuditLog.xlsx`) is written by the agentic testing system during and after each run. It provides a complete, structured audit trail of every run, all agent actions, tool calls, scope changes, rerun requests, warnings, errors, and output artifacts produced. This workbook is intended for compliance, debugging, and post-run analysis by human reviewers.

The workbook is created fresh for each run and stored as an artifact in the run's managed workspace. The file is also appended to a shared master audit log workbook maintained across all runs.

Each sheet is described below with full column definitions.

---

## Sheet: RunRegistry

One row per run. Top-level summary of the entire agentic testing execution.

| Column | Type | Description |
|--------|------|-------------|
| RunID | string | Unique run identifier (e.g. `RUN-2026-03-14-001`) |
| ProcessName | string | Always `document_ai_agentic_testing` |
| RunMode | string | `release_candidate`, `scheduled`, or `manual` |
| StartDateTime | datetime | UTC timestamp when the flow started |
| EndDateTime | datetime | UTC timestamp when the flow completed or failed |
| Status | string | `COMPLETED`, `FAILED`, or `PARTIAL` |
| Verdict | string | `PASS`, `WARN`, or `BLOCK` (null if Status = FAILED) |
| Confidence | float | Agent's overall confidence in the verdict (0.0–1.0) |
| TransactionsAnalyzed | int | Total number of transactions included in the final analysis |
| InitialTransactionCount | int | Number of transactions in the initial scope before any expansion |
| FinalTransactionCount | int | Number of transactions in the final scope after all expansions |
| PromptVersionLabel_Old | string | Version label of the previous execution artifact's prompt |
| PromptVersionLabel_New | string | Version label of the current (candidate) execution artifact's prompt |
| Model_Old | string | Model name of the previous execution artifact |
| Model_New | string | Model name of the current (candidate) execution artifact |
| WorkspaceKey | string | Run workspace key used for artifact storage |
| TriggeredBy | string | Entity that triggered the run (e.g. `Maestro`, `Manual`) |
| Notes | string | Free-text notes; populated if Status = FAILED or PARTIAL |

---

## Sheet: MaestroInput

Stores a flattened record of every field from the Maestro input payload for auditability. One row per input field.

| Column | Type | Description |
|--------|------|-------------|
| RunID | string | Links to RunRegistry |
| ReceivedDateTime | datetime | UTC timestamp when the input was received by the flow |
| InputSection | string | Top-level section of the input (e.g. `run_request`, `scope`, `policy`, `evidence_store`) |
| FieldName | string | Dot-notation path to the field (e.g. `scope.date_from`, `policy.block_weighted_f1_drop`) |
| FieldValue | string | String-serialized value of the field |
| ValueType | string | Python type of the value (e.g. `str`, `int`, `float`, `bool`, `list`, `dict`) |

This sheet allows full reconstruction of the Maestro input for any historical run without relying on external systems.

---

## Sheet: AgentEvents

One row per agent event. Captures the lifecycle of each agent's execution: start, completion, and any intermediate events.

| Column | Type | Description |
|--------|------|-------------|
| RunID | string | Links to RunRegistry |
| EventID | string | Unique event identifier within the run (e.g. `EVT-001`) |
| AgentName | string | Name of the agent (e.g. `Agentic_IntakeDiff`, `Agentic_RegressionHunter`) |
| EventType | string | `AGENT_START`, `AGENT_COMPLETE`, `AGENT_ERROR`, `AGENT_RETRY`, `SCOPE_CHANGE`, `RERUN_REQUEST` |
| Timestamp | datetime | UTC timestamp of the event |
| DurationSeconds | float | Wall-clock duration of the agent's execution (null for non-terminal events) |
| InputRef | string | Reference to the input data consumed by this agent (e.g. workspace key path or summary) |
| OutputRef | string | Reference to the output data produced by this agent |
| Summary | string | One-sentence human-readable summary of what the agent did or found |
| Status | string | `OK`, `WARN`, `ERROR`, `SKIPPED` |

---

## Sheet: ToolCalls

One row per tool call made by any agent. Enables detailed tracing of all data access and external operations.

| Column | Type | Description |
|--------|------|-------------|
| RunID | string | Links to RunRegistry |
| ToolCallID | string | Unique tool call identifier within the run (e.g. `TC-001`) |
| AgentName | string | Agent that made the tool call |
| ToolName | string | Name of the CrewAI tool invoked (e.g. `ExcelReaderTool`, `OllamaInferenceTool`) |
| Timestamp | datetime | UTC timestamp when the tool call was initiated |
| InputSummary | string | Brief description of the input provided to the tool (truncated to 500 chars) |
| RowsRead | int | Number of rows read from the evidence store (null for non-read operations) |
| RowsWritten | int | Number of rows written to an output artifact (null for non-write operations) |
| DurationSeconds | float | Wall-clock duration of the tool call |
| Status | string | `OK`, `ERROR`, `TIMEOUT` |
| Notes | string | Error message or additional context if Status != OK |

---

## Sheet: ScopeChanges

Records every change to the analysis scope that occurred during the run. The Challenger and TargetedRerun agents may request scope expansions; this sheet captures each one.

| Column | Type | Description |
|--------|------|-------------|
| RunID | string | Links to RunRegistry |
| Timestamp | datetime | UTC timestamp when the scope change was approved and applied |
| Reason | string | Human-readable explanation of why the scope was changed |
| OldScope | string | JSON-serialized representation of the scope before the change |
| NewScope | string | JSON-serialized representation of the scope after the change |
| RequestedByAgent | string | Agent name that requested the scope change |

Scope changes include: adding transaction IDs, adding document type filters, expanding date ranges, or increasing the maximum transaction count limit.

---

## Sheet: RerunRequests

Records every targeted rerun request raised by the TargetedRerun agent. Each row corresponds to one batch of transactions that were re-analysed with additional focus.

| Column | Type | Description |
|--------|------|-------------|
| RunID | string | Links to RunRegistry |
| Timestamp | datetime | UTC timestamp of the rerun request |
| RequestedByAgent | string | Always `Agentic_TargetedRerun` or `Agentic_Challenger` |
| PatternName | string | Label describing the pattern or hypothesis being investigated (e.g. `AddressLine2_Regression_Check`) |
| TransactionIDs | string | JSON array of transaction IDs included in the rerun |
| Reason | string | Detailed rationale for why these transactions were selected for rerun |
| Status | string | `APPROVED`, `SKIPPED` (if max reruns exceeded), `COMPLETED`, `FAILED` |

---

## Sheet: WarningsAndErrors

Captures all warnings and errors raised at any point during the run, by any agent or tool. This is the primary diagnostic sheet for failed or partial runs.

| Column | Type | Description |
|--------|------|-------------|
| RunID | string | Links to RunRegistry |
| Timestamp | datetime | UTC timestamp of the warning or error |
| Source | string | Agent name, tool name, or system component that raised the event |
| Severity | string | `INFO`, `WARN`, `ERROR`, `CRITICAL` |
| Message | string | Full warning or error message |
| RelatedTransactionID | int | Transaction ID related to the issue, if applicable (null otherwise) |
| RelatedAgent | string | Agent name most closely associated with the issue (may differ from Source for cascading errors) |

Rows with Severity = `CRITICAL` indicate failures that caused the run to terminate early (Status = `FAILED` in RunRegistry).

---

## Sheet: OutputArtifacts

Records every output artifact produced during the run, with its storage URI and creation status.

| Column | Type | Description |
|--------|------|-------------|
| RunID | string | Links to RunRegistry |
| Timestamp | datetime | UTC timestamp when the artifact was created |
| ArtifactType | string | Type of artifact: `pdf_report`, `html_report`, `excel_log`, `json_packet`, `trace_pack`, `patch_candidates`, `audit_log_excel` |
| ArtifactURI | string | Full `managed://` URI of the artifact |
| CreatedByAgent | string | Agent that created the artifact (typically `Agentic_ReportRouting`) |
| Status | string | `CREATED`, `FAILED`, `SKIPPED` (if the requested_outputs flag was false for this artifact type) |

A row is written for every artifact type that was requested via the `RequestedOutputs` configuration, regardless of whether creation succeeded or failed.
