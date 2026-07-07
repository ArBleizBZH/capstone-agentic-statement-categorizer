# Design Spec: Statement Categorizer Agent

This document outlines the deterministic execution flow, schema boundaries, directory structures, and architectural components for the Statement-Categorizer Capstone project.

## 1. Capstone Evaluation Criteria Alignment
To satisfy the course's evaluation rubric entirely within the repository codebase, this project explicitly implements and exposes the following three key concepts:
- **Agent System (ADK):** Logic is encapsulated using the official `google.adk` Agent framework inside `app/agent.py`.
- **Agent Skills (CLI):** Core processing logic and tool abstractions are mapped directly to the local project structure to be managed by the `agents-cli`.
- **Security Features:** A deterministic, regex-driven PII Masking Layer sits at the mouth of the ingestion node, preventing sensitive account details from reaching external LLM networks.

---

## 2. Environment & Directory Layout
To ensure predictable execution by the automated grading framework and the `agents-cli`, the workspace enforces a strict storage layout under the root directory:

*   `data/input/` - Folder containing raw incoming source banking CSV files.
*   `data/output/` - Folder where processed and categorized results are compiled.
*   `data/cache.json` - Persistent local storage file mapping unique historical descriptions to verified high-confidence categories.

### File Ingestion Mechanics
The ingestion sequence handles input dynamically:
1. The system scans the `data/input/` directory on startup.
2. It identifies and selects the single most recently modified CSV file in that directory.
3. The file is cleanly loaded into a Pandas DataFrame using the defined schema attributes.

### Output Target Mapping
Once execution concludes for all rows, the system exports the updated DataFrame into the `data/output/` directory. The export uses a standard prefix naming convention: `categorized_[original_filename].csv`.

---

## 3. Data Schemas

### Input CSV Columns
The incoming bank statement file contains the following structure:
`Transaction Date`, `Post Date`, `Description`, `Type`, `Amount`, `Memo`

### Output CSV Columns
The finalized processing sink appends a single validated category column:
`Transaction Date`, `Post Date`, `Description`, `Type`, `Amount`, `Memo`, `Category`

### LLM JSON Interface Schema
The Stochastic Inference Node must return a raw JSON payload matching this structure exactly:
```json
{
  "category": "string",
  "confidence": float
}
```

---

## 4. Master Taxonomy
All transactions must map strictly to one of the following ten categories. No other values are permitted:
## Predefined Taxonomy
Choose the category that best matches the merchant and context:
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
[Load Newest CSV from data/input/ via Pandas] 
                      │
          [For Each Row in DataFrame]
                      │
                      ├──► [Check data/cache.json] ──(Hit)──► [Apply Category] ──► [Next Row]
                      │          │
                      │       (Miss)
                      │          ▼
                      │   [Sanitize & Mask PII via Regex]  <-- (Satisfies: Security Criteria)
                      │          │
                      │          ▼
                      │   [Execute Node 1: Initial LLM Inference] <-- (Satisfies: ADK Criteria)
                      │          │
                      │   [Receive: Category + Confidence]
                      │          │
                      │          ├─► (Confidence >= 0.85) ──► [Save to Cache] ──► [Apply Category] ──► [Next Row]
                      │          │
                      │          └─► (Confidence < 0.85) 
                      │                      │
                      │                      ▼
                      │   [Execute Node 2: Call External Search Tool] <-- (Satisfies: Agent Skills Criteria)
                      │                      │
                      │            [Search Vendor via API/Mock]
                      │                      │
                      │            [Evaluate Search Snippets via LLM]
                      │                      │
                      │                      ├─► (Confidence >= 0.85) ──► [Save to Cache] ──► [Apply Category]
                      │                      │
                      │                      └─► (Confidence < 0.85 or Fail) ──► [Set Category as "Unknown"]
