# VeriNode

## Project Overview

**VeriNode** is a local-first research verification workbench for PDF and Markdown documents.

The system ingests a document, extracts atomic claim cards, maps each claim to in-document evidence and cited references, verifies whether the cited references exist and support the claim, and optionally performs an external corroboration or contradiction check. Code and math artifacts may be extracted as separate cards and can optionally be sent to a sandboxed execution stage.

The initial implementation is intentionally conservative:

- run locally only
- use mainstream, low-complexity tooling
- use **OpenAI** as the primary extraction, structuring, judgment, and optional sandbox provider
- use **TinyFish** only for web evidence acquisition when a reference requires real browser interaction or screenshots
- send PDF and Markdown directly to the OpenAI API
- avoid custom parsing pipelines, vector databases, distributed queues, and deployment-specific infrastructure
- prefer explicit state transitions over autonomous multi-agent behavior

Configuration is managed through `.env` only.

---

## High-Level Architecture

The system is a simple local application with a thin service split:

1. **Frontend**: React app for document upload, claim card browsing, and stage-by-stage execution.
2. **Backend**: FastAPI service that owns state, persistence, OpenAI orchestration, TinyFish orchestration, and background job execution.

### Logical Components

- **UI Layer**
  - document upload
  - claim card list
  - per-card stage controls
  - evidence, reference, screenshot, and sandbox result views

- **API Layer**
  - REST endpoints for documents, cards, jobs, and stage execution
  - server-side validation
  - response serialization

- **Application Layer**
  - document ingestion service
  - claim extraction service
  - reference resolution service
  - reference verification service
  - web evidence acquisition service
  - optional external search service
  - optional sandbox service for code/math cards
  - state machine coordinator

- **Persistence Layer**
  - SQLite database for all project state
  - local filesystem storage for uploaded files and generated artifacts

- **External Dependency Layer**
  - OpenAI API
  - TinyFish API

### Verification Strategy

Verification should remain layered and cost-aware:

1. **OpenAI-first**
   - extract claims, evidence spans, and references
   - perform structured support judgment
   - perform optional external search
2. **TinyFish escalation**
   - only when a reference requires live webpage interaction, navigation, or screenshots
   - not the default path for every reference

### Design Principles

- keep the backend authoritative; the UI only renders server state
- persist every stage result so later stages never recompute prior work unless explicitly retried
- keep each stage independently runnable per card
- use structured outputs wherever typed data is required
- keep concurrency low and explicit
- use TinyFish only where browser-native evidence adds value
- do not introduce infrastructure that is unnecessary for local development

---

## Technology Stack

### Backend

- **Python 3.12**
- **uv** for dependency management and task execution
- **FastAPI** for HTTP API
- **Pydantic v2** for request/response schemas and internal typed models
- **SQLAlchemy 2.x** for ORM and persistence
- **Alembic** for local schema migrations
- **SQLite** for local database storage
- **OpenAI Python SDK** for document analysis, structured outputs, optional external search, and optional code interpreter
- **httpx** for TinyFish API integration and general outbound HTTP

### Frontend

- **TypeScript**
- **React**
- **Vite**
- **Tailwind CSS**
- **shadcn/ui** for clean, OpenAI-like primitives
- **TanStack Query** for server-state fetching and mutation

### Local Storage

- `data/uploads/` for source documents
- `data/artifacts/` for generated outputs, screenshots, and sandbox artifacts
- SQLite file in `data/app.db`

### Environment Configuration

All runtime configuration is set through `.env`.

Minimum required variables:

```env
OPENAI_API_KEY=
OPENAI_MODEL_MAIN=
OPENAI_MODEL_SEARCH=
OPENAI_MODEL_SANDBOX=
TINYFISH_API_KEY=
TINYFISH_BASE_URL=
APP_ENV=local
APP_DATA_DIR=./data
DATABASE_URL=sqlite:///./data/app.db
MAX_CONCURRENT_JOBS=2
ENABLE_EXTERNAL_SEARCH=true
ENABLE_CODE_SANDBOX=false
ENABLE_TINYFISH=true
LOG_LEVEL=INFO
```

Notes:

