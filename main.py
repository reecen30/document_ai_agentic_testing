"""
main.py - CLI entry point for the Document AI Agentic Testing system.

Usage examples:
    # Run with a JSON payload file
    python main.py --payload path/to/maestro_payload.json

    # Run with a sample payload (for testing)
    python main.py --sample

    # Run with basic webhook mode (POST /run)
    python main.py --serve --port 8080

    # Run deploy-ready API mode with OpenAPI docs and bearer auth
    # Requires env var AGENTIC_API_TOKEN
    python main.py --serve-api --port 8080
"""
import argparse
import json
import os
import sys

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from agentic_testing.flow import run_flow_from_maestro_payload


SAMPLE_PAYLOAD = {
    "run_request": {
        "run_id": "RUN-2026-03-14-001",
        "process_name": "document_ai_agentic_testing",
        "run_mode": "release_candidate",
        "analysis_mode": "agentic_investigation",
        "time_budget_minutes": 20,
        "max_initial_transactions": 20,
        "max_total_transactions": 100,
        "max_targeted_reruns": 3,
        "triggered_by": "CLI_SAMPLE",
    },
    "scope": {
        "date_from": "2026-02-01",
        "date_to": "2026-03-14",
        "transaction_ids": [],
        "document_type_names": [],
        "process_stage_ids": [1, 2, 3, 4],
        "allow_agent_to_expand_scope": True,
    },
    "current_execution_artifact": {
        "prompt_name": "classification_extraction_bundle",
        "prompt_version_label": "bundle_v17",
        "prompt_text": (
            "You are a document classification and extraction AI. "
            "Classify the document type from: ApplicationForm, Resolution, Windeed, Passport, "
            "IdentityDocument, ProductFormsBTB, ProductFormsIFB, ProductFormsICIB, "
            "Income_Statement, Balance_Sheet, CashFlow, Debtors, Creditors, AFS, Other, RelatedPartyForm. "
            "Then extract all relevant fields. "
            "For IdentityDocument and Passport: extract IdentityNumber or PassportNumber. "
            "For ApplicationForm: extract EntityName, ApplicationDate. "
            "If the document is out of scope or unreadable, classify as Other."
        ),
        "model_name": "deepseek-r1:8b",
        "artifact_hash": "sha256-current-bundle-v17",
    },
    "previous_execution_artifact": {
        "prompt_name": "classification_extraction_bundle",
        "prompt_version_label": "bundle_v16",
        "prompt_text": (
            "You are a document classification and extraction AI. "
            "Classify the document type from: ApplicationForm, Resolution, Windeed, Passport, "
            "IdentityDocument, ProductFormsBTB, ProductFormsIFB, ProductFormsICIB, "
            "Income_Statement, Balance_Sheet, CashFlow, Debtors, Creditors, AFS, Other. "
            "Then extract all relevant fields. "
            "For IdentityDocument: extract IdentityNumber. "
            "For ApplicationForm: extract EntityName, ApplicationDate."
        ),
        "model_name": "deepseek-r1:8b",
        "artifact_hash": "sha256-previous-bundle-v16",
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
            "api_data": "api.APIData",
        },
    },
    "storage": {
        "artifact_namespace": "agentic-testing",
        "run_workspace_key": "RUN-2026-03-14-001",
        "output_mode": "managed_workspace",
        "workspace_base_path": None,
    },
    "policy": {
        "critical_doc_types": ["IdentityDocument", "Passport", "ApplicationForm"],
        "warn_weighted_f1_drop": 0.02,
        "block_weighted_f1_drop": 0.05,
        "block_empty_rate_increase": 0.03,
        "block_exception_rate_increase": 0.02,
    },
    "requested_outputs": {
        "pdf_report": True,
        "html_report": True,
        "excel_log": True,
        "json_packet": True,
        "trace_pack": True,
        "patch_candidates": True,
        "audit_log_excel": True,
    },
}


def run_from_payload_file(payload_path: str) -> None:
    with open(payload_path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    result = run_flow_from_maestro_payload(payload)
    print(json.dumps(result, indent=2, default=str))


def run_from_json_string(json_string: str) -> None:
    """Accept raw JSON string (e.g. from CrewAI cloud input or piped stdin)."""
    result = run_flow_from_maestro_payload(json_string)
    print(json.dumps(result, indent=2, default=str))


def run_sample() -> None:
    from dotenv import load_dotenv

    load_dotenv()
    if not os.getenv("AGENTIC_LLM_PROVIDER"):
        # Keep sample path simple for local development.
        os.environ["AGENTIC_LLM_PROVIDER"] = "ollama"
    if not os.getenv("WORKSPACE_BASE_PATH"):
        os.environ["WORKSPACE_BASE_PATH"] = os.path.join(os.path.dirname(__file__), "workspaces")
    if not os.getenv("EVIDENCE_STORE_PATH"):
        os.environ["EVIDENCE_STORE_PATH"] = os.path.join(
            os.path.dirname(__file__), "data", "DocumentAI_EvidenceStore.xlsx"
        )
    result = run_flow_from_maestro_payload(SAMPLE_PAYLOAD)
    print(json.dumps(result, indent=2, default=str))


def serve(port: int = 8080) -> None:
    """Simple HTTP server that accepts POST /run with a Maestro JSON payload."""
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            if self.path != "/run":
                self.send_response(404)
                self.end_headers()
                return

            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            try:
                payload = json.loads(body)
                result = run_flow_from_maestro_payload(payload)
                response = json.dumps(result, default=str).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(response)
            except Exception as exc:
                err = json.dumps({"error": str(exc)}).encode("utf-8")
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(err)

        def log_message(self, format, *args):
            print(f"[HTTP] {args}")

    print(f"[Server] Listening on 0.0.0.0:{port}")
    HTTPServer(("0.0.0.0", port), Handler).serve_forever()


def serve_api(port: int = 8080) -> None:
    """Run FastAPI server with explicit contracts and bearer token auth."""
    from uvicorn import run as uvicorn_run

    print(f"[API] Listening on 0.0.0.0:{port}")
    print("[API] Swagger UI: http://localhost:{port}/docs".format(port=port))
    print("[API] OpenAPI schema: http://localhost:{port}/openapi.json".format(port=port))
    uvicorn_run("agentic_testing.api:app", host="0.0.0.0", port=port, reload=False)


def main() -> None:
    parser = argparse.ArgumentParser(description="Document AI Agentic Testing System")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--payload", metavar="PATH", help="Path to Maestro JSON payload file")
    group.add_argument("--json-string", metavar="JSON", help="Raw JSON string payload (for CrewAI cloud or piped input)")
    group.add_argument("--sample", action="store_true", help="Run with built-in sample payload")
    group.add_argument("--serve", action="store_true", help="Start basic HTTP webhook server")
    group.add_argument("--serve-api", action="store_true", help="Start deploy-ready FastAPI server")
    parser.add_argument("--port", type=int, default=8080, help="Port for server modes (default: 8080)")
    args = parser.parse_args()

    if args.payload:
        run_from_payload_file(args.payload)
    elif getattr(args, "json_string", None):
        run_from_json_string(args.json_string)
    elif args.sample:
        run_sample()
    elif getattr(args, "serve_api", False):
        serve_api(args.port)
    elif args.serve:
        serve(args.port)


if __name__ == "__main__":
    main()
