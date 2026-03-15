# Document AI Agentic Testing — Architecture

## 1. System Overview

The Document AI Agentic Testing system is a **production-grade, agentic regression-testing framework** built on CrewAI Flows. Its purpose is to answer one question with high confidence before every release: *"Does the new document AI prompt + model combination perform better, the same, or worse than the previous one — and if worse, exactly where, why, and how do we fix it?"*

### What It Is

- An automated quality gate that sits between a document AI model release and production deployment.
- A 10-agent, 14-step CrewAI Flow that ingests a structured Maestro payload, reads evidence from an Excel-based store, performs a three-way comparison (baseline vs. candidate vs. ground truth), and produces structured routing decisions for Maestro.
- A self-challenging system: if the evidence gathered is statistically insufficient, the flow expands scope autonomously, re-collects, and re-hunts before drawing conclusions.
- A full audit trail system: every agent decision, tool call, scope change, and rerun request is logged to a structured Excel audit log.

### What It Is NOT

- It is NOT a model training framework. It does not modify weights or fine-tune models.
- It is NOT a real-time inference service. It operates on pre-collected execution artifacts stored in the evidence store.
- It is NOT a rules engine. All analysis logic is performed by LLM-backed agents reasoning over structured evidence.

### The Three-Way Comparison Model

Every transaction in the evidence store carries data at four `ProcessStageID` values:

| Stage ID | Stage Name                  | Role in Comparison           |
|----------|-----------------------------|------------------------------|
| 1        | Pre Classify                | Candidate AI output          |
| 2        | Validated Post Classified   | Ground truth (human-labeled) |
| 3        | Pre Extract                 | Candidate AI extraction      |
| 4        | Validated Post Extracted    | Ground truth extraction      |

The "baseline" (previous artifact) is reconstructed from historical Stage 1/3 data linked to the previous `ModelVersion`. The three-way comparison is:

```
Baseline (prev artifact) vs. Candidate (curr artifact) vs. Truth (Stage 2/4)
```

This enables the system to detect:
- **Improvements**: candidate correct, baseline wrong
- **Regressions**: baseline correct, candidate wrong
- **Hidden risks**: both baseline and candidate wrong in different ways
- **Stable gold**: both correct (high-confidence anchor evidence)

---

## 2. Flow Diagram

```
Maestro Trigger
      |
      v
[1] receive_maestro_payload
      | validate, create workspace dirs, save input JSON
      v
[2] run_intake_diff
      | diff prompt text, model name, artifact hash
      | produce: change_summary, initial_risk_hypotheses
      v
[3] run_scope_planner
      | query evidence store, stratify by doc type & risk
      | produce: selected_transaction_ids, selected_doc_types, analysis_plan
      v
[4] run_evidence_collector
      | fetch rows from DocumentData per transaction
      | assemble case_bundles (one dict per transaction)
      | produce: case_bundles, evidence_summary
      v
[5] run_regression_hunter
      | compare Stage1 vs Stage2 (classification delta)
      | compare Stage3 vs Stage4 (extraction delta)
      | produce: improvement_findings, regression_findings, hidden_risk_findings
      v
[6] run_challenger
      | audit evidence quality, coverage, confidence intervals
      | produce: confidence_assessment, needs_more_evidence, challenge_notes
      v
[7] route_after_challenger  <--- ROUTER
      |                                  |
      | needs_more_evidence=True         | needs_more_evidence=False
      | AND rerun_count < max_reruns     | OR rerun_count >= max_reruns
      v                                  v
[8] run_targeted_rerun           [11] run_trend_drift
      | expand transaction scope         | cross-run trend analysis
      | produce: scope_expansion,        | produce: trend_summary, drift_alerts
      |          transactions_added      v
      v                           [12] run_root_cause
[9] run_evidence_refresh                 |
      | re-run evidence collector        v
      v                           [13] run_patch_proposal
[10] run_regression_refresh              |
      | re-run regression hunter         v
      | then calls run_trend_drift  [14] run_report_routing
      |                                  | write all output artifacts
      +--------------------------------->+ return final_run_packet to Maestro
```

---

## 3. Agent Responsibilities

### IntakeDiff Agent
The IntakeDiff agent receives both the current and previous execution artifacts (prompt text, model name, artifact hash) and produces a structured change summary. It performs a semantic diff of the prompt text to identify which document types, fields, or instructions were added, removed, or modified. It also generates initial risk hypotheses — e.g., "RelatedPartyForm was added to the class list; transactions previously classified as Other may now be reclassified." This output seeds the ScopePlanner's prioritisation logic.

