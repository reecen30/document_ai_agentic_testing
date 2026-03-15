# Document AI Agentic Testing — Technical Specification

**Package:** `document-ai-agentic-testing` v1.0.0
**Framework:** CrewAI Flow (stateful multi-agent pipeline)
**Language:** Python 3.11+
**Entry points:** CLI (`agentic-testing`), REST API (FastAPI/Uvicorn), direct Python call
**Trigger protocol:** Maestro JSON envelope

---

## 1. What Problem This Solves

Every document AI release — whether a prompt change, model upgrade, or extraction rule revision — carries risk. The candidate might improve accuracy on one document type while silently regressing on another. A model with higher overall F1 could still produce high-confidence wrong answers on critical identity documents. Human QA teams cannot feasibly evaluate hundreds of transactions manually before each release, and static test suites cannot reason about _why_ a regression happened or _what patch_ would fix it.

**This system is a production-grade agentic quality gate.** It sits between a document AI prompt/model change and the decision to release. It autonomously:

- Understands what changed between the candidate and the previous release artifact
- Selects the most informative transactions from the evidence store
- Measures classification and extraction quality against human-validated ground truth using a three-way comparison framework (baseline vs truth, candidate vs truth, delta)
- Challenges its own findings when evidence is thin and requests additional scope if needed
- Diagnoses _why_ regressions occurred (prompt wording, model change, label noise, configuration)
- Proposes targeted prompt patches that human engineers can review
- Applies configurable policy thresholds to produce a binding routing verdict: **PASS**, **WARN**, or **BLOCK**
- Writes a full audit trail, HTML report, Excel log, JSON packet, and trace pack

The entire process runs autonomously under a configurable time budget. No human is required in the loop until the verdict is issued and review is requested.

---

## 2. System Architecture

### 2.1 High-Level Overview

```
Maestro / Orchestrator
        │
        │  MaestroInput JSON Envelope
        ▼
┌─────────────────────────────────────────────────────────────────┐
│                    AgenticTestingFlow                           │
│                    (CrewAI Flow[FlowState])                     │
│                                                                 │
│  Step 1  receive_maestro_payload  ─ validate, create workspace  │
│  Step 2  IntakeDiffAgent          ─ diff artifacts              │
│  Step 3  ScopePlannerAgent        ─ select transactions         │
│  Step 4  EvidenceCollectorAgent   ─ build case bundles          │
│  Step 5  RegressionHunterAgent    ─ hunt findings               │
│  Step 6  ChallengerAgent          ─ challenge evidence          │
│  Step 7  ROUTER                   ─ branch decision             │
│            ├─ needs_more_evidence → Step 8 TargetedRerunAgent   │
│            │                     → Step 9 EvidenceCollector     │
│            │                     → Step 10 RegressionHunter     │
│            └─ sufficient         → Step 11 TrendDriftAgent      │
│  Step 11 TrendDriftAgent          ─ trend analysis              │
│  Step 12 RootCauseAgent           ─ root cause diagnosis        │
│  Step 13 PatchProposalAgent       ─ propose patches             │
│  Step 14 ReportRoutingAgent       ─ produce all outputs         │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
        │
        │  Final Routing Packet (JSON)
        ▼
   Maestro / Orchestrator
   (PASS / WARN / BLOCK + artifacts base64-embedded)
```

### 2.2 Project File Layout

