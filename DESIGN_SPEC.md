# Design Spec: Statement Categorizer Agent (Final Version)

This document outlines the asynchronous orchestrator-worker architecture, deterministic data boundaries, local security gateways, directory schemas, and native framework constraints for the Statement-Categorizer Capstone project.

## 1. Capstone Evaluation Criteria Alignment
To satisfy the course evaluation rubric comprehensively, the project implementation is engineered around four core evaluation vectors, avoiding mock dependencies and hardwired execution paths:
- **Agent / Multi-Agent System (ADK):** Implements an asynchronous Orchestrator-Worker concurrency pattern using the official `google.adk` framework within `app/agent.py`. The system splits batch execution into atomic, isolated agent instances per transaction.
- **Agent Skills (CLI Runtime):** Decouples processing layers and domain knowledge into discrete framework skills localized under `app/skills/`. Each skill directory is driven by its own `SKILL.md` manifest file to prevent LLM context rot via progressive disclosure.
- **Security Features (Local Boundary):** Configures an on-premise Data Security Firewall. A deterministic, regex-driven PII Masking Layer and a local memory cache intercept strings *before* payload execution, ensuring no sensitive identifiers leave the local runtime boundary.
- **Deployability (`uv` Environment):** Packages the runtime dependencies using a modern, fast `uv` lock schema, exposing clean entrypoints so that the automated testing suite can initialize execution cleanly using `agents-cli`.

---

## 2. Environment & Directory Layout
The workspace enforces a modular structure designed to support both local batch execution and headless framework evaluation (`agents-cli eval run`):

```text
statement-categorizer/
+-- app/
�   +-- __init__.py
�   +-- agent.py                   <- Core ADK Agent & Workflow instance definitions
�   +-- main.py                    <- Asynchronous Batch Orchestrator entrypoint
�   +-- skills/
�   �   +-- transaction_categorizer/
�   �   �   +-- SKILL.md           <- Node 1 Primary classification instructions
�   �   �   +-- tools.py           <- mask_pii_local() local PII gateway
�   �   +-- fallback_search/
�   �       +-- SKILL.md           <- Node 2 search-context instruction harness
�   +-- data/
�       +-- input/                     <- Inbound raw statement CSV source folder
�       +-- output/                    <- Outbound compiled transaction target folder
�       +-- cache.json                 <- Persistent historical classification cache
+-- pyproject.toml                 <- Project metadata and uv dependency locks
+-- DESIGN_SPEC.md                 <- System design specification
```

Note: `fallback_search/` has no `tools.py`. The native `google_search` tool is
imported and attached directly on the search-only agent defined in
`app/agent.py` (see sections 5 and 7) rather than wrapped in a skill tool
module.

### File Ingestion Mechanics
1. **Target Identification:** The orchestration script scans `app/data/input/` on execution and isolates the single most recently modified CSV file.
2. **Pandas Extraction:** The selected target is loaded into a structured Pandas DataFrame to enforce strict data type boundaries during memory manipulation.

### Output Serialization
Upon batch termination, the updated DataFrame is exported to `app/data/output/` using the explicit naming prefix: `categorized_[original_filename].csv`.

---

## 3. Data Schemas

### Input CSV Boundary
The target banking statements conform to a standardized 6-column configuration:
`Transaction Date`, `Post Date`, `Description`, `Type`, `Amount`, `Memo`

### Output CSV Boundary
The sink architecture appends a final validated classification string, maintaining schema integrity:
`Transaction Date`, `Post Date`, `Description`, `Type`, `Amount`, `Memo`, `Category`

### LLM Interface Contract
Stochastic nodes are bound to an explicit structured JSON output schema to ensure predictable downstream validation. `category` is not a free-form string: it is constrained to a `Literal` enum of the 17 Master Taxonomy values (section 4) - including the mandatory `"Unknown"` fallback - enforced natively via the ADK `output_schema` mechanism (a Pydantic model, `CategoryOutput` in `app/agent.py`), not by prompt instruction alone:
```json
{
  "category": "Income | Utilities | Entertainment | Food & Dining | Shopping | Gas & Fuel | Insurance | Housing | Medical & Health | Auto Loan | Groceries | Travel & Recreation | Subscriptions & Software | Home Improvement | Manual Review Required | Cash Withdrawal | Unknown",
  "confidence": float,
  "reasoning": "string | null"
}
```

---

## 4. Master Taxonomy
Every transaction must resolve cleanly to exactly one of the following 17 standardized categories. The taxonomy relies on a mandatory low-confidence fallback string (`Unknown`) to avoid model hallucination when boundary criteria are unmet:

