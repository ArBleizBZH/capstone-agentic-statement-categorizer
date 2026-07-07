import os
import re
import json
import glob
import pandas as pd
from google.adk import Agent

# =====================================================================
# 1. System Prompt Harness & Master Taxonomy Configuration
# =====================================================================
SYSTEM_INSTRUCTION = """You are a deterministic financial transaction classifier. 
Analyze the input transaction description and map it to exactly one category from the APPROVED_TAXONOMY list.

APPROVED_TAXONOMY:
1. Income (e.g., salary, deposits, interest)
2. Utilities (e.g., electricity, gas, natural gas, cellular, water, internet)
3. Entertainment (e.g., streaming services, Netflix, Spotify, concert tickets, bars)
4. Food & Dining (e.g., restaurants, bakeries, cafes, fast food, coffee shops)
5. Shopping (e.g., general merchandise, Amazon, retail, department stores)
6. Gas & Fuel (e.g., gas stations, Chevron, Shell)
7. Insurance (e.g., auto insurance, health insurance, Geico)
8. Housing (e.g., rent, mortgage payments)
9. Medical & Health (e.g., healthcare providers, pharmacies, Blue Cross, doctors)
10. Auto Loan (e.g., car financing, monthly auto payments)
11. Groceries (e.g., supermarket, Safeway, Kroger, grocery store)
12. Travel & Recreation (e.g., travel agencies, booking services, flights, camping, recreation.gov)
13. Subscriptions & Software (e.g., Adobe, cloud storage, monthly software fees)
14. Home Improvement (e.g., hardware store, Runnings Farm & Fleet, building materials)
15. Manual Review Required (e.g., checks, wire transfers with no merchant name)
16. Cash Withdrawal (e.g., ATM transactions)
17. Unknown (Mandatory fallback for unresolved/low-confidence transactions)

CRITICAL ENFORCEMENT PROTOCOLS:
1. Output MUST be raw JSON matching this schema exactly: {"category": "string", "confidence": float}
2. The "confidence" value must be a float between 0.0 and 1.0 representing your certainty.
3. DO NOT wrap the output in markdown code blocks (e.g., do not use ```json).
4. Do not include any conversational text, explanations, whitespace padding, or introductory prose. Output ONLY the raw JSON string.
5. If the transaction description is ambiguous or does not map clearly to the taxonomy, set the category to "Unknown" and confidence to 0.0.
"""

# =====================================================================
# 2. ADK Agent Framework Initialization
# =====================================================================
# Exposing root_agent at module level allows 'agents-cli' to discover it
root_agent = Agent(
    name="statement_categorizer",
    model="gemini-2.5-flash",
    instruction=SYSTEM_INSTRUCTION
)

# =====================================================================
# 3. Custom Skill Layers & Auxiliary Logic
# =====================================================================
def mask_pii(text: str) -> str:
    """Scrubs sensitive account numbers or card variations via local regex patterns."""
    card_pattern = re.compile(r'\b(?:\d[ -]*?){13,16}\b')
    return card_pattern.sub('[REDACTED_CARD]', text)

def mock_web_search(description: str) -> str:
    """Simulates external merchant verification metadata when token analysis scores are low."""
    return f"Search snippets for {description}: Active commercial corporate entity with registered operating storefront."

CACHE_FILE = "data/cache.json"

def load_cache() -> dict:
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_cache(cache_data: dict):
    os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
    try:
        with open(CACHE_FILE, "w") as f:
            json.dump(cache_data, f, indent=2)
    except Exception as e:
        print(f"Warning: Cache persistent write skipped: {e}")

