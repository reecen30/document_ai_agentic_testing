"""
Generate a Word (.docx) architecture document for this project.

This script writes a lightweight OOXML package without external dependencies.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape
import zipfile


W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _w_t(text: str) -> str:
    attrs = ' xml:space="preserve"' if text[:1] == " " or text[-1:] == " " else ""
    return f"<w:t{attrs}>{escape(text)}</w:t>"


def _paragraph(
    text: str,
    *,
    bold: bool = False,
    size_half_points: int | None = None,
    center: bool = False,
) -> str:
    run_props = []
    if bold:
        run_props.append("<w:b/>")
    if size_half_points is not None:
        run_props.append(f'<w:sz w:val="{size_half_points}"/>')
    run_props_xml = f"<w:rPr>{''.join(run_props)}</w:rPr>" if run_props else ""
    p_props_xml = "<w:pPr><w:jc w:val=\"center\"/></w:pPr>" if center else ""
    return f"<w:p>{p_props_xml}<w:r>{run_props_xml}{_w_t(text)}</w:r></w:p>"


def _blank_paragraph() -> str:
    return "<w:p/>"


def build_document_xml(lines: list[dict]) -> str:
    body_parts: list[str] = []
    for item in lines:
        line_type = item["type"]
        if line_type == "title":
            body_parts.append(
                _paragraph(
                    item["text"],
                    bold=True,
                    size_half_points=36,
                    center=True,
                )
            )
        elif line_type == "h1":
            body_parts.append(_paragraph(item["text"], bold=True, size_half_points=28))
        elif line_type == "h2":
            body_parts.append(_paragraph(item["text"], bold=True, size_half_points=24))
        elif line_type == "bullet":
            body_parts.append(_paragraph(f"- {item['text']}"))
        elif line_type == "blank":
            body_parts.append(_blank_paragraph())
        else:
            body_parts.append(_paragraph(item["text"]))

    body_parts.append(
        (
            "<w:sectPr>"
            '<w:pgSz w:w="12240" w:h="15840"/>'
            '<w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440" '
            'w:header="708" w:footer="708" w:gutter="0"/>'
            "</w:sectPr>"
        )
    )

    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{W_NS}">'
        f"<w:body>{''.join(body_parts)}</w:body>"
        "</w:document>"
    )


def build_content() -> list[dict]:
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    lines: list[dict] = [
        {"type": "title", "text": "Document AI Agentic Testing Architecture"},
        {"type": "p", "text": f"Generated: {generated}"},
        {"type": "p", "text": "Version: 1.0 (Code-Aligned Documentation)"},
        {"type": "blank"},
        {"type": "h1", "text": "A. Why This Project Exists"},
        {
            "type": "p",
            "text": (
                "This project acts as a release quality gate for Document AI prompt/model changes. "
                "Before promoting a new execution artifact, it checks whether the candidate behavior "
                "improved, stayed stable, or regressed against validated truth data."
            ),
        },
        {
            "type": "bullet",
            "text": "Primary goal: prevent silent regressions from reaching production.",
        },
        {
            "type": "bullet",
            "text": "Secondary goal: provide actionable root-cause and patch guidance when regressions appear.",
        },
        {
            "type": "bullet",
            "text": "Operational goal: return routing instructions that Maestro can branch on (PASS/WARN/BLOCK).",
        },
        {"type": "blank"},
        {"type": "h1", "text": "B. What The System Is"},
        {
            "type": "p",
            "text": (
                "A CrewAI flow orchestrates 10 specialized agents over a 14-step pipeline. "
                "The flow ingests Maestro payloads, reads Excel-based evidence, compares baseline/candidate/truth, "
                "challenges evidence sufficiency, optionally expands scope, and returns a final routing packet."
            ),
        },
        {"type": "bullet", "text": "Runtime model stack: local Ollama models (deepseek-r1, qwen2.5, qwen2.5-coder)."},
        {"type": "bullet", "text": "Data substrate: Excel workbooks for evidence, audit logs, and run reports."},
        {"type": "bullet", "text": "Execution entry points: CLI payload mode, sample mode, webhook server mode, CrewAI cloud kickoff."},
        {"type": "blank"},
        {"type": "h1", "text": "C. How It Works (End-To-End Flow)"},
        {"type": "p", "text": "Flow owner: src/agentic_testing/flow.py (AgenticTestingFlow)."},
        {"type": "p", "text": "Step 1. receive_maestro_payload -> validate state, create workspace, persist maestro_input.json"},
        {"type": "p", "text": "Step 2. run_intake_diff -> compare current vs previous artifact; produce change summary + risk hypotheses"},
        {"type": "p", "text": "Step 3. run_scope_planner -> choose initial transactions/doc types and analysis plan"},
        {"type": "p", "text": "Step 4. run_evidence_collector -> collect rows and assemble per-transaction case bundles"},
        {"type": "p", "text": "Step 5. run_regression_hunter -> classify improvements/regressions/hidden risks"},
        {"type": "p", "text": "Step 6. run_challenger -> evaluate confidence and whether evidence is sufficient"},
        {"type": "p", "text": "Step 7. route_after_challenger -> branch to targeted rerun or trend analysis"},
        {"type": "p", "text": "Step 8. run_targeted_rerun (optional) -> propose minimal scope expansion"},
        {"type": "p", "text": "Step 9. run_evidence_refresh (optional) -> collect evidence again"},
        {"type": "p", "text": "Step 10. run_regression_refresh (optional) -> rerun regression hunting"},
        {"type": "p", "text": "Step 11. run_trend_drift -> evaluate performance trend/drift"},
        {"type": "p", "text": "Step 12. run_root_cause -> rank likely causes"},
        {"type": "p", "text": "Step 13. run_patch_proposal -> generate patch candidates + experiments"},
        {"type": "p", "text": "Step 14. run_report_routing -> write artifacts and return final routing packet"},
        {"type": "blank"},
        {"type": "h2", "text": "Branch Logic"},
        {"type": "p", "text": "If needs_more_evidence is true and rerun_count < max_targeted_reruns -> targeted rerun branch."},
        {"type": "p", "text": "Else -> trend drift branch."},
        {"type": "blank"},
        {"type": "h1", "text": "D. Architecture Layers"},
        {"type": "h2", "text": "1) Interface Layer"},
        {"type": "bullet", "text": "main.py CLI: --payload, --json-string, --sample, --serve."},
        {"type": "bullet", "text": "HTTP endpoint in serve mode: POST /run returns final packet JSON."},
        {"type": "bullet", "text": "CrewAI cloud entry: src/agentic_testing/main.py kickoff(inputs)."},
        {"type": "h2", "text": "2) Orchestration Layer"},
        {"type": "bullet", "text": "AgenticTestingFlow manages sequencing, routing, state mutation, and audit events."},
        {"type": "bullet", "text": "FlowState is the shared contract between all steps."},
        {"type": "h2", "text": "3) Agent Layer"},
        {"type": "bullet", "text": "10 agents: IntakeDiff, ScopePlanner, EvidenceCollector, RegressionHunter, Challenger, TargetedRerun, TrendDrift, RootCause, PatchProposal, ReportRouting."},
        {"type": "h2", "text": "4) Tool Layer"},
        {"type": "bullet", "text": "excel_reader: read evidence + lookup sheets."},
        {"type": "bullet", "text": "evidence_tools: build case bundles + summarize completeness."},
        {"type": "bullet", "text": "metrics_tools: compute baseline/candidate deltas and anomaly flags."},
        {"type": "bullet", "text": "diff_tools: prompt/model change comparison."},
        {"type": "bullet", "text": "rerun_tools: scope expansion + rerun request + patch file writes."},
        {"type": "bullet", "text": "reporting_tools/excel_writer/logging_tools: output generation and auditability."},
        {"type": "h2", "text": "5) Data Layer"},
        {"type": "bullet", "text": "DocumentAI_EvidenceStore.xlsx (source evidence)."},
        {"type": "bullet", "text": "AgenticTesting_AuditLog.xlsx (event and tool call history)."},
        {"type": "bullet", "text": "Run_TEMPLATE_Report.xlsx (run log template)."},
        {"type": "h2", "text": "6) Output Layer"},
        {"type": "bullet", "text": "latest_run.json final packet, HTML report, trace pack JSON, patch candidate JSON files, Excel logs."},
        {"type": "blank"},
        {"type": "h1", "text": "E. Inputs"},
        {"type": "h2", "text": "External Payload Inputs (MaestroInput)"},
        {"type": "bullet", "text": "run_request: run_id, budgets, rerun limits, mode metadata."},
        {"type": "bullet", "text": "scope: date range, optional transaction/doc type filters, stage filters, expand permission."},
        {"type": "bullet", "text": "current_execution_artifact and previous_execution_artifact: prompt/model metadata and full prompt text."},
        {"type": "bullet", "text": "evidence_store: workbook reference and sheet map."},
        {"type": "bullet", "text": "storage: workspace namespace and base path settings."},
        {"type": "bullet", "text": "policy: warning/block thresholds and critical doc types."},
        {"type": "bullet", "text": "requested_outputs: output artifact toggles."},
        {"type": "h2", "text": "Runtime Inputs"},
        {"type": "bullet", "text": "WORKSPACE_BASE_PATH and EVIDENCE_STORE_PATH environment variables."},
        {"type": "bullet", "text": "Ollama endpoint via OLLAMA_BASE_URL."},
        {"type": "blank"},
        {"type": "h1", "text": "F. Outputs"},
        {"type": "h2", "text": "Primary Output"},
        {
            "type": "p",
            "text": (
                "The flow returns final_run_packet to caller/maestro. "
                "Core fields include verdict, confidence, routing booleans, findings, root causes, "
                "patch candidates, artifact URIs, and run metadata."
            ),
        },
        {"type": "h2", "text": "Artifact Outputs"},
        {"type": "bullet", "text": "Workspace run folder with logs/, outputs/, patch_candidates/."},
        {"type": "bullet", "text": "report.html (from reporting_tools.write_html_report)."},
        {"type": "bullet", "text": "latest_run.json (from reporting_tools.write_final_packet)."},
        {"type": "bullet", "text": "trace_pack.json (from reporting_tools.write_trace_pack)."},
        {"type": "bullet", "text": "Excel sheets for run/audit events (via excel_writer + logging_tools)."},
        {"type": "blank"},
        {"type": "h1", "text": "G. Agent Breakdown (What + How + Input/Output)"},
        {"type": "h2", "text": "IntakeDiff"},
        {"type": "bullet", "text": "What: detects prompt/model changes and proposes initial risk hypotheses."},
        {"type": "bullet", "text": "Key IO: artifact text/model in -> change summary + risk hypotheses out."},
        {"type": "h2", "text": "ScopePlanner"},
        {"type": "bullet", "text": "What: selects informative initial transactions/doc types under budget."},
        {"type": "bullet", "text": "Key IO: change summary + scope + evidence metadata in -> selected IDs/doc types + analysis plan out."},
        {"type": "h2", "text": "EvidenceCollector"},
        {"type": "bullet", "text": "What: builds normalized case bundles per transaction."},
        {"type": "bullet", "text": "Key IO: selected IDs in -> case_bundles + evidence_summary out."},
        {"type": "h2", "text": "RegressionHunter"},
        {"type": "bullet", "text": "What: computes candidate-vs-baseline deltas against truth."},
        {"type": "bullet", "text": "Key IO: case bundles + policy in -> improvements/regressions/hidden risks + metrics out."},
        {"type": "h2", "text": "Challenger"},
        {"type": "bullet", "text": "What: checks sample adequacy/stability and challenges weak conclusions."},
        {"type": "bullet", "text": "Key IO: evidence + findings in -> confidence assessment + needs_more_evidence out."},
        {"type": "h2", "text": "TargetedRerun"},
        {"type": "bullet", "text": "What: proposes minimal additional scope to resolve uncertainty."},
        {"type": "bullet", "text": "Key IO: challenge notes + hidden risks in -> expansion request + transactions_added out."},
        {"type": "h2", "text": "TrendDrift"},
        {"type": "bullet", "text": "What: evaluates longitudinal movement (improving/declining/plateau/sudden regression)."},
        {"type": "bullet", "text": "Key IO: historical model data + current findings in -> trend summary + drift alerts out."},
        {"type": "h2", "text": "RootCause"},
        {"type": "bullet", "text": "What: correlates regressions with artifact changes and context."},
        {"type": "bullet", "text": "Key IO: change summary + findings + trend in -> ranked root causes out."},
        {"type": "h2", "text": "PatchProposal"},
        {"type": "bullet", "text": "What: proposes minimum-change remediations and experiments."},
        {"type": "bullet", "text": "Key IO: root causes + findings in -> patch_candidates + recommended_experiments out."},
        {"type": "h2", "text": "ReportRouting"},
        {"type": "bullet", "text": "What: final synthesis, artifact writing, and routing decision for Maestro."},
        {"type": "bullet", "text": "Key IO: full state in -> final packet + output artifacts out."},
        {"type": "blank"},
        {"type": "h1", "text": "H. Data Model and Stage Mapping"},
        {"type": "p", "text": "DocumentData uses ProcessStageID semantics:"},
        {"type": "bullet", "text": "1 = Pre Classify"},
        {"type": "bullet", "text": "2 = Validated Post Classified (truth)"},
        {"type": "bullet", "text": "3 = Pre Extract"},
        {"type": "bullet", "text": "4 = Validated Post Extracted (truth)"},
        {"type": "p", "text": "Comparison model: baseline vs candidate vs truth per transaction and field."},
        {"type": "bullet", "text": "Regression: baseline correct and candidate wrong."},
        {"type": "bullet", "text": "Improvement: baseline wrong and candidate correct."},
        {"type": "bullet", "text": "Hidden risk: both wrong or confidence/empty-rate anomalies that may mask quality issues."},
        {"type": "blank"},
        {"type": "h1", "text": "I. Routing Logic (Decision Policy)"},
        {"type": "bullet", "text": "PASS: weighted_f1_delta does not cross warning threshold and no critical-type regression override."},
        {"type": "bullet", "text": "WARN: weighted_f1_delta below warn threshold but above block threshold."},
        {"type": "bullet", "text": "BLOCK: weighted_f1_delta below block threshold OR any regression in critical document types."},
        {"type": "bullet", "text": "Routing actions map to block_release, request_human_review, open_defect, notify_roles."},
        {"type": "blank"},
        {"type": "h1", "text": "J. ATC (Acceptance/Test Criteria)"},
        {"type": "bullet", "text": "ATC-1 Input Contract: Maestro payload validates against Pydantic schema without missing required fields."},
        {"type": "bullet", "text": "ATC-2 Workspace Bootstrap: run workspace and expected subfolders are created for each run_id."},
        {"type": "bullet", "text": "ATC-3 Flow Progression: all mandatory steps execute and update FlowState without null critical outputs."},
        {"type": "bullet", "text": "ATC-4 Evidence Challenge Loop: needs_more_evidence triggers rerun branch and respects max_targeted_reruns."},
        {"type": "bullet", "text": "ATC-5 Metrics Integrity: regression/improvement findings are traceable to case bundle evidence."},
        {"type": "bullet", "text": "ATC-6 Routing Correctness: PASS/WARN/BLOCK and routing booleans follow policy thresholds and critical-doc override."},
        {"type": "bullet", "text": "ATC-7 Artifact Completeness: final packet, report, trace, and log artifacts are written and addressable."},
        {"type": "bullet", "text": "ATC-8 Baseline Tests: tests/test_imports.py passes as smoke validation for schema/tool imports and payload parsing."},
        {"type": "blank"},
        {"type": "h1", "text": "K. Current Implementation Notes and Risks"},
        {
            "type": "p",
            "text": (
                "The architecture is solid, but the current code has several state-key alignment gaps between flow and agent functions. "
                "These should be treated as priority hardening tasks."
            ),
        },
        {
            "type": "bullet",
            "text": (
                "IntakeDiff input mapping mismatch: agent expects current_prompt_text/current_model keys, "
                "while flow currently passes current_artifact and previous_artifact dicts."
            ),
        },
        {
            "type": "bullet",
            "text": (
                "Challenger input mismatch: flow provides case_bundles_count, but agent reads total_transactions and doc_type_distribution."
            ),
        },
        {
            "type": "bullet",
            "text": (
                "TrendDrift input mismatch: agent expects top-level date_from/date_to and summary_metrics, "
                "while flow passes nested scope and no summary_metrics field."
            ),
        },
        {
            "type": "bullet",
            "text": (
                "ReportRouting depends on summary_metrics/doc_type_breakdown/date fields that are not consistently populated in flow state."
            ),
        },
        {
            "type": "bullet",
            "text": (
                "TargetedRerun scope mismatch: agent reads current_scope.transaction_ids, "
                "but flow sends selected_transaction_ids inside current_scope."
            ),
        },
        {"type": "blank"},
        {"type": "h1", "text": "L. Recommended Next Steps"},
        {"type": "bullet", "text": "Align flow-to-agent state contracts so each agent receives exactly the keys it expects."},
        {"type": "bullet", "text": "Persist and forward RegressionHunter summary_metrics/doc_type_breakdown into state for TrendDrift and ReportRouting."},
        {"type": "bullet", "text": "Add one deterministic integration test with mocked agent outputs to validate branch routing and packet shape."},
        {"type": "bullet", "text": "Add schema-based assertions for final_run_packet fields before returning from flow."},
        {"type": "bullet", "text": "Normalize documentation encoding in markdown files (replace malformed UTF characters) to keep docs presentation clean."},
        {"type": "blank"},
        {"type": "p", "text": "End of document."},
    ]
    return lines


def write_docx(output_path: Path) -> None:
    document_xml = build_document_xml(build_content())

    content_types_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        "</Types>"
    )

    rels_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="word/document.xml"/>'
        "</Relationships>"
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types_xml)
        zf.writestr("_rels/.rels", rels_xml)
        zf.writestr("word/document.xml", document_xml)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate architecture documentation as a .docx file.")
    parser.add_argument(
        "--output",
        default="docs/Document_AI_Agentic_Testing_Architecture.docx",
        help="Output .docx path",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_path = Path(args.output).resolve()
    write_docx(output_path)
    print(f"Wrote architecture document: {output_path}")


if __name__ == "__main__":
    main()
