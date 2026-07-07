---
name: fallback_search
description: Performs a keyless web search using duckduckgo_search to gather context about obscure or unknown merchant strings.
---

# Fallback Search Skill

## Objective
Retrieve search results for a given merchant/description query, compiling the snippets into a brief context string to aid secondary categorization.

## Instructions
1. Extract the primary merchant name or search query from the transaction description (e.g. stripping transaction numbers, transaction codes like ACH, etc.).
2. Execute a web search for the query using keyless search APIs (e.g., DuckDuckGo).
3. Gather top 3 search result snippets.
4. Format the snippets as context to be fed back into the LLM during secondary classification.
5. If search fails or times out, return a message indicating search context is unavailable.