```
document_ai_agentic_testing/
├── main.py                                    # CLI entry (--payload, --json-string, --sample, --serve)
├── pyproject.toml                             # CrewAI deployment config, dependencies
├── data/
│   └── DocumentAI_EvidenceStore.xlsx          # 9-sheet evidence workbook (source of truth)
├── src/agentic_testing/
│   ├── flow.py                                # AgenticTestingFlow — 14-step orchestration
│   ├── main.py                                # CrewAI cloud kickoff() entry point
│   ├── llm_factory.py                         # Model routing (reasoning / structured / coder)
│   ├── agents/
│   │   ├── intake_diff.py                     # IntakeDiff Agent
│   │   ├── scope_planner.py                   # ScopePlanner Agent
│   │   ├── evidence_collector.py              # EvidenceCollector Agent
│   │   ├── regression_hunter.py               # RegressionHunter Agent
│   │   ├── challenger.py                      # Challenger Agent
│   │   ├── targeted_rerun.py                  # TargetedRerun Agent
│   │   ├── trend_drift.py                     # TrendDrift Agent
│   │   ├── root_cause.py                      # RootCause Agent
│   │   ├── patch_proposal.py                  # PatchProposal Agent
│   │   └── report_routing.py                  # ReportRouting Agent
│   ├── tools/
│   │   ├── diff_tools.py                      # Prompt diffing, model change comparison
│   │   ├── evidence_tools.py                  # Case bundle construction
│   │   ├── metrics_tools.py                   # F1, match rate, spike, confidence mismatch
│   │   ├── rerun_tools.py                     # Scope expansion, patch file writing
│   │   ├── excel_reader.py                    # Evidence store reads
│   │   ├── excel_writer.py                    # Audit log and run log writes
│   │   ├── reporting_tools.py                 # HTML report, trace pack, JSON packet
│   │   └── logging_tools.py                   # Model data trace, agent event log
│   ├── schemas/
│   │   ├── maestro_input.py                   # MaestroInput Pydantic envelope (input contract)
│   │   └── crew_output.py                     # FlowState Pydantic model (shared mutable state)
│   ├── prompts/                               # 10 × .txt system prompt files (one per agent)
│   └── config/
│       ├── app_config.yaml
│       └── model_config.yaml
```

---

## 3. CrewAI Integration

### 3.1 Pattern Used

This system uses **CrewAI Flow** — the stateful pipeline pattern — rather than the basic Crew/Task pattern. Each step in the flow is a Python method decorated with `@start()`, `@listen()`, or `@router()`. State (`FlowState`) is a Pydantic model that persists across all 14 steps and carries every agent output forward.

Each agent is a **single-agent Crew** (`Crew(agents=[agent], tasks=[task])`). This gives per-agent tool isolation, per-agent LLM selection, and Pydantic-validated structured outputs (`output_pydantic=...`). Agents do not share context or memory with each other — they communicate exclusively through the `FlowState` dictionary.

### 3.2 Flow Control

The flow uses a **conditional router** after the Challenger agent:

```python
@router(run_challenger_step)
def route_after_challenger(self) -> str:
    if self.state.needs_more_evidence and self.state.rerun_count < max_reruns:
        return "targeted_rerun_branch"
    return "trend_drift_branch"
```

This is the only branch in the flow. All other steps are strictly sequential. The rerun loop (Steps 8–10) can execute up to `max_targeted_reruns` times (default: 3) before the flow unconditionally proceeds to trend analysis.

### 3.3 Deployment Modes

| Mode | How | When |
|------|-----|-------|
| **Local Ollama** | `langchain-ollama` LLM backend | Development and testing |
| **CrewAI+ Cloud** | `pyproject.toml [tool.crewai] type = "flow"` | Production deployment |
| **FastAPI REST** | `--serve` flag, uvicorn on port 8000 | API integration |
| **CLI direct** | `agentic-testing --payload payload.json` | One-shot runs |
| **Python import** | `run_flow_from_maestro_payload(payload_dict)` | Maestro passthrough |

**Important:** When deploying to CrewAI+ cloud, replace Ollama model references in `model_config.yaml` with cloud LLM identifiers (e.g., `claude-sonnet-4-6`, `gpt-4o`). The `llm_factory.py` module routes by role (`reasoning`, `structured`, `coder`) and is the single place to update.

---

## 4. Agents — Detailed Specification

### Agent 1: IntakeDiff Agent

**Role:** Intake Diff Analyst
**LLM:** Reasoning model (deepseek-r1:8b / equivalent)
**Tools:** `diff_prompt_artifacts`, `compare_model_change`, `write_model_data_trace`

**What it does:** Performs a structured semantic diff between the current execution artifact (prompt text + model name) and the previous one. Identifies material changes by section (classification guidance, extraction instructions, scope rules, confidence thresholds). Generates ranked risk hypotheses with confidence scores.

**Output schema:**
```json
{
  "prompt_changed": true,
  "model_changed": false,
  "artifact_diff_summary": ["Added IdentityDocument precision clause", "..."],
  "artifact_diff_details": [
    {"section": "classification", "change_type": "added", "description": "...", "risk_level": "high"}
  ],
  "initial_risk_hypotheses": [
    {"hypothesis": "...", "risk_area": "classification", "risk_level": "high", "confidence": 0.82}
  ],
  "confidence": 0.78
}
```

---

### Agent 2: ScopePlanner Agent

