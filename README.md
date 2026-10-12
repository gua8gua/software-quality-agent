# Software Quality Workbench

This package serves the quality-management frontend and proxies `/api/v1/*`
to `QUALITY_BACKEND_URL` (default `http://127.0.0.1:8000`). It also exposes a
separate `/api/agent/review-suggestions` endpoint implemented with the OpenAI
Agents SDK. That Agent is read-only against the canonical backend and persists
one SDK session plus a public checkpoint per review sentence; it does not create
a second TLR or rewrite source artifacts.

The runtime is an SDK manager plus scoped agents-as-tools. Tool-enabled
research is separated from the no-tool structured-output finalizer because the
deployed local Qwen endpoint does not reliably accept a function-call
transcript and JSON schema in one response. Official SDK output guardrails
still validate every structured stage and reject unsupported evidence.

Start the canonical backend first, then run:

```powershell
python -m software_quality_agent.cli serve --host 127.0.0.1 --port 8010
```

Build the frontend with `npm run build` in `frontend/` when a static UI is needed.
The backend owns canonical content, the only formal TLR, and information/review
tools. The proxy is retained because the quality workbench uses a same-origin
`/api/v1` route; the suggestion endpoint is the only local Agent runtime.
