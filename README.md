# Statement Categorizer

An agentic pipeline that turns a raw bank statement CSV into a categorized one —
built for the Kaggle "5-Day AI Agents Intensive" Vibecoding Capstone.

## Problem

Personal and small-business budgeting starts with one tedious task: figuring out
what every line on a bank statement actually *is*. Exports from banks give you a
merchant string like `PONY EXPRESS-O BELLE FOURCHE SD` or `AMZN Mktp US*MK87L19A2`
— cryptic, inconsistently formatted, and not mapped to any budget category.
Doing this by hand for hundreds of transactions a month doesn't scale, and naive
"send every row to an LLM" approaches leak financial account/card identifiers to
a third-party API and re-pay for the same recurring merchants every run.

## Solution

Statement Categorizer ingests a statement CSV and returns the same CSV with a
`Category` column filled in, using a two-tier agent pipeline instead of a single
LLM call per row:

1. A **local, deterministic cache** answers repeat merchants (e.g. the same
   `NETFLIX.COM DIG RECURRING` line every month) instantly, with no LLM call at all.
2. A **local regex PII gateway** strips card numbers and long account identifiers
   from the description *before* anything leaves the machine.
3. A **primary classification agent** (Node 1) maps the sanitized description to
   one of 17 fixed budget categories with a confidence score.
4. If confidence is low, a **search agent** (Node 2a) uses the native
   `google_search` grounding tool to look up the merchant, and the primary
   classifier is re-invoked with that context to re-attempt classification
   (Node 2b) — rather than guessing or hard-failing.
5. Anything still unresolved — or any transaction that errors out (rate limits,
   network faults) — is labeled `Unknown` rather than crashing the batch.

All of this runs concurrently (bounded to a handful of in-flight requests at a
time) across every row in the statement, and the verified results are written
back into the cache so the next run for the same accounts is instant and free.

## Architecture

Two ADK agents — a structured classifier and a search-only agent — orchestrated
by an async batch pipeline. Node 1's classifier is reused for both the initial
attempt and the post-search re-attempt:

```text
                 [app/main.py: Async Batch Orchestrator]
                                  │
                Load app/data/cache.json into memory
                                  │
             Load newest CSV in app/data/input/ (pandas)
                                  │
         Bounded asyncio.Semaphore (max 4 concurrent rows)
                                  │
        ┌─────────────────────────────────────────────────┐
        │                 per transaction row              │
        │                                                   │
        │   Cache hit? ── yes ──▶ reuse cached category      │
        │      │no                                          │
        │      ▼                                             │
        │   mask_pii_local()  (regex: card / account numbers)│
        │      │                                             │
        │      ▼                                             │
        │   Node 1 - transaction_categorizer agent           │
        │   (google.adk LlmAgent, structured output_schema)  │
        │      │                                             │
        │      ├─ confidence ≥ 0.85 ──▶ commit to cache      │
        │      │                                             │
        │      └─ confidence < 0.85                          │
        │             │                                       │
        │             ▼                                       │
        │      Node 2a - fallback_search agent                │
        │      (google_search tool, plain-text output only)  │
        │             │                                       │
        │             ▼                                       │
        │      Node 2b - Node 1 agent re-invoked with          │
        │      description + search context appended          │
        │             │                                       │
        │             ├─ confidence ≥ 0.85 ──▶ commit to cache│
        │             └─ else / exception ──▶ "Unknown"        │
        └─────────────────────────────────────────────────┘
                                  │
                asyncio.gather() awaits all rows
                                  │
              Single atomic flush → app/data/cache.json
                                  │
      Write app/data/output/categorized_<original_filename>.csv
```