1. `Income` (e.g., salary, deposits, interest)
2. `Utilities` (e.g., electricity, gas, natural gas, cellular, water, internet)
3. `Entertainment` (e.g., streaming services, Netflix, Spotify, concert tickets, bars)
4. `Food & Dining` (e.g., restaurants, bakeries, cafes, fast food, coffee shops)
5. `Shopping` (e.g., general merchandise, Amazon, retail, department stores)
6. `Gas & Fuel` (e.g., gas stations, Chevron, Shell)
7. `Insurance` (e.g., auto insurance, health insurance, Geico)
8. `Housing` (e.g., rent, mortgage payments)
9. `Medical & Health` (e.g., healthcare providers, pharmacies, Blue Cross, doctors)
10. `Auto Loan` (e.g., car financing, monthly auto payments)
11. `Groceries` (e.g., supermarket, Safeway, Kroger, grocery store)
12. `Travel & Recreation` (e.g., travel agencies, booking services, flights, camping, recreation.gov)
13. `Subscriptions & Software` (e.g., Adobe, cloud storage, monthly software fees)
14. `Home Improvement` (e.g., hardware store, Runnings Farm & Fleet, building materials)
15. `Manual Review Required` (e.g., checks, wire transfers with no merchant name)
16. `Cash Withdrawal` (e.g., ATM transactions)
17. `Unknown` (Mandatory fallback for unresolved/low-confidence transactions)

---

## 5. Architectural Data Flow

```text
              [Start: app/main.py Ingestion Engine]
                                �
             [Read cache.json into Global Memory Dict]
                                �
             [Load Target Input CSV into Pandas DataFrame]
                                �
          [Instantiate Bounded Concurrency Semaphore (Capped 3-5)]
                                �
     +-----------------------------------------------------+
     ?                                                     ?
[Worker Task: Row 1]                                  [Worker Task: Row N]
     �                                                     �
     +-? 1. Check Shared Memory Cache Dict (Hit) ----------+-? Apply Category --+
     �                                                     �                    �
     +-? (Cache Miss)                                      �                    �
     �     �                                               �                    �
     �     ?                                               �                    �
     �   2. Apply Local Regex PII Masking Gateway          �                    �
     �     �                                               �                    �
     �     ?                                               �                    �
     �   3. Spawn Isolated ADK Session (per-row)            �                    �
     �     �                                               �                    �
     �     ?                                               �                    �
     �   4. Execute Node 1: "transaction_categorizer" Agent �                    �
     �     �  (structured output_schema, no tools)         �                    �
     �     +-? (Confidence >= 0.85) -----------------------+-? Update Memory    �
     �     �                                               �   Cache & Apply    �
     �     +-? (Confidence < 0.85)                         �                    �
     �           �                                         �                    �
     �           ?                                         �                    �
     �     5a. Execute Node 2a: "fallback_search" Agent     �                    �
     �           �  (native google_search tool, plain-text �                    �
     �           �   output - NO output_schema; see note)  �                    �
     �           ?                                         �                    �
     �     5b. Node 2b: Re-invoke Node 1 Agent with the     �                    �
     �           original description + search context     �                    �
     �           appended                                   �                    �
     �           (structured output_schema, no tools)       �                    �
     �           �                                         �                    �
     �           +-? (Confidence >= 0.85) ------------------+-? Update Memory    �
     �           �                                         �   Cache & Apply    �
     �           +-? (Confidence < 0.85 / Exception / 429) +-? Apply "Unknown"  �
     �                                                     �                    �
     +-----------------------------------------------------+                    �
                                ?                                               �
             [Await completion of all asyncio worker tasks]                    �
                                �                                               �
            [Flush Local Memory Cache Dict to app/data/cache.json] ?-----------+
                                �
            [Serialize output to app/data/output/ directory]
                                �
                               [End]
```