- `OPENAI_MODEL_MAIN` is the default model for claim extraction and reference verification.
- `OPENAI_MODEL_SEARCH` is used for the optional external search stage.
- `OPENAI_MODEL_SANDBOX` is used only when code/math execution is enabled.
- `ENABLE_CODE_SANDBOX` should remain `false` unless the code/math lane is intentionally enabled.
- `ENABLE_TINYFISH` allows the browser-evidence lane to be fully disabled without code changes.
- `TINYFISH_BASE_URL` should point to the TinyFish API root used by the backend.

---

## Core Workflow & State Machine

The product is stage-driven, not chat-driven.

A document is uploaded once, then analyzed incrementally. Each claim card advances only when the user triggers the next stage.

### Document Workflow

1. **Upload**
   - store original file locally
   - create document record
2. **Normalize**
   - determine file type
   - prepare OpenAI input payload
3. **Extract Claims**
   - call OpenAI with the document
   - return structured claim cards, evidence spans, cited references, and optional code/math cards
4. **Review**
   - user reviews extracted cards
5. **Run Per-Card Stages**
   - reference verification
   - TinyFish evidence acquisition when required
   - optional external corroboration / contradiction search
   - optional sandbox execution for code/math cards

### Card Stages

Each card has its own stage state:

- `draft`
- `extracted`
- `verified`
- `web_evidence_acquired`
- `externally_checked`
- `sandboxed`
- `completed`
- `failed`

Not every card reaches every stage.

### Job States

Long-running work is tracked as jobs:

- `queued`
- `running`
- `succeeded`
- `failed`
- `cancelled`

### Execution Model

- jobs run in-process inside the backend
- concurrency is limited with an application-level semaphore
- stage results are persisted after every successful transition
- retries are explicit and user-triggered
- no Redis, Celery, Kafka, or distributed workers in v1

### Stage Responsibilities

#### Claim Extraction

- provider: OpenAI
- input: PDF or Markdown
- output: structured claim cards with evidence spans and reference mappings

#### Reference Verification

- provider: OpenAI
- input: claim card + mapped references + available source material
- output: structured verdicts:
  - `supported`
  - `partially_supported`
  - `not_supported`
  - `cannot_verify`

#### Web Evidence Acquisition

- provider: TinyFish
- trigger: only when direct verification is insufficient and live web interaction is needed
- input: reference metadata + verification goal
- output: extracted web evidence, source URL, and screenshots

#### External Search

- provider: OpenAI
- input: claim card
- output: additional corroborating or contradicting evidence summaries

#### Sandbox Execution

- provider: OpenAI
- input: code/math card
- output: execution logs, artifacts, and a narrow execution verdict

---

## Data Architecture & Models

The database is relational and intentionally small.

### Core Tables

#### `documents`
Stores one uploaded source document.

Key fields:
- `id`
- `filename`
- `file_type`
- `storage_path`
- `status`
- `title`
- `created_at`
- `updated_at`

#### `claim_cards`
Stores one atomic card per row.

Key fields:
- `id`
- `document_id`
- `card_type` (`claim`, `code`, `math`)
- `claim_text`
- `stage`
- `page_label`
- `section_label`
- `summary`
- `created_at`
- `updated_at`

#### `evidence_spans`
Stores evidence tied to a card.

Key fields:
- `id`
- `claim_card_id`
- `source_kind` (`document`, `reference`, `tinyfish`, `external_search`, `sandbox`)
- `text`
- `page_label`
- `start_anchor`
- `end_anchor`

#### `references`
Stores references extracted from the document.

Key fields:
- `id`
- `document_id`
- `ref_label`
- `raw_citation`
- `resolved_title`
- `resolved_url`
- `resolved_doi`

#### `claim_references`
Join table between claim cards and references.

Key fields:
- `claim_card_id`
- `reference_id`
- `relation_type`

#### `verification_results`
Stores verification outputs for a specific claim/reference pair.

Key fields:
- `id`
- `claim_card_id`
- `reference_id`
- `exists_verdict`
- `support_verdict`
- `reasoning_summary`
- `source_url`
- `created_at`

#### `tinyfish_runs`
Stores TinyFish evidence-acquisition attempts.