Node 2 is two separate model calls rather than one because Gemini rejects
combining a built-in tool (`google_search`) with the function-calling
mechanism ADK uses to enforce `output_schema` in the same request. See
[`DESIGN_SPEC.md`](./DESIGN_SPEC.md#5-architectural-data-flow) for the full
explanation.

### Master taxonomy

Every transaction resolves to exactly one of 17 categories (enforced at the
schema level, not just by prompt instruction):

`Income`, `Utilities`, `Entertainment`, `Food & Dining`, `Shopping`,
`Gas & Fuel`, `Insurance`, `Housing`, `Medical & Health`, `Auto Loan`,
`Groceries`, `Travel & Recreation`, `Subscriptions & Software`,
`Home Improvement`, `Manual Review Required`, `Cash Withdrawal`, `Unknown`.

See [`DESIGN_SPEC.md`](./DESIGN_SPEC.md) for the full technical design
(data schemas, confidence thresholds, and the detailed execution-stage
breakdown behind the diagram above).

### Key concepts demonstrated

- **Agent / Multi-agent system (ADK)**: an asynchronous orchestrator-worker
  pattern (`app/main.py`) driving two `google.adk` `LlmAgent`s (`app/agent.py`).
- **Agent Skills**: domain instructions live in `app/skills/*/SKILL.md`
  manifests rather than inline prompts, loaded at runtime (progressive
  disclosure, discoverable by `agents-cli`).
- **Security features**: a deterministic, regex-only PII masking gateway
  (`app/skills/transaction_categorizer/tools.py`) runs locally before any
  description reaches the LLM; no API keys are hardcoded (all credentials via
  `.env`, which is gitignored).
- **Deployability**: dependencies are pinned via `uv`/`pyproject.toml`, with a
  clean `agents-cli`-discoverable entrypoint (`root_agent` in `app/agent.py`)
  alongside the standalone batch entrypoint (`app/main.py`).

## Project Structure

```
statement-categorizer/
├── app/
│   ├── agent.py                       # Node 1 / Node 2 ADK agent definitions
│   ├── main.py                        # Async batch orchestrator (entrypoint)
│   ├── fast_api_app.py                # Optional FastAPI/A2A serving surface
│   ├── app_utils/                     # Serving-surface plumbing (sessions, telemetry, A2A)
│   ├── skills/
│   │   ├── transaction_categorizer/
│   │   │   ├── SKILL.md               # Node 1 instructions + taxonomy
│   │   │   └── tools.py               # mask_pii_local() - local PII gateway
│   │   └── fallback_search/
│   │       └── SKILL.md               # Node 2 search-fallback instructions
│   └── data/
│       ├── input/                     # Drop raw statement CSVs here
│       ├── output/                    # categorized_<file>.csv is written here
│       └── cache.json                 # Persistent classification cache
├── tests/                             # Unit, integration, and eval tests
├── DESIGN_SPEC.md                     # Full technical design specification
├── pyproject.toml                     # uv-managed project dependencies
└── .env.example                       # Credential template (copy to .env)
```

## Setup Instructions

### Prerequisites

- Python 3.11–3.13
- [`uv`](https://docs.astral.sh/uv/getting-started/installation/) — dependency manager used for everything in this project
- (Optional) [`agents-cli`](https://google.github.io/agents-cli/) — `uv tool install google-agents-cli`, for the interactive playground/eval tooling
- A Gemini credential — either:
  - a [Google AI Studio API key](https://aistudio.google.com/apikey) (simplest), or
  - a Google Cloud project with Vertex AI enabled + [`gcloud auth application-default login`](https://cloud.google.com/sdk/docs/install)

### 1. Clone and install dependencies

```bash
git clone https://github.com/ArBleizBZH/capstone-agentic-statement-categorizer.git
cd capstone-agentic-statement-categorizer
uv sync
```

### 2. Configure credentials

Copy the template and fill in your own key — **never commit `.env`** (it's
already gitignored):

```bash
cp .env.example .env
```

Then edit `.env`:
- For Google AI Studio, uncomment/set `GEMINI_API_KEY=<your key>`.
- For Vertex AI, instead set `GOOGLE_GENAI_USE_VERTEXAI=true`,
  `GOOGLE_CLOUD_PROJECT=<your-project-id>`, `GOOGLE_CLOUD_LOCATION=global`.

### 3. Provide input data

Drop a bank statement CSV into `app/data/input/`. It must contain these columns:

`Transaction Date, Post Date, Description, Type, Amount, Memo`

A synthetic sample is already included at
`app/data/input/synthetic_sample_statement_raw.csv` so you can try the pipeline
immediately without your own data.

### 4. Run the batch categorizer

```bash
uv run python -m app.main
```

The most recently modified CSV in `app/data/input/` is processed and written to
`app/data/output/categorized_<original_filename>.csv` with a `Category` column
appended. Verified classifications are persisted to `app/data/cache.json` so
repeat runs skip the LLM entirely for merchants seen before.

### 5. (Optional) Interactive testing and evaluation

```bash
agents-cli playground          # chat with the Node 1 categorizer agent directly
uv run pytest tests/unit tests/integration   # run unit + integration tests
agents-cli eval generate && agents-cli eval grade   # run the eval loop
```

## Security Notes

- PII masking is local and deterministic (regex-only, no LLM/network round-trip)
  and runs before any transaction description is sent to the model.
- No API keys or credentials are stored in code; `.env` is gitignored and only
  `.env.example` (a template with no real values) is committed.