### ScopePlanner Agent
The ScopePlanner agent translates the change summary and risk hypotheses into a concrete transaction selection plan. It queries the DocumentData sheet to understand what transaction volume and doc-type distribution is available in the requested date range. It applies a stratified sampling strategy that prioritises doc types flagged as high-risk by IntakeDiff, ensures coverage of all critical doc types (IdentityDocument, Passport, ApplicationForm), and respects the `max_initial_transactions` budget. Its output is a list of transaction IDs and a written analysis plan.

### EvidenceCollector Agent
The EvidenceCollector agent retrieves all DocumentData rows for each selected transaction ID from the Excel evidence store. For each transaction it assembles a "case bundle" — a structured dict containing all four stage rows, the inferred baseline classification (from historical Stage 1 linked to the previous model version), the candidate classification (current Stage 1), and the ground truth (Stage 2/4). It also flags missing truth records and missing candidate records, and produces an evidence quality summary.

### RegressionHunter Agent
The RegressionHunter agent performs the core three-way comparison across all case bundles. For classification it computes per-transaction deltas (correct/incorrect) and aggregates weighted F1 scores by doc type. For extraction it computes per-field match rates and missing-field rates. It classifies each finding as an improvement (candidate better than baseline), a regression (candidate worse), or a hidden risk (both wrong but in different ways). It applies policy thresholds from the run configuration to flag WARN and BLOCK conditions.

### Challenger Agent
The Challenger agent acts as the system's internal sceptic. It reviews the evidence summary, the findings produced by RegressionHunter, and the case bundle count to assess whether the conclusions are statistically sound. It checks for low sample sizes in critical doc types, high rates of missing truth records, and confidence intervals that span zero. If the evidence is insufficient to draw reliable conclusions, it sets `needs_more_evidence=True` and produces specific challenge notes that the TargetedRerun agent uses to guide scope expansion.

### TargetedRerun Agent
The TargetedRerun agent is invoked only when the Challenger flags insufficient evidence. It reads the challenge notes and hidden risk findings, then queries the evidence store to identify additional transactions that would resolve the specific gaps — e.g., more IdentityDocument transactions if the Challenger noted low coverage of that type. It produces a scope expansion request and a list of new transaction IDs to add. The flow then re-runs EvidenceCollector and RegressionHunter on the expanded scope. The system allows up to `max_targeted_reruns` expansions before proceeding regardless.

### TrendDrift Agent
The TrendDrift agent takes a longitudinal view. Rather than looking only at the current run, it queries the audit log and evidence store for historical run data to compute trend lines for key metrics: weighted F1, missing-field rate, exception rate, and API error rate. It detects drift — a sustained directional change across multiple runs — and produces drift alerts for any metric that has been degrading over time. This catches slow regressions that any single run comparison might miss.

### RootCause Agent
The RootCause agent synthesises the change summary, regression findings, targeted rerun summary, and trend summary into a structured list of root causes. For each regression pattern it reasons about the most likely cause: prompt wording change, model change, new class label introduction, scope creep in an existing class description, or data distribution shift. It assigns a confidence score to each hypothesised cause and ranks them by severity and likelihood.

### PatchProposal Agent
The PatchProposal agent translates root causes into concrete, safe, actionable patch candidates. For each root cause it proposes a minimum-change fix — e.g., a targeted prompt clause, a few-shot example addition, or a confidence threshold adjustment. It explicitly flags whether each patch requires human approval before deployment, and it generates a recommended A/B experiment specification for validating the patch. All patch candidates are written to the `patch_candidates/` workspace directory as structured JSON files.

### ReportRouting Agent
The ReportRouting agent is the final step. It aggregates all agent outputs into the complete final run packet and writes every requested output artifact: PDF report, HTML report, Excel run log, JSON packet, trace pack, and audit log update. It computes the final routing verdict (PASS, WARN, BLOCK) by applying policy thresholds to the regression findings, and it populates the Maestro routing fields that control downstream workflow branching: `block_release`, `request_human_review`, `open_defect`, and `notify_roles`.

---

## 4. Tool Layer