Key fields:
- `id`
- `claim_card_id`
- `reference_id`
- `status`
- `goal`
- `run_id`
- `source_url`
- `result_summary`
- `artifact_path`
- `created_at`

#### `external_search_results`
Stores optional final-stage search results.

Key fields:
- `id`
- `claim_card_id`
- `stance` (`supports`, `contradicts`, `neutral`)
- `title`
- `url`
- `summary`
- `created_at`

#### `sandbox_runs`
Stores execution attempts for code/math cards.

Key fields:
- `id`
- `claim_card_id`
- `status`
- `input_payload`
- `result_summary`
- `artifact_path`
- `created_at`

#### `jobs`
Stores background task lifecycle.

Key fields:
- `id`
- `job_type`
- `document_id`
- `claim_card_id`
- `status`
- `error_message`
- `created_at`
- `updated_at`

### Modeling Rules

- one card = one atomic unit of review and execution
- code and math are first-class card types, not attachments
- model outputs must be converted into typed internal models before persistence
- raw provider text must not be treated as canonical application state
- TinyFish artifacts are evidence, not source-of-truth state by themselves

---

## API Design

The API is small, synchronous at the edge, and job-based for long-running operations.

### Documents

- `POST /api/documents`
  - upload a PDF or Markdown file
  - create a document record

- `GET /api/documents/{document_id}`
  - return document metadata and overall status

- `GET /api/documents/{document_id}/cards`
  - list all cards for a document

- `POST /api/documents/{document_id}/extract`
  - enqueue claim extraction

### Cards

- `GET /api/cards/{card_id}`
  - return a full card with evidence, references, and stage data

- `POST /api/cards/{card_id}/verify`
  - enqueue reference verification for one card

- `POST /api/cards/{card_id}/web-evidence`
  - enqueue TinyFish evidence acquisition for one card

- `POST /api/cards/{card_id}/search`
  - enqueue external search for one card

- `POST /api/cards/{card_id}/sandbox`
  - enqueue sandbox execution for one code/math card

### Jobs

- `GET /api/jobs/{job_id}`
  - return job status and error message if failed

- `POST /api/jobs/{job_id}/retry`
  - retry a failed job

### Conventions

- all write endpoints return a job object for asynchronous work
- all read endpoints return fully typed JSON
- errors are explicit and machine-readable
- no websocket dependency is required in v1; polling is acceptable

---

## Non-Functional Requirements

### Simplicity

- prefer the smallest viable number of libraries
- avoid custom infrastructure unless a clear implementation bottleneck appears
- avoid premature abstraction

### Reliability

- every stage transition must be persisted
- every job failure must be visible and retryable
- invalid provider output must be rejected before persistence
- uploaded source files must remain accessible locally for re-run and audit
- TinyFish failures must degrade cleanly without corrupting card state

### Maintainability

- keep strict separation between API schemas, domain models, persistence models, OpenAI client logic, and TinyFish client logic
- isolate prompts and response schemas in dedicated modules
- keep services small and single-purpose
- keep feature flags in `.env`, not hard-coded branches

### Determinism

- the UI must render only persisted server state
- stage execution must be user-triggered, not autonomous
- re-running a stage must not mutate prior stage data except through explicit versioned replacement or overwrite rules
- TinyFish should be invoked only through explicit backend stage transitions

### Performance

- support local use on a laptop-class machine
- limit background concurrency
- do not load entire historical project state into memory
- prefer incremental fetches in the UI

### Security

- local-only development mode
- no multi-user auth in v1
- secrets must only come from `.env`
- never expose API keys to the frontend

### Scope Boundaries

Out of scope for v1:

- production deployment
- distributed workers
- multi-user accounts and permissions
- vector databases and custom retrieval systems
- autonomous background monitoring
- collaborative editing
- deployment-specific infrastructure

---

## Final Implementation Guidance

When implementation decisions are ambiguous, prefer:

1. fewer moving parts
2. typed schemas
3. persisted state
4. explicit stage boundaries
5. boring, mainstream libraries

VeriNode should feel like a clean local application with a thin AI orchestration layer, not an experimental agent framework.
