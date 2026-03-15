# CrewAI AMP Deployment Runbook

This project is now hardened for AMP-style cloud deployment.

## 1) Compatibility Checklist

- `pyproject.toml` has `[tool.crewai] type = "flow"`
- Flow cloud entrypoint exists: `src/agentic_testing/main.py` with `kickoff(inputs=...)`
- `uv.lock` is present
- LLM config is provider-driven via environment variables (no localhost lock-in)

## 2) Log In and Deploy

```powershell
uv run crewai login
uv run crewai deploy create -y
uv run crewai deploy push
uv run crewai deploy status
```

After deployment completes, AMP will show:

- **Agent URL** (example: `https://<your-agent>.crewai.com`)
- **Bearer Token** (from your CrewAI Enterprise/AMP account for API calls)

## 3) Lowest-Cost Cloud Model Setup

Set these environment variables in AMP deployment settings:

```text
AGENTIC_LLM_PROVIDER=groq
AGENTIC_REASONING_MODEL=groq/llama-3.1-8b-instant
AGENTIC_STRUCTURED_MODEL=groq/llama-3.1-8b-instant
AGENTIC_CODE_MODEL=groq/llama-3.1-8b-instant
AGENTIC_LLM_TEMPERATURE=0.1
GROQ_API_KEY=<your-groq-key>
```

If you prefer OpenAI:

```text
AGENTIC_LLM_PROVIDER=openai
AGENTIC_REASONING_MODEL=openai/gpt-4o-mini
AGENTIC_STRUCTURED_MODEL=openai/gpt-4o-mini
AGENTIC_CODE_MODEL=openai/gpt-4o-mini
OPENAI_API_KEY=<your-openai-key>
```

## 4) Inputs/Outputs for UiPath

Use AMP REST pattern:

1. `GET /inputs` to fetch required schema
2. `POST /kickoff` with JSON payload
3. `GET /{kickoff_id}/status` until completed

Header:

```http
Authorization: Bearer <AMP_BEARER_TOKEN>
Content-Type: application/json
```

Your payload should follow `MaestroInput` shape from:
- `src/agentic_testing/schemas/maestro_input.py`

## 5) Notes on Free Models

- CrewAI itself does not provide free model inference.
- Cost depends on the model provider account you connect.
- For lowest cost, start with small open-weight cloud models (for example Groq 8B class models), then scale up only if quality requires it.