```

### Operational Pipeline Breakdown
1. **Cache Inspection (Local Memory):** Look up the raw `Description` string in `data/cache.json`.
   - *Hit:* Apply the cached category directly, skip network execution, and advance to the next row.
   - *Miss:* Advance to Step 2.
2. **PII Masking Layer (Security Gate):** Run the string through the local regex masking skill. Redact card numbers or account details to `[REDACTED_CARD]`.
3. **Initial LLM Inference (Node 1 - ADK Agent):** Pass the sanitized string to the Gemini model.
   - If the returned `confidence` is greater than or equal to 0.85, update `data/cache.json`, apply the category, and advance to the next row.
   - If the returned `confidence` is less than 0.85, advance to Step 4.
4. **Fallback Web Search (Node 2 - External Tool Skill):** Execute the mock web search engine using the merchant name to retrieve surrounding context snippets.
5. **Secondary LLM Evaluation:** Pass the retrieved search snippets along with the transaction string back to the model for a final assessment.
   - If the evaluation `confidence` is greater than or equal to 0.85, update `data/cache.json`, apply the category, and finish.
   - If the evaluation `confidence` is less than 0.85 or the tool fails entirely, apply the category as `"Unknown"` to allow for manual user auditing.

### Robust Network & API Error Handling
To keep the execution pipeline completely non-blocking, all external network interactions (including initial model inference, search queries, and secondary evaluations) are wrapped in fallback exception handlers. If an API key quota exhaustion error, cellular timeout, or connection drop triggers:
- The system logs the specific exception message cleanly to standard error output.
- The pipeline intercepts the crash, immediately maps the current row's transaction category to `"Unknown"`, and safely moves forward to process the remaining entries in the data collection without stopping the process.

---

## 6. System Instructions (The Prompt Harness)
The core agent uses this rigid instructional block to guarantee format adherence and prevent token leakage:

```text
You are a deterministic financial transaction classifier. 
Analyze the input transaction description and map it to exactly one category from the APPROVED_TAXONOMY list.

APPROVED_TAXONOMY: [Income, Housing & Rent, Utilities, Groceries, Dining Out, Transportation, Shopping, Entertainment, Medical & Healthcare, Unknown]

CRITICAL ENFORCEMENT PROTOCOLS:
1. Output MUST be raw JSON matching this schema exactly: {"category": "string", "confidence": float}
2. The "confidence" value must be a float between 0.0 and 1.0 representing your certainty.
3. DO NOT wrap the output in markdown code blocks (e.g., do not use ```json).
4. Do not include any conversational text, explanations, whitespace padding, or introductory prose. Output ONLY the raw JSON string.
5. If the transaction description is ambiguous or does not map clearly to the taxonomy, set the category to "Unknown" and confidence to 0.0.
```

---

## 7. Tool & Skill Declarations
All custom agent skills must live cleanly within the `.agents/skills/` directory tree to allow the `agents-cli` framework to discover, map, and cleanly catalog them.

```python
from typing import Optional, Dict

# Path: .agents/skills/cache_manager.py
def check_local_cache(description: str) -> Optional[Dict[str, any]]:
    """
    Searches data/cache.json for an identical transaction description key.
    Returns: {"category": str, "confidence": float} if hit, None if miss.
    """
    pass

# Path: .agents/skills/cache_manager.py
def update_local_cache(description: str, category: str, confidence: float) -> None:
    """
    Appends a newly verified high-confidence transaction classification to the data/cache.json file.
    """
    pass

# Path: .agents/skills/pii_masker.py
def mask_pii(transaction_str: str) -> str:
    """
    Scrubs sensitive numerical sequences (e.g., 16-digit cards, routing formats) out of incoming transaction strings using local regex patterns.
    """
    pass

# Path: .agents/skills/web_search.py
def search_merchant_web(description: str) -> str:
    """
    Queries a mockup or live search endpoint using the sanitized merchant name to retrieve contextual text snippets.
    """
    pass
```