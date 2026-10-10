"""Closed enum keys for MCP titles and intents."""

from domain.enums import Intent, Topic


def test_topic_mcp_title_keys() -> None:
    assert Topic.KYC_ONBOARDING.value == "KYC Onboarding"
    assert Topic.SIP_MANDATES.value == "SIP Mandates"
    assert Topic.STATEMENTS_TAX_DOCS.value == "Statements/Tax Docs"
    assert Topic.WITHDRAWALS_TIMELINES.value == "Withdrawals & Timelines"
    assert Topic.ACCOUNT_CHANGES_NOMINEE.value == "Account Changes/Nominee"
    assert len(Topic) == 5


def test_intent_values() -> None:
    assert {i.value for i in Intent} == {
        "book_new",
        "reschedule",
        "cancel",
        "what_to_prepare",
        "check_availability",
        "unknown",
    }
