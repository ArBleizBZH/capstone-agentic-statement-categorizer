"""Core ADK Agent & Workflow instance definitions.

Defines the two atomic, isolated worker agents described in DESIGN_SPEC.md
section 5 (Node 1: primary classification, Node 2: search-augmented fallback),
both driven by the `app/skills/*/SKILL.md` instruction manifests rather than
inline prompt text, to avoid LLM context rot via progressive disclosure.

Node 2 is deliberately split into two model calls rather than one: Gemini
rejects combining a built-in tool (`google_search`) with the function-calling
mechanism ADK uses to enforce `output_schema` ("Built-in tools and Function
Calling cannot be combined in the same request"). So `search_agent` only
gathers grounded search context (plain text, no schema), and `node1_agent` is
re-invoked with that context appended to make the final structured decision -
matching fallback_search/SKILL.md, which only ever describes searching and
formatting context "to be fed back into the LLM during secondary
classification", not deciding the category itself.
"""

from pathlib import Path
from typing import Literal, Optional

from google.adk import Agent
from google.adk.apps import App
from google.adk.tools import google_search
from pydantic import BaseModel

# =====================================================================
# 1. Master Taxonomy & LLM Interface Contract (DESIGN_SPEC.md sections 3-4)
# =====================================================================
CategoryName = Literal[
    "Income",
    "Utilities",
    "Entertainment",
    "Food & Dining",
    "Shopping",
    "Gas & Fuel",
    "Insurance",
    "Housing",
    "Medical & Health",
    "Auto Loan",
    "Groceries",
    "Travel & Recreation",
    "Subscriptions & Software",
    "Home Improvement",
    "Manual Review Required",
    "Cash Withdrawal",
    "Unknown",
]


class CategoryOutput(BaseModel):
    """Structured JSON contract enforced natively via `output_schema`."""

    category: CategoryName
    confidence: float
    reasoning: Optional[str] = None


CONFIDENCE_THRESHOLD = 0.85

# =====================================================================
# 2. Skill Instruction Loader (Progressive Disclosure)
# =====================================================================
_SKILLS_DIR = Path(__file__).parent / "skills"

_CONFIDENCE_NOTE = (
    "\n\nOutput a `confidence` float between 0.0 and 1.0 representing your "
    "statistical certainty. If the transaction description is highly "
    "fragmented, ambiguous, or lacks explicit semantic features to cleanly "
    "fit the taxonomy, fall back to category \"Unknown\" with confidence 0.0."
)


def _load_skill_instruction(skill_name: str) -> str:
    """Reads and returns the body of a skill's SKILL.md, stripping the YAML
    frontmatter, so instructions live in `app/skills/` rather than inline.
    """
    skill_md = (_SKILLS_DIR / skill_name / "SKILL.md").read_text(encoding="utf-8")
    if skill_md.startswith("---"):
        parts = skill_md.split("---", 2)
        if len(parts) >= 3:
            skill_md = parts[2]
    return skill_md.strip()


_NODE1_INSTRUCTION = _load_skill_instruction("transaction_categorizer") + _CONFIDENCE_NOTE
_SEARCH_INSTRUCTION = _load_skill_instruction("fallback_search")

# =====================================================================
# 3. ADK Agent Framework Initialization
# =====================================================================
# Node 1: primary zero-shot classifier (DESIGN_SPEC.md section 5, step 4).
# Also reused for the final re-classification pass after Node 2's search
# (same taxonomy/schema, prompt augmented with search context - see app/main.py).
node1_agent = Agent(
    name="transaction_categorizer",
    model="gemini-2.5-flash",
    instruction=_NODE1_INSTRUCTION,
    output_schema=CategoryOutput,
)

# Node 2: search-augmented fallback (DESIGN_SPEC.md section 5, step 5).
# Gathers grounded context via the native google_search tool only - no
# output_schema here (see module docstring for why it can't carry one).
search_agent = Agent(
    name="fallback_search",
    model="gemini-2.5-flash",
    instruction=_SEARCH_INSTRUCTION,
    tools=[google_search],
)

# Exposing root_agent/app at module level allows 'agents-cli' (playground, A2A,
# eval) to discover and serve the primary classifier interactively.
root_agent = node1_agent
app = App(root_agent=root_agent, name="app")