**Role:** Scope Planning Analyst
**LLM:** Reasoning model
**Tools:** Evidence store reader, scope selection tools

**What it does:** Selects the most informative initial slice of transactions to analyze. Respects user-supplied transaction IDs and document type filters when present. When the scope is empty or `allow_agent_to_expand_scope` is true, performs risk-based selection — prioritizing critical document types and transactions most likely to expose regressions based on the change summary and risk hypotheses from IntakeDiff.

**Respects:** `max_initial_transactions`, `scope.transaction_ids`, `scope.document_type_names`, `scope.process_stage_ids`

---

### Agent 3: EvidenceCollector Agent

**Role:** Evidence Collection Specialist
**LLM:** Structured output model (qwen2.5:7b-instruct / equivalent)
**Tools:** `read_document_data`, `read_model_data`, `build_case_bundle`, `validate_case_bundle`

**What it does:** Reads from the Excel evidence store and assembles per-transaction **case bundles**. Each bundle is a self-contained unit of comparison containing:
- `transaction_id`
- `doc_type_truth` (human-validated ground truth)
- `doc_type_baseline` (previous model's prediction)
- `doc_type_candidate` (new model's prediction)
- `classification_confidence_baseline`, `classification_confidence_candidate`
- `fields_truth`, `fields_baseline`, `fields_candidate` (field-level extraction arrays)

Case bundles are the primary data structure passed to RegressionHunter and all downstream agents.

---

### Agent 4: RegressionHunter Agent

**Role:** Regression and Improvement Hunter
**LLM:** Structured output model
**Tools:** `compare_baseline_to_truth`, `compare_candidate_to_truth`, `calculate_doc_type_metrics`, `calculate_field_metrics`, `detect_missing_field_spikes`, `detect_confidence_mismatch`

**What it does:** The analytical core of the system. Applies a **three-way comparison framework**:

```
baseline vs truth  →  OLD quality (pre-change)
candidate vs truth →  NEW quality (post-change)
DELTA = candidate − baseline
```

Produces three finding categories:

| Category | Condition |
|----------|-----------|
| `improvement_findings` | Weighted F1 delta >= +0.05 |
| `regression_findings` | Weighted F1 delta <= −0.03 |
| `hidden_risk_findings` | Confidence > 0.85 on wrong answer (confidence mismatch) |

Also detects **missing field spikes** (>5% increase in empty extraction rate) and applies elevated scrutiny to `critical_doc_types` from the policy config.

**Key metrics produced:**
- `weighted_f1_baseline`, `weighted_f1_candidate`, `weighted_f1_delta`
- `exact_match_rate_baseline`, `exact_match_rate_candidate`
- `empty_rate_baseline`, `empty_rate_candidate`
- `classification_accuracy_baseline`, `classification_accuracy_candidate`
- `doc_type_breakdown` (per-document-type F1 delta, improvement/regression counts)

---

### Agent 5: Challenger Agent

**Role:** Evidence Quality Challenger
**LLM:** Reasoning model
**Tools:** None (pure reasoning)

**What it does:** Acts as an adversarial reviewer. Challenges findings before they reach the verdict stage. Evaluates:

1. **Sample size adequacy:** Requires >= 10 transactions per doc type for credibility; 5–10 is marginal; < 5 is insufficient.
2. **Pattern stability:** Are regressions concentrated in 1–2 transactions (isolated) or spread across many?
3. **Label quality:** Inconsistencies in ground truth labels (stage 2/4 data) that make findings unreliable.

Sets `needs_more_evidence = true` if evidence is insufficient or patterns are isolated, which triggers the router to loop back through TargetedRerun.

---

### Agent 6: TargetedRerun Agent (optional)

**Role:** Scope Expansion Specialist
**LLM:** Structured output model
**Tools:** Evidence store reader, scope expansion tools

**What it does:** When the Challenger requests more evidence, this agent identifies which additional transactions would best resolve the uncertainty — additional samples of under-represented document types, specific transaction ranges, or alternative process stages. Adds new transaction IDs to the selected scope and triggers a re-collection and re-analysis loop.

**Loop limit:** Controlled by `max_targeted_reruns` (default: 3). Prevents infinite loops.

---

### Agent 7: TrendDrift Agent

**Role:** Trend and Drift Analyst
**LLM:** Structured output model
**Tools:** `read_model_data` (historical run traces from `ai.ModelData` sheet)

**What it does:** Analyzes whether the current candidate is part of a sustained trend or an anomaly. Classifies each document type's performance history:

| Pattern | Definition |
|---------|-----------|
| `improving` | Consistent positive F1 delta over >= 3 consecutive runs |
| `declining` | Consistent negative F1 delta over >= 3 consecutive runs |
| `plateau` | < 0.02 F1 change over last 5 runs |
| `sudden_regression` | F1 drop > 0.05 in a single run |
| `converging` | Alternating small +/−, variance shrinking |

Issues `DriftAlert` records for sustained declines and sudden regressions. Assigns a `trend_confidence` score based on number of historical data points and pattern consistency.

---

### Agent 8: RootCause Agent

**Role:** Root Cause Investigator
**LLM:** Reasoning model
**Tools:** None (pure reasoning over structured inputs)

**What it does:** Correlates regression findings with the change summary from IntakeDiff. Separates cause types:

| Cause Type | Description |
|------------|-------------|
| `prompt` | Regression correlates with a specific change in prompt wording |
| `model` | Regression is present across all doc types (model-wide behavioral change) |
| `label` | "Regression" appears in ground truth inconsistencies, not model output |
| `evidence` | Evidence too sparse to determine causality |
| `configuration` | Non-prompt, non-model change (thresholds, routing) responsible |

Produces a ranked list with confidence scores (max realistic confidence: 0.85). Only asserts a `primary_cause` if top candidate confidence > 0.4.

---

### Agent 9: PatchProposal Agent

**Role:** Safe Patch Proposal Architect
**LLM:** Structured output model
**Tools:** `write_patch_candidate` (persists patches to workspace `patch_candidates/` directory)

**What it does:** For each root cause with confidence > 0.3, proposes the smallest safe patch. Applies the **minimal-change principle**:
- Prefer adding one clarifying sentence over rewriting sections
- Prefer exclusion clauses over changing thresholds
- Prefer field-specific extraction instructions over global rule changes

Patch types:
- `exclusion_wording` — "Do not classify X as Y when Z is present"
- `extraction_instructions` — How to extract a specific field
- `classification_guidance` — Improving how a doc type is identified
- `scope_guards` — Guards to prevent out-of-scope document processing

**Every patch has `requires_human_approval = true`. No patch is ever auto-applied.**

---

### Agent 10: ReportRouting Agent

**Role:** Report and Routing Orchestrator
**LLM:** Structured output model
**Tools:** `write_html_report`, `write_trace_pack`, `write_final_packet`, `write_audit_log_event`, `write_sheet`, `append_rows`, `write_model_data_trace`, `log_agent_event`

**What it does:** Synthesizes all prior agent outputs into the final deliverables. Applies policy thresholds to produce the binding verdict:

```
IF weighted_f1_delta < -block_weighted_f1_drop (default 0.05) → BLOCK
ELSE IF weighted_f1_delta < -warn_weighted_f1_drop (default 0.02) → WARN
ELSE → PASS
OVERRIDE: ANY regression in critical_doc_types → BLOCK regardless of F1
```

**Routing actions by verdict:**

| Verdict | block_release | request_human_review | open_defect |
|---------|--------------|---------------------|-------------|
| PASS | false | false | false |
| WARN | false | true | false |
| BLOCK | true | true | true |

---

## 5. Tools — Complete Inventory

| Module | Tool Name | Purpose |
|--------|-----------|---------|
| `diff_tools` | `diff_prompt_artifacts` | Semantic diff of two prompt texts |
| `diff_tools` | `compare_model_change` | Risk analysis of model identity change |
| `evidence_tools` | `read_document_data` | Read DocumentData sheet |
| `evidence_tools` | `build_case_bundle` | Assemble three-way comparison bundle per transaction |
| `evidence_tools` | `validate_case_bundle` | Validate bundle completeness |
| `metrics_tools` | `compare_baseline_to_truth` | Baseline F1, match rate, confidence vs correctness |
| `metrics_tools` | `compare_candidate_to_truth` | Candidate F1, match rate, confidence vs correctness |
| `metrics_tools` | `calculate_doc_type_metrics` | Aggregate per-doc-type F1 and accuracy deltas |
| `metrics_tools` | `calculate_field_metrics` | Per-field extraction match and missing rates |
| `metrics_tools` | `detect_missing_field_spikes` | Flag fields where empty rate spiked |
| `metrics_tools` | `detect_confidence_mismatch` | Flag high-confidence wrong predictions |
| `rerun_tools` | `expand_scope` | Identify additional transactions for rerun |
| `rerun_tools` | `write_patch_candidate` | Persist patch candidate JSON to disk |
| `excel_reader` | `read_model_data` | Read `ai.ModelData` (historical run traces) |
| `excel_writer` | `write_sheet` | Write or overwrite an Excel sheet |
| `excel_writer` | `append_rows` | Append rows to an existing sheet |
| `reporting_tools` | `write_html_report` | Render and write HTML report |
| `reporting_tools` | `write_trace_pack` | Write trace pack JSON |
| `reporting_tools` | `write_final_packet` | Write routing JSON packet |
| `reporting_tools` | `write_audit_log_event` | Append event to audit log |
| `logging_tools` | `write_model_data_trace` | Persist run metrics to `ai.ModelData` |
| `logging_tools` | `log_agent_event` | Write agent event to log sheet |

Total: **22 tools** across 8 modules.

---

## 6. Evidence Store Schema

The evidence store is an Excel workbook (`DocumentAI_EvidenceStore.xlsx`) with 9 sheets:

| Sheet Key | Sheet Name | Contents |
|-----------|------------|---------|
| `document_data` | `DocumentData` | Per-transaction: truth label, baseline prediction, candidate prediction, fields |
| `model_data` | `ai.ModelData` | Historical run metrics — F1, match rate, empty rate per run per doc type |
| `document_types` | `DocumentTypes` | Reference list of document type names and IDs |
| `process_stages` | `ProcessStages` | Reference list of process stage IDs (1=intake, 2=validation, 3=review, 4=approved) |
| `model_names` | `ai.ModelNames` | Reference list of model identifiers |
| `model_stages` | `ai.ModelStages` | Mapping of models to process stages |
| `model_types` | `ai.ModelTypes` | Document types supported per model |
| `exception_logs` | `ExceptionLogs` | Logged processing exceptions |
| `api_data` | `api.APIData` | API call metadata |

Ground truth data lives in `DocumentData`. The `ai.ModelData` sheet accumulates run-over-run historical traces that enable TrendDrift analysis.

---

## 7. Maestro Input Contract

### 7.1 Full Input Envelope

The Maestro payload is a single JSON object validated against the `MaestroInput` Pydantic schema. All fields are typed and validated at flow entry.

```json
{
  "run_request": {
    "run_id": "RUN-2026-03-15-001",
    "process_name": "document_ai_agentic_testing",
    "run_mode": "release_candidate",
    "analysis_mode": "agentic_investigation",
    "time_budget_minutes": 20,
    "max_initial_transactions": 20,
    "max_total_transactions": 100,
    "max_targeted_reruns": 3,
    "triggered_by": "Maestro"
  },
  "scope": {
    "date_from": "2026-03-01",
    "date_to": "2026-03-15",
    "transaction_ids": [],
    "document_type_names": [],
    "process_stage_ids": [1, 2, 3, 4],
    "allow_agent_to_expand_scope": true
  },
  "current_execution_artifact": {
    "prompt_name": "classification_extraction_bundle",
    "prompt_version_label": "bundle_v17",
    "prompt_text": "<full resolved prompt text>",
    "model_name": "llama-3.1-8b-instant",
    "artifact_hash": "sha256-current-bundle-v17"
  },
  "previous_execution_artifact": {
    "prompt_name": "classification_extraction_bundle",
    "prompt_version_label": "bundle_v16",
    "prompt_text": "<full resolved prompt text>",
    "model_name": "llama-3.1-8b-instant",
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
    "run_workspace_key": "RUN-2026-03-15-001",
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

### 7.2 Field Reference

**`run_request`**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `run_id` | string | required | Unique run identifier. Convention: `RUN-YYYY-MM-DD-NNN` |
| `run_mode` | string | `release_candidate` | `release_candidate` \| `scheduled` \| `manual` |
| `analysis_mode` | string | `agentic_investigation` | Determines agent reasoning depth |
| `time_budget_minutes` | int | 20 | Soft time limit (agents self-limit iterations) |
| `max_initial_transactions` | int | 20 | Max transactions in first scope selection |
| `max_total_transactions` | int | 100 | Hard cap across all reruns |
| `max_targeted_reruns` | int | 3 | Max iterations of the Challenger→Rerun loop |

**`scope`**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `date_from` / `date_to` | string | required | ISO date range for evidence selection |
| `transaction_ids` | int[] | `[]` | Empty = agent selects based on risk |
| `document_type_names` | string[] | `[]` | Empty = agent selects across all types |
| `process_stage_ids` | int[] | `[1,2,3,4]` | Which process stages to include |
| `allow_agent_to_expand_scope` | bool | `true` | Enables TargetedRerun loop |

**`policy`**

| Field | Type | Default | Meaning |
|-------|------|---------|---------|
| `critical_doc_types` | string[] | `[IdentityDocument, Passport, ApplicationForm]` | Any regression here forces BLOCK |
| `warn_weighted_f1_drop` | float | 0.02 | F1 drop threshold for WARN verdict |
| `block_weighted_f1_drop` | float | 0.05 | F1 drop threshold for BLOCK verdict |
| `block_empty_rate_increase` | float | 0.03 | Extraction empty rate increase threshold |
| `block_exception_rate_increase` | float | 0.02 | Processing exception rate threshold |

---

## 8. Maestro Output Contract

The flow returns a single JSON object (`FinalRoutingOutput`) to Maestro. In addition to the structured JSON, artifacts are base64-embedded under `artifacts.embedded_files` (controllable via `AGENTIC_EMBED_ARTIFACTS_BASE64` environment variable, max file size `AGENTIC_MAX_EMBED_FILE_BYTES`, default 5 MB).

### 8.1 Output Envelope

```json
{
  "run_id": "RUN-2026-03-15-001",
  "status": "completed",
  "verdict": "PASS",
  "confidence": 0.81,
  "analysis_scope": {
    "transaction_ids": [1001, 1002, 1003],
    "doc_types": ["IdentityDocument", "Passport"],
    "date_from": "2026-03-01",
    "date_to": "2026-03-15",
    "total_transactions": 3
  },
  "change_summary": { "...IntakeDiff output..." },
  "summary_metrics": {
    "weighted_f1_baseline": 0.872,
    "weighted_f1_candidate": 0.891,
    "weighted_f1_delta": 0.019,
    "exact_match_rate_baseline": 0.803,
    "exact_match_rate_candidate": 0.821,
    "empty_rate_baseline": 0.041,
    "empty_rate_candidate": 0.038,
    "classification_accuracy_baseline": 0.933,
    "classification_accuracy_candidate": 0.950
  },
  "improvements": [ { "...Finding..." } ],
  "regressions": [],
  "hidden_risks": [],
  "root_causes": [],
  "agentic_actions_taken": [
    "IntakeDiff: identified prompt change in classification guidance section",
    "ScopePlanner: selected 3 transactions covering 2 critical doc types",
    "..."
  ],
  "recommended_actions": [
    "Monitor Passport classification accuracy over next 3 release cycles",
    "..."
  ],
  "patch_candidates": [],
  "routing": {
    "block_release": false,
    "request_human_review": false,
    "open_defect": false,
    "notify_roles": [],
    "verdict": "PASS",
    "verdict_rationale": "Candidate shows +0.019 F1 improvement. No critical doc type regressions. Evidence sample adequate."
  },
  "artifacts": {
    "report_html_uri": "managed://reports/RUN-2026-03-15-001/report.html",
    "run_json_uri": "managed://packets/RUN-2026-03-15-001/routing.json",
    "excel_log_uri": "managed://excel/RUN-2026-03-15-001/run_log.xlsx",
    "audit_log_uri": "managed://logs/RUN-2026-03-15-001/AgenticTesting_AuditLog.xlsx",
    "trace_pack_uri": "managed://traces/RUN-2026-03-15-001/trace.zip",
    "embedded_files": {
      "report_html": {
        "filename": "report.html",
        "mime_type": "text/html",
        "encoding": "base64",
        "data": "<base64 string>",
        "size_bytes": 48320,
        "skipped": false
      }
    }
  }
}
```

### 8.2 Error Response

If input validation fails or an unhandled exception occurs, the flow returns an error envelope instead of a routing packet. Maestro must always check for the presence of `"error"` key before treating the response as a valid verdict.

```json
{
  "error": "validation_error",
  "detail": [ { "...pydantic error list..." } ],
  "run_id": "RUN-2026-03-15-001",
  "verdict": "ERROR",
  "block_release": true,
  "request_human_review": true
}
```

---

## 9. How to Call It

### 9.1 Python (direct import — recommended for Maestro integration)

```python
from agentic_testing.flow import run_flow_from_maestro_payload

payload = { ...maestro_input_dict... }

# Also accepts a JSON string:
# payload = json.dumps(maestro_input_dict)

result = run_flow_from_maestro_payload(payload)

if result.get("error"):
    # Handle error — always block on error
    block = True
else:
    verdict = result["routing"]["verdict"]   # "PASS" | "WARN" | "BLOCK"
    block = result["routing"]["block_release"]
    html_report = result["artifacts"]["embedded_files"].get("report_html", {}).get("data")
```

### 9.2 CLI

```bash
# From a payload file
agentic-testing --payload data/test_maestro_payload.json

# From a JSON string
agentic-testing --json-string '{"run_request": {...}, ...}'

# Run with sample payload (built-in smoke test)
agentic-testing --sample

# Start REST API server
agentic-testing --serve
```

### 9.3 REST API

```
POST http://localhost:8000/run
Content-Type: application/json

{ ...MaestroInput envelope... }

→ 200 OK  { ...FinalRoutingOutput... }
→ 422     { "detail": "validation error detail" }
→ 500     { "error": "...", "verdict": "ERROR", "block_release": true }
```

### 9.4 CrewAI Cloud

The `pyproject.toml` declares `[tool.crewai] type = "flow"`. The standard CrewAI kickoff entry point in `src/agentic_testing/main.py` calls:

```python
from agentic_testing.flow import AgenticTestingFlow

def kickoff():
    flow = AgenticTestingFlow()
    flow.kickoff()
```

Inputs are passed via CrewAI's managed input injection. The `MaestroInput` JSON must be provided as the flow's `inputs` dictionary.

---

## 10. Models and LLM Configuration

### 10.1 Local (Development) — Ollama

Three model roles are configured in `model_config.yaml`:

| Role | Model | Purpose |
|------|-------|---------|
| `reasoning` | `deepseek-r1:8b` | Deep analysis, root cause, Challenger, IntakeDiff |
| `structured` | `qwen2.5:7b-instruct` | Structured JSON output, metrics, reporting |
| `coder` | `qwen2.5-coder:7b-instruct` | Patch proposal, code-adjacent reasoning |

Models are served via Ollama on `http://localhost:11434` (default). The `llm_factory.py` file is the single configuration point for LLM routing. Agents specify their role (`reasoning` or `structured`) and the factory resolves the actual LLM object.

### 10.2 Cloud (Production)

For production deployment, update `model_config.yaml` to reference cloud endpoints. Suggested mappings:

| Role | Recommended Cloud Model |
|------|------------------------|
| `reasoning` | `claude-opus-4-6` or `claude-sonnet-4-6` |
| `structured` | `claude-sonnet-4-6` or `gpt-4o` |
| `coder` | `claude-sonnet-4-6` |

### 10.3 Cost Considerations

Cost is entirely determined by LLM choice and transaction volume. The framework is LLM-agnostic at the factory layer.

**Local Ollama:** Zero API cost. Compute cost depends on hardware. An 8B parameter model on a mid-range GPU (RTX 3080+) processes a typical 20-transaction run in approximately 3–8 minutes depending on prompt and case bundle size.

**Cloud LLMs:** Each run invokes agents sequentially. Approximate token budget per run at 20 initial transactions:
- IntakeDiff: ~2,000–4,000 tokens (prompt diff)
- ScopePlanner: ~1,000–2,000 tokens
- EvidenceCollector: ~3,000–6,000 tokens (bundle construction)
- RegressionHunter: ~8,000–20,000 tokens (case bundles passed in full)
- Challenger: ~3,000–5,000 tokens
- TrendDrift: ~2,000–4,000 tokens
- RootCause: ~2,000–4,000 tokens
- PatchProposal: ~2,000–4,000 tokens
- ReportRouting: ~5,000–10,000 tokens

**Estimated total: 28,000–59,000 tokens per run at 20 transactions.** At cloud LLM pricing (~$3–15 per million tokens for frontier models), a typical run costs $0.08–$0.90 depending on model and transaction count. With 100 transactions (max scope), expect 2–5× that range.

---

## 11. Generated Outputs

Each run produces a managed workspace at `workspaces/{run_id}/`:

| Output | Path | Description |
|--------|------|-------------|
| HTML Report | `workspaces/{run_id}/report.html` | Human-readable report with verdict badge, metrics table, findings list, patch candidates |
| JSON Routing Packet | `workspaces/{run_id}/latest_run.json` | Machine-readable verdict + all agent outputs |
| Excel Run Log | `workspaces/{run_id}/outputs/Run_REPORT.xlsx` | Tabular log of findings for spreadsheet analysis |
| Trace Pack | `workspaces/{run_id}/trace_pack.json` | Full agent reasoning trace for debugging |
| Audit Log | `workspaces/{run_id}/logs/AgenticTesting_AuditLog.xlsx` | Step-by-step event log with timestamps |
| Patch Candidates | `workspaces/{run_id}/patch_candidates/*.json` | Per-patch JSON files for human review |
| Maestro Input | `workspaces/{run_id}/maestro_input.json` | Copy of the input payload for traceability |

---

## 12. Benefits

**For Release Engineering**
- Provides a binding automated verdict (PASS/WARN/BLOCK) before any release, reducing reliance on manual QA spot-checks
- Catches hidden risks (high-confidence wrong answers) that aggregate F1 metrics would miss
- Configurable thresholds mean teams control how strict the gate is

**For Prompt Engineers**
- Identifies _which section_ of the prompt caused a regression, not just that a regression exists
- Proposes minimal targeted patch candidates, reducing iteration time
- Shows improvement and regression patterns side by side with ground truth

**For Quality Analysts**
- Eliminates the manual three-way comparison task (baseline vs candidate vs truth)
- Produces fully reproducible, audit-trailed analysis tied to a specific run ID
- Documents every agent action in the audit log for compliance

**For Operations**
- Trend drift analysis detects slow model decay before it becomes a production incident
- Historical `ai.ModelData` trace accumulates automatically across runs
- All outputs are available as base64-embedded files in the routing packet for immediate downstream processing by Maestro

**For Architecture**
- Single, well-typed input contract (MaestroInput) and output contract (FinalRoutingOutput)
- Evidence store is decoupled from the flow — swap the backend (Excel → database) by replacing the reader tools
- Agents are individually testable; each is a pure function `run_agent(state_dict) → dict`
- Rerun loop prevents premature decisions without human intervention

---

## 13. Integration Patterns

### Pattern A: Maestro-Triggered Release Gate

Maestro calls `run_flow_from_maestro_payload(payload)` synchronously as part of the release pipeline. The returned `routing.block_release` flag determines whether the release proceeds. The `routing.verdict` and `routing.verdict_rationale` are surfaced to the release engineer dashboard.

### Pattern B: Scheduled Monitoring

Set `run_mode = "scheduled"` and supply a date range spanning the last N days. A cron job calls the CLI (`agentic-testing --payload ...`) nightly. The trend drift output accumulates in `ai.ModelData`, enabling degradation detection before manual reports are triggered.

### Pattern C: REST API Integration

Any system with HTTP access can trigger a run via `POST /run`. The response is the complete `FinalRoutingOutput` JSON including embedded artifact files. Suitable for CI/CD pipeline integration (e.g., GitHub Actions, Jenkins post-build step).

### Pattern D: Human-in-the-Loop Review

When `verdict = "WARN"`, the flow sets `request_human_review = true` and populates `recommended_actions` with specific, actionable items. The patch candidates in `workspaces/{run_id}/patch_candidates/` provide draft prompt changes for prompt engineers to review and approve before the next release cycle.

---

## 14. Dependencies

```
crewai >= 0.80.0          # Core multi-agent framework and Flow orchestration
crewai-tools >= 0.20.0    # BaseTool, tool utilities
langchain-community >= 0.3.0
langchain-ollama >= 0.2.0 # Local LLM backend (dev)
pydantic >= 2.7.0         # Schema validation (input, output, all agent schemas)
pandas >= 2.2.0           # Excel data manipulation
openpyxl >= 3.1.2         # Excel read/write
jinja2 >= 3.1.4           # HTML report templating
reportlab >= 4.2.0        # PDF report generation
PyYAML >= 6.0.1           # Config file parsing
python-dotenv >= 1.0.0    # Environment variable management
fastapi >= 0.115.0        # REST API server (--serve mode)
uvicorn >= 0.30.0         # ASGI server
httpx >= 0.27.0           # HTTP client
```

Python 3.11+ required (type annotation syntax used throughout).

---

*Document generated 2026-03-15 from source analysis of document_ai_agentic_testing v1.0.0*
