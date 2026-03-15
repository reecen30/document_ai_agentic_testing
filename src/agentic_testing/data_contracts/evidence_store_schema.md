# Evidence Store Schema

## Overview

The Evidence Store is a read-only Excel workbook named `DocumentAI_EvidenceStore.xlsx`. It serves as the single source of truth for all document AI processing data used by the agentic testing system. Agents are strictly prohibited from writing to this workbook. All reads are performed through the designated Excel reader tools. The workbook captures all historical processing runs, ground truth labels, model outputs, and exception logs required to evaluate the quality of document AI extraction and classification across process stages.

The file path is configured via the `EVIDENCE_STORE_PATH` environment variable or the `evidence_store.store_ref` field in the Maestro input payload.

---

## Sheet: DocumentData

The primary sheet containing per-field extraction and classification records for every document processed through the pipeline.

| Column | Type | Description |
|--------|------|-------------|
| DocumentDataID | int (PK) | Unique record identifier |
| TransactionID | int (FK) | Links to the parent transaction |
| DocumentID | string | Unique document identifier within the transaction |
| ProcessStageID | int (FK) | Stage at which this record was created (see ProcessStage interpretation) |
| DocumentTypeID | int (FK) | Links to DocumentTypes sheet |
| DocumentTypeName | string | Human-readable document type label |
| StartPage | int | Page number within the document where the field was found |
| Confidence | float | Overall model confidence score for the document classification (0.0–1.0) |
| OcrConfidence | float | OCR engine confidence for the page/region (0.0–1.0) |
| Field | string | Name of the extracted field (e.g., "FirstName", "DateOfBirth") |
| IsMissing | bool | True if the field was expected but not found by the model |
| Value | string | Extracted or ground-truth value for the field |
| FieldConfidence | float | Model confidence for this specific field extraction (0.0–1.0) |
| FieldOcrConfidence | float | OCR confidence for this specific field region (0.0–1.0) |
| Created_By | string | Process or user that created the record |
| CreatedDateTime | datetime | UTC timestamp when the record was written |
| Active | bool | Soft-delete flag; agents only read records where Active = True |

### ProcessStage Interpretation

The `ProcessStageID` column is critical for determining the role of each record in quality analysis:

| ProcessStageID | Stage Name | Role in Analysis |
|----------------|------------|-----------------|
| 1 | Pre Classify | Baseline classification — the output produced by the current production model (old prompt/model). Used as `baseline_prediction`. |
| 2 | Validated Post Classified | Truth classification — human-validated ground truth label. Used as `validated_truth` for classification quality. |
| 3 | Pre Extract | Baseline extraction — field-level output from the current production model. Used as `baseline_prediction` for extraction fields. |
| 4 | Validated Post Extracted | Truth extraction — human-validated field values. Used as `validated_truth` for extraction quality. |

The candidate prediction (new prompt/model output) is sourced from the `ai.ModelData` sheet via the linked `TransactionID` and the appropriate `ModelStageID`.

---

## Sheet: ai.ModelData

Contains input and output argument records for every model invocation, enabling the agentic system to retrieve candidate (new) model outputs for comparison.

| Column | Type | Description |
|--------|------|-------------|
| ModelDataID | int (PK) | Unique record identifier |
| TransactionID | int (FK) | Links to the parent transaction |
| ModelStageID | int (FK) | 1 = Input argument, 2 = Output argument (see ai.ModelStages) |
| ModelTypeID | int (FK) | 1 = LLM, 2 = Agent (see ai.ModelTypes) |
| ModelNameID | int (FK) | Links to ai.ModelNames for the model identifier |
| ModelVersion | string | Version string of the model at time of invocation |
| In_Argument_Field | string | Name of the input or output argument field |
| In_Argument_Value | string | Value of the input or output argument field |
| RecordDateTime | datetime | UTC timestamp of the model invocation |
| Active | bool | Soft-delete flag; agents only read records where Active = True |

To retrieve candidate predictions: filter by `TransactionID`, join on `ModelNameID` matching the candidate execution artifact's model name, and `ModelStageID = 2` (Output).

---

## Sheet: DocumentTypes

Reference table mapping numeric IDs to document type names.

| Column | Type | Description |
|--------|------|-------------|
| DocumentTypeID | int (PK) | Unique identifier |
| DocumentType | string | Human-readable document type name |

### Known Document Type Values

| DocumentTypeID | DocumentType |
|----------------|-------------|
| 1 | ApplicationForm |
| 2 | Resolution |
| 3 | Windeed |
| 4 | Passport |
| 5 | IdentityDocument |
| 6 | ProductFormsBTB |
| 7 | ProductFormsIFB |
| 8 | ProductFormsICIB |
| 9 | Income_Statement |
| 10 | Balance_Sheet |
| 11 | CashFlow |
| 12 | Debtors |
| 13 | Creditors |
| 14 | AFS |
| 15 | Other |
| 16 | RelatedPartyForm |

