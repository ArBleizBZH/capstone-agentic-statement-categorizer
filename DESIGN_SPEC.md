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
+-- data/
¦   +-- input/                     <- Inbound raw statement CSV source folder
¦   +-- output/                    <- Outbound compiled transaction target folder
¦   +-- cache.json                 <- Persistent historical classification cache
+-- app/
¦   +-- __init__.py
¦   +-- agent.py                   <- Core ADK Agent & Workflow instance definitions
¦   +-- main.py                    <- Asynchronous Batch Orchestrator entrypoint
¦   +-- skills/
¦       +-- transaction-categorizer/
¦       ¦   +-- SKILL.md           <- Node 1 Primary classification instructions
¦       ¦   +-- tools.py
¦       +-- fallback-search/
¦           +-- SKILL.md           <- Node 2 Context enlargement instruction harness
¦           +-- tools.py
+-- pyproject.toml                 <- Project metadata and uv dependency locks
+-- DESIGN_SPEC_FINAL.md           <- System design specification
```

### File Ingestion Mechanics
1. **Target Identification:** The orchestration script scans `data/input/` on execution and isolates the single most recently modified CSV file.
2. **Pandas Extraction:** The selected target is loaded into a structured Pandas DataFrame to enforce strict data type boundaries during memory manipulation.

### Output Serialization
Upon batch termination, the updated DataFrame is exported to `data/output/` using the explicit naming prefix: `categorized_[original_filename].csv`.

---

## 3. Data Schemas

### Input CSV Boundary
The target banking statements conform to a standardized 6-column configuration:
`Transaction Date`, `Post Date`, `Description`, `Type`, `Amount`, `Memo`

### Output CSV Boundary
The sink architecture appends a final validated classification string, maintaining schema integrity:
`Transaction Date`, `Post Date`, `Description`, `Type`, `Amount`, `Memo`, `Category`

### LLM Interface Contract
Stochastic nodes are bound to an explicit structured JSON output schema to ensure predictable downstream validation:
```json
{
  "category": "string",
  "confidence": float
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
                                ¦
             [Read cache.json into Global Memory Dict]
                                ¦
             [Load Target Input CSV into Pandas DataFrame]
                                ¦
          [Instantiate Bounded Concurrency Semaphore (Capped 3-5)]
                                ¦
     +-----------------------------------------------------+
     ?                                                     ?
[Worker Task: Row 1]                                  [Worker Task: Row N]
     ¦                                                     ¦
     +-? 1. Check Shared Memory Cache Dict (Hit) ----------+-? Apply Category --+
     ¦                                                     ¦                    ¦
     +-? (Cache Miss)                                      ¦                    ¦
     ¦     ¦                                               ¦                    ¦
     ¦     ?                                               ¦                    ¦
     ¦   2. Apply Local Regex PII Masking Gateway          ¦                    ¦
     ¦     ¦                                               ¦                    ¦
     ¦     ?                                               ¦                    ¦
     ¦   3. Spawn Isolated ADK Worker Agent                         ¦                    ¦
     ¦     ¦                                               ¦                    ¦
     ¦     ?                                               ¦                    ¦
     ¦   4. Execute Node 1: "transaction-categorizer" Skill¦                    ¦
     ¦     ¦                                               ¦                    ¦
     ¦     +-? (Confidence >= 0.85) -----------------------+-? Update Memory    ¦
     ¦     ¦                                               ¦   Cache & Apply    ¦
     ¦     +-? (Confidence < 0.85)                         ¦                    ¦
     ¦           ¦                                         ¦                    ¦
     ¦           ?                                         ¦                    ¦
     ¦         5. Execute Node 2: "fallback-search" Skill  ¦                    ¦
     ¦           ¦  (Invokes native google_search tool)    ¦                    ¦
     ¦           ¦                                         ¦                    ¦
     ¦           +-? (Disambiguates and matches taxonomy) -+-? Update Memory    ¦
     ¦           ¦                                         ¦   Cache & Apply    ¦
     ¦           +-? (Confidence < 0.85 / Exception / 429) +-? Apply "Unknown"  ¦
     ¦                                                     ¦                    ¦
     +-----------------------------------------------------+                    ¦
                                ?                                               ¦
             [Await completion of all asyncio worker tasks]                    ¦
                                ¦                                               ¦
            [Flush Local Memory Cache Dict to data/cache.json] ?----------------+
                                ¦
            [Serialize output to data/output/ directory]
                                ¦
                               [End]
```

### Execution Stage Breakdown
1. **Shared Memory Cache Filter (Local):** To prevent asynchronous race conditions and file-locking bottlenecks, `data/cache.json` is ingested into a native Python dictionary exactly *once* at startup. Workers scan this in-memory collection. If a string match hits, the cached category is mapped instantly, eliminating LLM execution.
2. **Local PII Masking Gateway (Security):** If a cache miss occurs, the transaction description is processed locally using regex utilities. Elements like credit card tracking blocks, invoice IDs, and specific numeric account tags are normalized (e.g., `[REDACTED_CARD]`) before passing out of the machine.
3. **Atomic Agent Allocation (ADK Layer):** A dedicated, short-lived `google.adk` Agent instance is instantiated for the isolated transaction row. It runs concurrently inside the boundaries of an `asyncio.Semaphore` block to maintain a stable, predictable Requests-Per-Minute threshold.
4. **Primary Inference (Node 1 - Categorizer Skill):** The agent runs the sanitized description against the instructions loaded via the `transaction-categorizer` skill. If the JSON validation returns a confidence score $\ge 0.85$, the worker commits the result to the shared in-memory dictionary, writes the category to the DataFrame row, and finishes.
5. **Context Expansion (Node 2 - Fallback Search Skill):** If the classification confidence falls below $0.85$, the agent switches context to the `fallback-search` skill. This layer equips the agent with the framework's native `Google Search` tool. The agent executes a live web search on the fragmented vendor string (e.g., `"CRAZEE COW Belle Fourche"`), processes the top web snippets to identify the core business function, and extracts relevant keywords to disambiguate the item. It then re-attempts mapping the entity against the 17-item taxonomy. If successful, the results are committed to the memory cache.
6. **Graceful Pipeline Isolation:** If Node 2 cannot resolve the classification or if network exhaustion faults (such as a 429 rate limit or connectivity dropout) occur inside a worker task, the error is intercepted cleanly by an internal `try/except` boundary. The system logs the failure message to standard error, flags the target cell as `"Unknown"` to maintain complete downstream compliance, and keeps the concurrent batch tasks moving without system interruption.
7. **Cache Flush Synchronization:** Once all parallel worker tasks resolve, the main thread performs a single atomic write operation, flushing the updated memory dictionary cleanly back onto disk at `data/cache.json`.

---

## 6. System Instructions (The Prompt Harness)
The core agent logic inside the `transaction-categorizer` skill uses a frozen instructional harness to force structured formats and completely eradicate conversational token leakage:

```text
You are a deterministic financial transaction classification agent. 
Analyze the input transaction string and assign it to exactly one category from the APPROVED_TAXONOMY array.

APPROVED_TAXONOMY: [
  "Income", "Utilities", "Entertainment", "Food & Dining", "Shopping", 
  "Gas & Fuel", "Insurance", "Housing", "Medical & Health", "Auto Loan", 
  "Groceries", "Travel & Recreation", "Subscriptions & Software", 
  "Home Improvement", "Manual Review Required", "Cash Withdrawal", "Unknown"
]

CRITICAL CONSTRAINTS:
1. Output MUST be raw JSON matching this schema exactly: {"category": "string", "confidence": float}
2. The "confidence" value must be a floating-point number between 0.0 and 1.0 representing your statistical certainty.
3. DO NOT wrap the output in markdown fences (e.g., do not enclose within ```json ... ```).
4. Do not emit intro prose, explanatory notes, formatting white-space padding, or concluding remarks. Output ONLY the raw JSON string.
5. If the transaction description is highly fragmented, ambiguous, or lacks explicit semantic features to cleanly fit the taxonomy, you must fallback to "Unknown" with a confidence score of 0.0.
```

---

## 7. Tool & Skill Declarations
Custom operational routines and native extensions are explicitly isolated into the `app/skills/` runtime directory to guarantee discovery by the execution engine and clear decoupling of algorithmic steps:

```python
from typing import Optional, Dict

# Module Path: app/skills/transaction-categorizer/tools.py
def mask_pii_local(transaction_str: str) -> str:
    """
    Deterministically scrubs highly specific identifier metrics (card groups, account strings)
    out of inbound transaction items using compiled local regex parameters.
    """
    pass

# Module Path: app/skills/fallback-search/tools.py
# Node 2 imports and attaches the framework's native search utility directly:
# from google.adk.tools import google_search
```