| Tool Name                     | Category        | Description                                                                                     |
|-------------------------------|-----------------|-------------------------------------------------------------------------------------------------|
| `ReadExcelTool`               | Data Access     | Reads one or more sheets from an Excel workbook using openpyxl; returns rows as list of dicts. |
| `WriteExcelTool`              | Data Access     | Appends or overwrites rows in a specified sheet of an Excel workbook.                           |
| `FilterDocumentDataTool`      | Data Access     | Queries DocumentData sheet with filters: TransactionID list, ProcessStageID, DocumentTypeID.    |
| `GetTransactionListTool`      | Data Access     | Returns a list of distinct TransactionIDs matching date range and doc type filters.             |
| `ComputeClassificationDelta`  | Analysis        | Compares Stage 1 vs Stage 2 per transaction; returns classification delta records.              |
| `ComputeExtractionDelta`      | Analysis        | Compares Stage 3 vs Stage 4 per transaction and field; returns extraction delta records.        |
| `ComputeWeightedF1Tool`       | Analysis        | Computes weighted F1 score from a set of classification delta records.                          |
| `ComputeMissingFieldRateTool` | Analysis        | Computes per-field missing rate from extraction delta records.                                  |
| `DiffPromptTextTool`          | Diff            | Performs a structured diff of two prompt strings; returns added/removed/changed clause list.    |
| `HashArtifactTool`            | Diff            | Computes and compares SHA-256 hashes of two artifact dictionaries.                              |
| `WriteWorkspaceTool`          | Output          | Writes a file (JSON, HTML, text) to the run workspace directory.                                |
| `WriteAuditLogTool`           | Output          | Appends a structured event row to the AgenticTesting_AuditLog.xlsx AgentEvents sheet.          |
| `WriteRunReportTool`          | Output          | Populates all sheets of a Run_REPORT.xlsx from structured agent output data.                    |
| `RenderHTMLReportTool`        | Output          | Renders a Jinja2 HTML report template from the final run packet dict.                           |
| `LookupModelNameTool`         | Lookup          | Resolves a ModelNameID to its ModelName string from the ai.ModelNames sheet.                    |
| `LookupDocTypeTool`           | Lookup          | Resolves a DocumentTypeID to its DocumentType string from the DocumentTypes sheet.              |

---

## 5. Data Model

### DocumentData Stage Interpretation

The `DocumentData` sheet is the central evidence table. Each row represents one observation of one field on one document at one processing stage. The four `ProcessStageID` values define the role of each row:

| ProcessStageID | ProcessStageName           | Meaning in the comparison model                             |
|----------------|----------------------------|-------------------------------------------------------------|
| 1              | Pre Classify               | What the AI model output BEFORE human validation           |
| 2              | Validated Post Classified  | What the human validator confirmed as GROUND TRUTH         |
| 3              | Pre Extract                | What the AI model extracted BEFORE human validation        |
| 4              | Validated Post Extracted   | What the human validator confirmed as the TRUE field value |

Stage 1 and Stage 3 are the candidate (current artifact) outputs when the `ModelVersion` column matches the current `prompt_version_label`. Historical Stage 1/3 rows with a prior `ModelVersion` represent the baseline. Stage 2 and Stage 4 are always ground truth, regardless of model version.

### Three-Way Comparison Table

| Comparison Dimension  | Baseline Source  | Candidate Source | Truth Source |
|-----------------------|------------------|------------------|--------------|
| Classification        | Stage 1 (prev)   | Stage 1 (curr)   | Stage 2      |
| Extraction value      | Stage 3 (prev)   | Stage 3 (curr)   | Stage 4      |
| Missing field flag    | Stage 3 IsMissing (prev) | Stage 3 IsMissing (curr) | Stage 4 IsMissing |
| Confidence score      | Stage 1 Confidence (prev) | Stage 1 Confidence (curr) | N/A (truth has no confidence) |

A **regression** is defined as: `baseline_correct=True AND candidate_correct=False`.
An **improvement** is defined as: `baseline_correct=False AND candidate_correct=True`.
A **hidden risk** is defined as: `baseline_correct=False AND candidate_correct=False AND baseline_value != candidate_value`.

---

## 6. Excel Workbooks

| Workbook                          | Purpose                                                  | Key Sheets                                                                                               |
|-----------------------------------|----------------------------------------------------------|----------------------------------------------------------------------------------------------------------|
| `DocumentAI_EvidenceStore.xlsx`   | Source of truth for all evidence; pre-populated with mock data | DocumentTypes, ProcessStages, ai.ModelStages, ai.ModelTypes, ai.ModelNames, DocumentData, ai.ModelData, ExceptionLogs, api.APIData |
| `AgenticTesting_AuditLog.xlsx`    | Append-only audit log written by agents during each run  | RunRegistry, MaestroInput, AgentEvents, ToolCalls, ScopeChanges, RerunRequests, WarningsAndErrors, OutputArtifacts |
| `Run_TEMPLATE_Report.xlsx`        | Per-run output report template; copied and populated by ReportRouting | RunSummary, Scope, TransactionsAnalyzed, ClassificationDeltas, ExtractionDeltas, MissingFieldAnalysis, ExceptionCorrelation, PatchCandidates, FinalRouting |