Critical document types subject to stricter policy thresholds: `IdentityDocument`, `Passport`, `ApplicationForm`.

---

## Sheet: ProcessStages

Reference table describing each process stage in the document AI pipeline.

| Column | Type | Description |
|--------|------|-------------|
| ProcessStageID | int (PK) | Unique identifier |
| ProcessStageName | string | Human-readable stage name |
| Description | string | What occurs at this stage |

Stage IDs 1–4 correspond to the classify and extract pipeline phases as described in the ProcessStage Interpretation section above.

---

## Sheet: ai.ModelStages

Defines whether a `ai.ModelData` record represents an input or output argument.

| ModelStageID | ModelStageName | Description |
|-------------|----------------|-------------|
| 1 | Input | The argument was passed into the model as an input |
| 2 | Output | The argument was returned by the model as an output |

When querying for candidate predictions, agents must filter on `ModelStageID = 2`.

---

## Sheet: ai.ModelTypes

Classifies the type of model that produced a record.

| ModelTypeID | ModelTypeName | Description |
|------------|---------------|-------------|
| 1 | LLM | A large language model invocation |
| 2 | Agent | An agentic system invocation (e.g. CrewAI agent) |

---

## Sheet: ai.ModelNames

Reference table mapping numeric IDs to model name strings.

| Column | Type | Description |
|--------|------|-------------|
| ModelNameID | int (PK) | Unique identifier |
| ModelName | string | Full model name string (e.g. `deepseek-r1:8b`, `qwen2.5:7b-instruct`) |
| ModelFamily | string | Model family grouping |
| Active | bool | Whether this model is currently active |

Agents use this sheet to resolve `ModelNameID` values from `ai.ModelData` to human-readable model names for comparison against execution artifacts.

---

## Sheet: ExceptionLogs

Records all exceptions and errors raised during document processing for any transaction.

| Column | Type | Description |
|--------|------|-------------|
| ExceptionLogID | int (PK) | Unique identifier |
| TransactionID | int (FK) | Linked transaction |
| DocumentID | string | Document that triggered the exception |
| ProcessStageID | int (FK) | Stage at which the exception occurred |
| ExceptionType | string | Classification of the exception (e.g. OcrFailure, ModelTimeout, ParseError) |
| ExceptionMessage | string | Full exception message or stack trace summary |
| Severity | string | low / medium / high / critical |
| CreatedDateTime | datetime | UTC timestamp of the exception |
| Active | bool | Soft-delete flag |

Agents compare exception rates between baseline and candidate runs to detect exception rate increases that would trigger a BLOCK verdict under policy thresholds.

---

## Sheet: api.APIData

Records API call metadata for all external service calls made during transaction processing.

| Column | Type | Description |
|--------|------|-------------|
| APIDataID | int (PK) | Unique identifier |
| TransactionID | int (FK) | Linked transaction |
| APIName | string | Name of the external API called |
| Endpoint | string | URL or endpoint identifier |
| RequestDateTime | datetime | UTC timestamp of the request |
| ResponseCode | int | HTTP or service response code |
| DurationMs | int | Request duration in milliseconds |
| Success | bool | Whether the API call succeeded |
| ErrorMessage | string | Error message if the call failed |
| Active | bool | Soft-delete flag |

---

## Data Model: Quality Comparison Framework

The agentic testing system performs three distinct comparisons using data from the evidence store:

### 1. Old Quality (Baseline vs Truth)
- **Baseline prediction**: `DocumentData` records with `ProcessStageID = 1` (classification) or `ProcessStageID = 3` (extraction)
- **Validated truth**: `DocumentData` records with `ProcessStageID = 2` (classification) or `ProcessStageID = 4` (extraction)
- **Purpose**: Establishes the quality baseline of the currently deployed model/prompt
- **Metrics produced**: Baseline F1, baseline accuracy, baseline empty rate, baseline exception rate

### 2. New Quality (Candidate vs Truth)
- **Candidate prediction**: `ai.ModelData` records with `ModelStageID = 2` (Output) for the candidate execution artifact
- **Validated truth**: `DocumentData` records with `ProcessStageID = 2` or `ProcessStageID = 4`
- **Purpose**: Measures the quality of the new prompt/model version under evaluation
- **Metrics produced**: Candidate F1, candidate accuracy, candidate empty rate, candidate exception rate

### 3. Behavior Change (Baseline vs Candidate)
- **Baseline prediction**: `DocumentData` records with `ProcessStageID = 1` or `ProcessStageID = 3`
- **Candidate prediction**: `ai.ModelData` records with `ModelStageID = 2`
- **Purpose**: Detects behavioral drift between old and new versions independent of ground truth quality
- **Metrics produced**: Agreement rate, flip rate, silent regression indicators

All three comparisons are assembled by the `Agentic_EvidenceCollector` agent into case bundles and evaluated by `Agentic_RegressionHunter`.
