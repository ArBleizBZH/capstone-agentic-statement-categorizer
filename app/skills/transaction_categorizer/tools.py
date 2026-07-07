"""Local Security Gateway tooling for the transaction-categorizer skill.

Deterministic, regex-only PII scrubbing so sensitive identifiers never leave
the local runtime boundary before a transaction description is sent to the LLM.
"""

import re

# 13-19 digit card numbers, optionally grouped with spaces or dashes
# (e.g. "4111 1111 1111 1111", "4111-1111-1111-1111", "4111111111111111").
_CARD_PATTERN = re.compile(r"\b(?:\d[ -]*){13,19}\b")

# Bare runs of 9+ consecutive digits left over after card redaction: bank
# account numbers, SSNs, and similar long numeric identifiers. Deliberately
# does not touch shorter numeric tokens (store numbers, check numbers) since
# those carry classification signal (e.g. "CHECK #1042") rather than PII risk.
_ACCOUNT_PATTERN = re.compile(r"\b\d{9,}\b")


def mask_pii_local(transaction_str: str) -> str:
    """Deterministically scrubs highly specific identifier metrics (card groups,
    account strings) out of inbound transaction items using compiled local regex
    parameters.
    """
    sanitized = _CARD_PATTERN.sub("[REDACTED_CARD]", transaction_str)
    sanitized = _ACCOUNT_PATTERN.sub("[REDACTED_ACCOUNT]", sanitized)
    return sanitized