---

## 7. Maestro Integration

### Input Contract Summary

Maestro sends a POST request (or triggers an "External Agent" step) with a JSON payload containing:

- `run_request` — run metadata: run_id, process_name, run_mode, budgets, reruns
- `scope` — date range, optional transaction/doc-type filters, expansion permission
- `current_execution_artifact` — the new prompt: name, version label, full text, model name, hash
- `previous_execution_artifact` — the previous prompt: same fields
- `evidence_store` — store type, store_ref, sheet name mapping
- `storage` — workspace namespace, output mode, optional base path
- `policy` — numeric thresholds for WARN/BLOCK decisions
- `requested_outputs` — boolean flags for each output artifact type

### Output Contract Summary

The flow returns a `final_run_packet` dict to Maestro containing:

- `run_id`, `verdict` (PASS / WARN / BLOCK), `confidence`
- `block_release` (bool), `request_human_review` (bool), `open_defect` (bool)
- `notify_roles` (list of role names)
- `artifact_uris` — dict of artifact type → managed:// URI
- `summary_stats` — weighted F1 delta, missing field delta, exception rate delta
- `regression_count`, `improvement_count`, `hidden_risk_count`
- `rerun_count`, `start_datetime`, `end_datetime`
- `patch_candidates` — list of patch dicts
- `recommended_experiments` — list of experiment specs

### Routing Logic

| Verdict | Condition                                                        | Maestro Action           |
|---------|------------------------------------------------------------------|--------------------------|
| PASS    | No regressions OR regressions below WARN threshold              | Approve release          |
| WARN    | Regressions at or above WARN threshold, below BLOCK threshold   | Request human review     |
| BLOCK   | Any regression at or above BLOCK threshold                      | Block release, open defect |

The `block_release`, `request_human_review`, and `open_defect` boolean fields map directly to Maestro conditional branch connectors.

---

## 8. Model Stack

All models are run locally via Ollama — no API keys required, no data leaves the machine.

| Model                       | Ollama Pull Command                      | Used By Agents                              |
|-----------------------------|------------------------------------------|---------------------------------------------|
| `deepseek-r1:8b`            | `ollama pull deepseek-r1:8b`             | Document AI execution (evidence generation) |
| `qwen2.5:7b-instruct`       | `ollama pull qwen2.5:7b-instruct`        | IntakeDiff, ScopePlanner, Challenger, TrendDrift, RootCause |
| `qwen2.5-coder:7b-instruct` | `ollama pull qwen2.5-coder:7b-instruct`  | EvidenceCollector, RegressionHunter, TargetedRerun, PatchProposal, ReportRouting |

All three models are free, open-weight, and run entirely on local hardware. The coder variant is used for agents that produce structured JSON and perform algorithmic analysis; the instruct variant is used for agents that perform reasoning and natural-language synthesis.

---

## 9. Deployment

### Local Setup (Step by Step)

**Step 1 — Clone the repository and create a virtual environment**
```bash
git clone <repo-url> document_ai_agentic_testing
cd document_ai_agentic_testing
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate
```

**Step 2 — Install Python dependencies**
```bash
pip install -r requirements.txt
```

Key dependencies: `crewai`, `openpyxl`, `pydantic`, `python-dotenv`, `jinja2`.

**Step 3 — Install and start Ollama**
```bash
# Download Ollama from https://ollama.com
ollama serve  # Start in background
```

**Step 4 — Pull the required models**
```bash
ollama pull deepseek-r1:8b
ollama pull qwen2.5:7b-instruct
ollama pull qwen2.5-coder:7b-instruct
```

**Step 5 — Create the Excel workbooks**
```bash
python scripts/create_workbooks.py --output-dir ./data
```

This creates three `.xlsx` files in `./data/` with all required sheets and mock data.

**Step 6 — Run with the sample payload**
```bash
python main.py --sample
```

The system will create a workspace under `./workspaces/RUN-2026-03-14-001/`, run all 14 steps, and print the final routing packet as JSON.

**Step 7 — (Optional) Run as a webhook server**
```bash
python main.py --serve --port 8080
# Then POST to http://localhost:8080/run with a Maestro JSON payload
```