> **Why Node 2 is two calls, not one:** the Gemini API rejects combining a
> built-in tool (`google_search`) with the function-calling mechanism ADK
> uses to enforce `output_schema` in the same request ("Built-in tools and
> Function Calling cannot be combined in the same request"). So the fallback
> is split into a search-only agent call (step 5a, plain text, no schema)
> followed by a second call to the *same* Node 1 classifier agent (step 5b,
> schema-enforced, no tools) with the search context appended to the prompt.
> This also matches `fallback_search/SKILL.md`, which only ever describes
> searching and formatting context "to be fed back into the LLM during
> secondary classification" - it never claims to decide the category itself.

### Execution Stage Breakdown
1. **Shared Memory Cache Filter (Local):** To prevent asynchronous race conditions and file-locking bottlenecks, `app/data/cache.json` is ingested into a native Python dictionary exactly *once* at startup. Workers scan this in-memory collection. If a string match hits, the cached category is mapped instantly, eliminating LLM execution.
2. **Local PII Masking Gateway (Security):** If a cache miss occurs, the transaction description is processed locally using regex utilities (`mask_pii_local`). Card-number-length digit sequences and long bank-account/SSN-style identifiers are normalized (e.g., `[REDACTED_CARD]`, `[REDACTED_ACCOUNT]`) before passing out of the machine, while short numeric tokens that carry classification signal (check numbers, store numbers) are left untouched.
3. **Atomic Agent Allocation (ADK Layer):** A fresh, isolated ADK session is created for the transaction row (unique session id per row, per call), so no conversational context bleeds between rows or between Node 1 and Node 2 calls. Rows run concurrently inside the boundaries of an `asyncio.Semaphore` block to maintain a stable, predictable Requests-Per-Minute threshold.
4. **Primary Inference (Node 1 - `transaction_categorizer` Agent):** The agent runs the sanitized description against the instructions loaded via the `transaction_categorizer` skill, returning a schema-validated `CategoryOutput` (category/confidence/reasoning). If confidence $\ge 0.85$, the worker commits the result to the shared in-memory dictionary, writes the category to the DataFrame row, and finishes.
5. **Context Expansion (Node 2 - Search Then Reclassify):** If confidence falls below $0.85$, the pipeline runs two further calls:
   - **5a. Search (Node 2a):** a dedicated `fallback_search` agent - equipped only with the framework's native `google_search` tool, carrying no `output_schema` - executes a live web search on the fragmented vendor string (e.g., `"CRAZEE COW Belle Fourche"`) and returns a plain-text summary of what it found.
   - **5b. Reclassify (Node 2b):** the Node 1 `transaction_categorizer` agent is re-invoked with the original description plus that search-context summary appended to the prompt, and returns a fresh schema-validated `CategoryOutput`. If confidence $\ge 0.85$ this time, the result is committed to the memory cache.
6. **Graceful Pipeline Isolation:** If step 5b still can't resolve the classification, or if network exhaustion faults (such as a 429 rate limit or connectivity dropout) occur at any point inside a worker task, the error is intercepted cleanly by an internal `try/except` boundary. The system logs the failure message to standard error, flags the target cell as `"Unknown"` to maintain complete downstream compliance, and keeps the concurrent batch tasks moving without system interruption.
7. **Cache Flush Synchronization:** Once all parallel worker tasks resolve, the main thread performs a single atomic write operation, flushing the updated memory dictionary cleanly back onto disk at `app/data/cache.json`.

---

## 6. System Instructions (The Prompt Harness)
Structural JSON formatting (raw JSON, no markdown fences, no conversational
prose, exact field names/types) is **not** left to prompt discipline: it is
enforced mechanically by the ADK `output_schema` mechanism (the `CategoryOutput`
Pydantic model in `app/agent.py`, attached to the `transaction_categorizer`
agent). This eliminates the class of failure where a model wraps its answer
in ```` ```json ```` fences or adds explanatory prose despite being told not to.

Instructions loaded from the `transaction_categorizer` skill therefore only
need to carry the *substantive* business logic - the taxonomy and the
confidence/fallback semantics - not formatting rules:

```text
Analyze the input transaction string and assign it to exactly one category from the APPROVED_TAXONOMY array.

APPROVED_TAXONOMY: [
  "Income", "Utilities", "Entertainment", "Food & Dining", "Shopping", 
  "Gas & Fuel", "Insurance", "Housing", "Medical & Health", "Auto Loan", 
  "Groceries", "Travel & Recreation", "Subscriptions & Software", 
  "Home Improvement", "Manual Review Required", "Cash Withdrawal", "Unknown"
]

Output a "confidence" float between 0.0 and 1.0 representing your statistical
certainty. If the transaction description is highly fragmented, ambiguous, or
lacks explicit semantic features to cleanly fit the taxonomy, fall back to
category "Unknown" with confidence 0.0.
```

The `fallback_search` agent (Node 2a) carries a separate, narrower instruction
set - loaded from `fallback_search/SKILL.md` - describing only how to extract
a search query and summarize results; it has no `output_schema` at all (see
section 5's note on why), so it never needs the JSON contract above.

---

## 7. Tool & Skill Declarations
Custom operational routines are isolated into the `app/skills/` runtime directory; the two agent instances that use them are assembled in `app/agent.py`:

```python
# Module Path: app/skills/transaction_categorizer/tools.py
def mask_pii_local(transaction_str: str) -> str:
    """
    Deterministically scrubs highly specific identifier metrics (card groups, account strings)
    out of inbound transaction items using compiled local regex parameters.
    """
    ...

# Module Path: app/agent.py
from google.adk import Agent
from google.adk.tools import google_search

# Node 1: structured classifier, no tools. Reused verbatim for the Node 2b
# reclassification pass (same agent, prompt augmented with search context).
node1_agent = Agent(
    name="transaction_categorizer",
    model="gemini-2.5-flash",
    instruction=...,          # loaded from transaction_categorizer/SKILL.md
    output_schema=CategoryOutput,
)

# Node 2a: search-only agent. Native google_search tool, deliberately NO
# output_schema - see section 5's note on why the two cannot be combined.
search_agent = Agent(
    name="fallback_search",
    model="gemini-2.5-flash",
    instruction=...,          # loaded from fallback_search/SKILL.md
    tools=[google_search],
)
```

There is no `app/skills/fallback_search/tools.py`: the native search utility
is imported and attached directly on `search_agent` above, since it is a
built-in framework tool rather than a custom function tool.
