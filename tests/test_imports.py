"""
tests/test_imports.py

Fast local smoke tests — no LLM calls, no Excel files needed.
Run with:  python -m pytest tests/test_imports.py -v
       or:  python tests/test_imports.py
"""
import json
import os
import sys

# Make sure the src package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


# ── 1. Schema import tests ────────────────────────────────────────────────────

def test_maestro_input_imports():
    from agentic_testing.schemas.maestro_input import (
        MaestroInput, RunRequest, ScopeConfig, ExecutionArtifact,
        EvidenceStoreConfig, StorageConfig, PolicyConfig, RequestedOutputs,
    )
    print("  [OK] maestro_input schemas")


def test_flow_state_imports():
    from agentic_testing.schemas.crew_output import FlowState
    print("  [OK] crew_output FlowState")


def test_agent_output_imports():
    from agentic_testing.schemas.agent_outputs import (
        ChangeSummaryOutput, ScopePlannerOutput, EvidenceSummaryOutput,
        RegressionHunterOutput, ChallengerOutput, TargetedRerunOutput,
        TrendDriftOutput, RootCauseOutput, PatchProposalOutput, FinalRoutingOutput,
    )
    print("  [OK] agent_outputs schemas")


# ── 2. Tool import tests ───────────────────────────────────────────────────────

def test_diff_tools_import():
    from agentic_testing.tools.diff_tools import diff_prompt_artifacts, compare_model_change
    print("  [OK] diff_tools")


def test_evidence_tools_import():
    from agentic_testing.tools.evidence_tools import build_case_bundle, summarize_evidence
    print("  [OK] evidence_tools")


def test_excel_reader_import():
    from agentic_testing.tools.excel_reader import (
        read_document_data, read_model_data, read_exception_logs,
        read_api_data, read_lookup_sheet,
    )
    print("  [OK] excel_reader")


def test_excel_writer_import():
    from agentic_testing.tools.excel_writer import write_sheet, append_rows
    print("  [OK] excel_writer")


def test_metrics_tools_import():
    from agentic_testing.tools.metrics_tools import (
        compare_baseline_to_truth, compare_candidate_to_truth,
        calculate_doc_type_metrics, calculate_field_metrics,
        detect_missing_field_spikes, detect_confidence_mismatch,
    )
    print("  [OK] metrics_tools")


def test_reporting_tools_import():
    from agentic_testing.tools.reporting_tools import (
        write_html_report, write_trace_pack, write_final_packet, write_audit_log_event,
    )
    print("  [OK] reporting_tools")


def test_rerun_tools_import():
    from agentic_testing.tools.rerun_tools import (
        expand_scope_by_pattern, request_targeted_rerun, write_patch_candidate,
    )
    print("  [OK] rerun_tools")


def test_logging_tools_import():
    from agentic_testing.tools.logging_tools import (
        log_agent_event, write_model_data_trace,
    )
    print("  [OK] logging_tools")


def test_deploy_contract_import():
    from agentic_testing.schemas.deploy_contract import UiPathRunOutput, normalize_uipath_output
    out = normalize_uipath_output({"run_id": "TEST-001", "verdict": "PASS"})
    assert isinstance(out, UiPathRunOutput)
    assert out.run_id == "TEST-001"
    print("  [OK] deploy_contract")


def test_api_import():
    from agentic_testing.api import app
    assert app is not None
    print("  [OK] api")


# ── 3. Payload validation tests ───────────────────────────────────────────────

MINIMAL_PAYLOAD = {
    "run_request": {
        "run_id": "TEST-001",
        "process_name": "document_ai_agentic_testing",
    },
    "scope": {
        "date_from": "2026-01-01",
        "date_to": "2026-03-15",
    },
    "current_execution_artifact": {
        "prompt_name": "test_prompt",
        "prompt_version_label": "v1",
        "prompt_text": "Classify the document.",
        "model_name": "deepseek-r1:8b",
        "artifact_hash": "sha256-test-current",
    },
    "previous_execution_artifact": {
        "prompt_name": "test_prompt",
        "prompt_version_label": "v0",
        "prompt_text": "Classify the doc.",
        "model_name": "deepseek-r1:8b",
        "artifact_hash": "sha256-test-previous",
    },
    "evidence_store": {
        "store_type": "excel",
        "store_ref": "DocumentAI_EvidenceStore",
    },
    "storage": {
        "artifact_namespace": "agentic-testing",
        "run_workspace_key": "TEST-001",
    },
    "policy": {},
    "requested_outputs": {},
}


def test_payload_dict_validation():
    from agentic_testing.schemas.maestro_input import MaestroInput
    m = MaestroInput(**MINIMAL_PAYLOAD)
    assert m.run_request.run_id == "TEST-001"
    print("  [OK] payload dict validation")


def test_payload_json_string_parsing():
    """Simulates what CrewAI cloud does — passes input as a JSON string."""
    from agentic_testing.flow import run_flow_from_maestro_payload
    # We only test parsing, not execution — patch the flow to stop early
    import json
    payload_str = json.dumps(MINIMAL_PAYLOAD)
    # Just verify json.loads round-trip (not running the full flow here)
    parsed = json.loads(payload_str)
    from agentic_testing.schemas.maestro_input import MaestroInput
    m = MaestroInput(**parsed)
    assert m.run_request.run_id == "TEST-001"
    print("  [OK] JSON string input parsing")


def test_flow_state_initialisation():
    from agentic_testing.schemas.maestro_input import MaestroInput
    from agentic_testing.schemas.crew_output import FlowState
    m = MaestroInput(**MINIMAL_PAYLOAD)
    state = FlowState(**m.to_flow_state_dict())
    assert state.run_id == "TEST-001"
    assert state.rerun_count == 0
    assert state.needs_more_evidence is False
    print("  [OK] FlowState initialisation")


def test_diff_tool_functional():
    """Run the diff tool directly — no LLM needed."""
    from agentic_testing.tools.diff_tools import diff_prompt_artifacts
    result_str = diff_prompt_artifacts._run(
        current_prompt_text="Classify the document type.",
        previous_prompt_text="Classify the doc.",
    )
    result = json.loads(result_str)
    assert "unified_diff" in result
    assert result["addition_count"] >= 0
    assert result["prompts_identical"] is False
    print("  [OK] diff_tool functional test")


def test_compare_model_tool_functional():
    from agentic_testing.tools.diff_tools import compare_model_change
    result_str = compare_model_change._run(
        current_model="deepseek-r1:8b",
        previous_model="qwen2.5:7b-instruct",
    )
    result = json.loads(result_str)
    assert result["model_changed"] is True
    print("  [OK] compare_model_tool functional test")


# ── Runner ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    tests = [
        test_maestro_input_imports,
        test_flow_state_imports,
        test_agent_output_imports,
        test_diff_tools_import,
        test_evidence_tools_import,
        test_excel_reader_import,
        test_excel_writer_import,
        test_metrics_tools_import,
        test_reporting_tools_import,
        test_rerun_tools_import,
        test_logging_tools_import,
        test_deploy_contract_import,
        test_api_import,
        test_payload_dict_validation,
        test_payload_json_string_parsing,
        test_flow_state_initialisation,
        test_diff_tool_functional,
        test_compare_model_tool_functional,
    ]

    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except Exception as e:
            print(f"  [FAIL] {t.__name__}: {e}")
            failed += 1

    print(f"\n{'='*50}")
    print(f"Results: {passed} passed, {failed} failed out of {len(tests)} tests")
    if failed:
        sys.exit(1)
