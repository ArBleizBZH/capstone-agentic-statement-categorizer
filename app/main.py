"""Asynchronous Batch Orchestrator entrypoint (DESIGN_SPEC.md section 5).

Ingests the most recently modified CSV in `app/data/input/`, categorizes every
row through the Node 1 / Node 2 worker-agent pipeline under a bounded
concurrency semaphore, and serializes the result to `app/data/output/`.
"""

import asyncio
import glob
import json
import os
import sys
import uuid

import pandas as pd
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from app.agent import CONFIDENCE_THRESHOLD, CategoryOutput, node1_agent, node2_agent
from app.skills.transaction_categorizer.tools import mask_pii_local

# =====================================================================
# 1. Directory & Cache Constants
# =====================================================================
_APP_DIR = os.path.dirname(os.path.abspath(__file__))
INPUT_DIR = os.path.join(_APP_DIR, "data", "input")
OUTPUT_DIR = os.path.join(_APP_DIR, "data", "output")
CACHE_FILE = os.path.join(_APP_DIR, "data", "cache.json")

APP_NAME = "statement_categorizer"
MAX_CONCURRENCY = 4  # DESIGN_SPEC.md: bounded semaphore capped 3-5


def load_cache() -> dict:
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_cache(cache_data: dict) -> None:
    os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
    try:
        with open(CACHE_FILE, "w") as f:
            json.dump(cache_data, f, indent=2)
    except Exception as e:
        print(f"Warning: Cache persistent write skipped: {e}", file=sys.stderr)


# =====================================================================
# 2. Isolated Agent Invocation
# =====================================================================
async def _run_agent_turn(
    runner: Runner, session_service: InMemorySessionService, sanitized_text: str
) -> CategoryOutput:
    """Spawns an isolated session for a single transaction turn and parses the
    structured JSON response into a CategoryOutput.
    """
    session_id = f"txn-{uuid.uuid4().hex}"
    await session_service.create_session(
        app_name=APP_NAME, user_id="batch_worker", session_id=session_id
    )
    message = types.Content(
        role="user", parts=[types.Part.from_text(text=sanitized_text)]
    )

    final_text = None
    async for event in runner.run_async(
        user_id="batch_worker", session_id=session_id, new_message=message
    ):
        if event.is_final_response() and event.content and event.content.parts:
            final_text = "".join(
                part.text for part in event.content.parts if part.text
            )

    if not final_text:
        raise ValueError("No final response text returned by agent")

    return CategoryOutput(**json.loads(final_text))


# =====================================================================
# 3. Per-Row Worker Task
# =====================================================================
async def classify_transaction(
    idx: int,
    raw_description: str,
    cache: dict,
    semaphore: asyncio.Semaphore,
    session_service: InMemorySessionService,
    node1_runner: Runner,
    node2_runner: Runner,
) -> str:
    # Step 1: Shared Memory Cache Filter
    if raw_description in cache:
        cached_val = cache[raw_description].get("category", "Unknown")
        print(f"Row {idx:03d} | Local Cache Hit -> {cached_val}")
        return cached_val

    async with semaphore:
        # Step 2: Local PII Masking Gateway
        sanitized_description = mask_pii_local(raw_description)

        # Step 3 & 4: Atomic Agent Allocation + Node 1 Primary Inference
        print(f"Row {idx:03d} | Evaluating Input: '{sanitized_description}'")
        try:
            node1_result = await _run_agent_turn(
                node1_runner, session_service, sanitized_description
            )
        except Exception as e:
            print(f"Row {idx:03d} | Node 1 exception: {e}", file=sys.stderr)
            node1_result = CategoryOutput(category="Unknown", confidence=0.0)

        if node1_result.confidence >= CONFIDENCE_THRESHOLD:
            print(
                f"        | Node 1 Match Verified ({node1_result.confidence:.2f}) "
                f"-> {node1_result.category}"
            )
            cache[raw_description] = {
                "category": node1_result.category,
                "confidence": node1_result.confidence,
            }
            return node1_result.category

        # Step 5: Node 2 Context Expansion Fallback
        print(
            f"        | Marginal Confidence ({node1_result.confidence:.2f}). "
            "Triggering Secondary Contextual Fallback..."
        )
        try:
            node2_result = await _run_agent_turn(
                node2_runner, session_service, sanitized_description
            )
        except Exception as e:
            print(f"Row {idx:03d} | Node 2 exception: {e}", file=sys.stderr)
            node2_result = CategoryOutput(category="Unknown", confidence=0.0)

        if node2_result.confidence >= CONFIDENCE_THRESHOLD:
            print(
                f"        | Node 2 Match Verified ({node2_result.confidence:.2f}) "
                f"-> {node2_result.category}"
            )
            cache[raw_description] = {
                "category": node2_result.category,
                "confidence": node2_result.confidence,
            }
            return node2_result.category

        # Step 6: Graceful Pipeline Isolation
        print(
            f"        | Unresolved Taxonomy Boundary "
            f"({node2_result.confidence:.2f}). Mapping to 'Unknown'"
        )
        return "Unknown"


# =====================================================================
# 4. Core Batch Process Orchestration Pipeline
# =====================================================================
async def run_batch_processing() -> None:
    csv_files = glob.glob(os.path.join(INPUT_DIR, "*.csv"))
    if not csv_files:
        print(f"Execution Aborted: No target CSV source sheets detected in '{INPUT_DIR}/'")
        return

    # File Ingestion Mechanics: isolate the single most recently modified sheet
    newest_file = max(csv_files, key=os.path.getmtime)
    print(f"\n[Ingestion Stream Activated] Processing latest target: {newest_file}")

    try:
        df = pd.read_csv(newest_file)
    except Exception as e:
        print(f"Fatal CSV Parse Failure: {e}", file=sys.stderr)
        return

    if "Description" not in df.columns:
        print("Fatal Error: 'Description' column missing from target source configuration template.")
        return

    cache = load_cache()
    semaphore = asyncio.Semaphore(MAX_CONCURRENCY)
    session_service = InMemorySessionService()
    node1_runner = Runner(
        agent=node1_agent, app_name=APP_NAME, session_service=session_service
    )
    node2_runner = Runner(
        agent=node2_agent, app_name=APP_NAME, session_service=session_service
    )

    tasks = [
        classify_transaction(
            idx,
            str(row["Description"]).strip(),
            cache,
            semaphore,
            session_service,
            node1_runner,
            node2_runner,
        )
        for idx, row in df.iterrows()
    ]
    compiled_categories = await asyncio.gather(*tasks)

    # Update DataFrame tracking arrays and export execution results
    df["Category"] = compiled_categories

    # Step 7: Cache Flush Synchronization (single atomic write after batch)
    save_cache(cache)

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    out_name = f"categorized_{os.path.basename(newest_file)}"
    destination_sink = os.path.join(OUTPUT_DIR, out_name)

    df.to_csv(destination_sink, index=False)
    print(f"\n[Execution Pipe Concluded] Compiled results routed safely to: {destination_sink}\n")


def main() -> None:
    asyncio.run(run_batch_processing())


if __name__ == "__main__":
    main()
