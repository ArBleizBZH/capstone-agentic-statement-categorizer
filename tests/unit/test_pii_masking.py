"""Unit tests for the local Security Gateway (DESIGN_SPEC.md sections 1 & 5).

Deterministic, regex-only PII scrubbing - no LLM calls required.
"""

from app.skills.transaction_categorizer.tools import mask_pii_local


def test_redacts_card_number() -> None:
    result = mask_pii_local("POS PURCHASE CARD 4111111111111111 STORE #12")
    assert "4111111111111111" not in result
    assert "[REDACTED_CARD]" in result


def test_redacts_spaced_card_number() -> None:
    result = mask_pii_local("PAYMENT CARD 4111 1111 1111 1111")
    assert "4111 1111 1111 1111" not in result
    assert "[REDACTED_CARD]" in result


def test_redacts_long_account_number() -> None:
    result = mask_pii_local("ACH TRANSFER ACCOUNT 123456789012")
    assert "123456789012" not in result
    assert "[REDACTED_ACCOUNT]" in result


def test_leaves_check_number_untouched() -> None:
    result = mask_pii_local("CHECK #1042")
    assert result == "CHECK #1042"


def test_leaves_store_number_untouched() -> None:
    result = mask_pii_local("WM SUPERCENTER #1543 RETAIL")
    assert result == "WM SUPERCENTER #1543 RETAIL"


def test_leaves_plain_merchant_description_untouched() -> None:
    result = mask_pii_local("NETFLIX.COM DIG RECURRING")
    assert result == "NETFLIX.COM DIG RECURRING"