# =====================================================================
# 4. Stochastic Inference Routing Node
# =====================================================================
def call_llm_inference_node(prompt_payload: str) -> dict:
    """Executes model inference via ADK runtime with protective exception handling."""
    try:
        response = root_agent.run(prompt_payload)
        raw_text = response.text.strip()
        
        # Strip potential markdown code fence leakage gracefully
        if raw_text.startswith("```"):
            raw_text = raw_text.split("```")[1]
            if raw_text.startswith("json"):
                raw_text = raw_text[4:]
        
        return json.loads(raw_text.strip())
    except Exception as e:
        print(f"Exception caught during live model inference node: {e}")
        return {"category": "Unknown", "confidence": 0.0}

# =====================================================================
# 5. Core Batch Process Orchestration Pipeline
# =====================================================================
def run_batch_processing():
    input_dir = "data/input"
    output_dir = "data/output"
    
    csv_files = glob.glob(os.path.join(input_dir, "*.csv"))
    if not csv_files:
        print(f"Execution Aborted: No target CSV source sheets detected in '{input_dir}/'")
        return
        
    # Isolate the single most recently updated sheet in the ingestion directory
    newest_file = max(csv_files, key=os.path.getmtime)
    print(f"\n[Ingestion Stream Activated] Processing latest target: {newest_file}")
    
    try:
        df = pd.read_csv(newest_file)
    except Exception as e:
        print(f"Fatal CSV Parse Failure: {e}")
        return
        
    if 'Description' not in df.columns:
        print("Fatal Error: 'Description' column missing from target source configuration template.")
        return
        
    cache = load_cache()
    compiled_categories = []
    
    for idx, row in df.iterrows():
        raw_description = str(row['Description']).strip()
        
        # Step 1: Local Cache Check
        if raw_description in cache:
            cached_val = cache[raw_description].get("category", "Unknown")
            print(f"Row {idx:03d} | Local Cache Hit -> {cached_val}")
            compiled_categories.append(cached_val)
            continue
            
        # Step 2: Local Security Guard (PII Scrubbing)
        sanitized_description = mask_pii(raw_description)
        
        # Step 3: Node 1 Primary Inference
        print(f"Row {idx:03d} | Evaluating Input: '{sanitized_description}'")
        node1_res = call_llm_inference_node(f"Transaction: {sanitized_description}")
        
        category = node1_res.get("category", "Unknown")
        confidence = node1_res.get("confidence", 0.0)
        
        if confidence >= 0.85:
            print(f"        | Node 1 Match Verified ({confidence:.2f}) -> {category}")
            cache[raw_description] = {"category": category, "confidence": confidence}
            compiled_categories.append(category)
        else:
            # Step 4 & 5: Node 2 Fallback Verification
            print(f"        | Marginal Confidence ({confidence:.2f}). Triggering Secondary Contextual Fallback...")
            search_data = mock_web_search(sanitized_description)
            
            fallback_prompt = (
                f"Transaction: {sanitized_description}\n"
                f"Web Search Context Metadata: {search_data}"
            )
            node2_res = call_llm_inference_node(fallback_prompt)
            
            fb_category = node2_res.get("category", "Unknown")
            fb_confidence = node2_res.get("confidence", 0.0)
            
            if fb_confidence >= 0.85:
                print(f"        | Node 2 Match Verified ({fb_confidence:.2f}) -> {fb_category}")
                cache[raw_description] = {"category": fb_category, "confidence": fb_confidence}
                compiled_categories.append(fb_category)
            else:
                print(f"        | Unresolved Taxonomy Boundary ({fb_confidence:.2f}). Mapping to 'Unknown'")
                compiled_categories.append("Unknown")
                
    # Update DataFrame tracking arrays and export execution results
    df['Category'] = compiled_categories
    save_cache(cache)
    
    os.makedirs(output_dir, exist_ok=True)
    out_name = f"categorized_{os.path.basename(newest_file)}"
    destination_sink = os.path.join(output_dir, out_name)
    
    df.to_csv(destination_sink, index=False)
    print(f"\n[Execution Pipe Concluded] Compiled results routed safely to: {destination_sink}\n")

if __name__ == "__main__":
    run_batch_processing()
