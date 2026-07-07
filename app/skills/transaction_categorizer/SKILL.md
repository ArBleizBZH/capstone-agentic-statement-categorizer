---
name: transaction_categorizer
description: Categorizes raw bank statement transaction descriptions into a fixed budget taxonomy using LLM zero-shot inference.
---

# Transaction Categorizer Skill

## Objective
Categorize a bank transaction description into exactly one category from a predefined budget taxonomy.

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

## Instructions
1. Analyze the transaction description, amount, and payment type (if provided).
2. Clean or ignore transaction IDs or reference numbers in the text.
3. Classify the transaction strictly into one of the 16 taxonomy categories listed above.
4. If it is a check transaction (e.g. description starts with `CHECK #`), select `Manual Review Required`.
5. If it is an ATM withdrawal, select `Cash Withdrawal`.
6. Provide a confidence score between `0.0` and `1.0` representing how certain you are of this category assignment.
7. Return a JSON object with the following fields:
   - `category`: The category name (string).
   - `confidence`: The confidence score (float).
   - `reasoning`: A short description of why this category was chosen (string).
