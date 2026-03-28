# VeriNode

VeriNode is a local-first paper verification workbench.

It lets you:
- upload a PDF or Markdown paper
- extract claims
- verify references
- capture browser evidence with TinyFish
- run sandbox checks for code and math claims

## Quick Start

1. Install backend dependencies:

```bash
uv sync
```

2. Add a repo-root `.env`:

```env
OPENAI_API_KEY=...
OPENAI_MODEL_MAIN=gpt-5-mini
OPENAI_MODEL_SEARCH=gpt-5-mini
OPENAI_MODEL_SANDBOX=gpt-5.1
TINYFISH_API_KEY=...
TINYFISH_BASE_URL=https://agent.tinyfish.ai
ENABLE_TINYFISH=true
ENABLE_CODE_SANDBOX=true
```

3. Start the backend from the repo root:

```bash
uv run uvicorn verinode.main:create_app --factory --reload --host 127.0.0.1 --port 8000
```

4. Start the frontend:

```bash
cd frontend
npm install
npm run dev
```

5. Open [http://localhost:5173](http://localhost:5173)

## Demo Flow

1. Upload one file from `resources/sample/`
2. Click `Extract Claims`
3. Open a claim
4. Click `Verify + Capture Evidence` or `Run Sandbox Simulation`

## Notes

- If you interrupt the backend mid-job, restart it before rerunning.
- TinyFish evidence is only treated as complete when a screenshot artifact is returned.
