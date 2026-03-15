# Demo Test Cases (Excel Evidence Store)

Use these with your deployed Crew endpoint.

- `AGENT_URL`: your deployed kickoff URL, for example:
  `https://document-ai-agentic-testing-<id>.crewai.com/kickoff`
- `AGENT_TOKEN`: bearer token from Crew deployment.

## 1) Clean PASS Demo (No regressions)

Payload file:
- `data/test_maestro_payload_pass_clean_kickoff.json`

PowerShell:
```powershell
$AGENT_URL = "https://<your-agent>.crewai.com/kickoff"
$AGENT_TOKEN = "<your-bearer-token>"

curl -X POST $AGENT_URL `
  -H "Authorization: Bearer $AGENT_TOKEN" `
  -H "Content-Type: application/json" `
  -H "Accept: application/json" `
  --data-binary "@data/test_maestro_payload_pass_clean_kickoff.json"
```

Expected:
- `verdict = PASS`
- non-empty `summary_metrics`
- `regressions = []`
- PDF/HTML/Excel artifacts populated.

## 2) Extraction + Classification Demo (Richer flow)

Payload file:
- `data/test_maestro_payload_extraction_kickoff.json`

PowerShell:
```powershell
$AGENT_URL = "https://<your-agent>.crewai.com/kickoff"
$AGENT_TOKEN = "<your-bearer-token>"

curl -X POST $AGENT_URL `
  -H "Authorization: Bearer $AGENT_TOKEN" `
  -H "Content-Type: application/json" `
  -H "Accept: application/json" `
  --data-binary "@data/test_maestro_payload_extraction_kickoff.json"
```

Expected:
- includes both classification and extraction stats:
  - `classification_accuracy_*`
  - `exact_match_rate_*`
  - `empty_rate_*`
- richer timeline and routing narrative in HTML/PDF.

## 3) Notes

- These payloads are already in **single envelope** format:
  - `{"inputs":{"maestro_payload":{...}}}`
- Evidence store used:
  - `data/DocumentAI_EvidenceStore_Demo.xlsx`
  - Candidate sheet: `DocumentData_Candidate`
