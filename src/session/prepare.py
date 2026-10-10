"""Static “what to prepare” snippets per Topic — no LLM invention."""

from __future__ import annotations

from domain.enums import Topic

_PREPARE: dict[Topic, str] = {
    Topic.KYC_ONBOARDING: (
        "### KYC Onboarding — what to prepare\n"
        "- Government-issued photo ID (PAN / Aadhaar / passport as applicable)\n"
        "- Proof of address (recent utility bill or bank statement)\n"
        "- Bank account details for linking\n"
        "- Any existing demat / folio numbers if you have them\n"
        "\n"
        "Bring clear scans or originals; the advisor will guide next steps on the call."
    ),
    Topic.SIP_MANDATES: (
        "### SIP Mandates — what to prepare\n"
        "- Folio or scheme names you want to discuss\n"
        "- Current SIP amounts and debit dates (if active)\n"
        "- Bank mandate / NACH status if known\n"
        "- Questions about pause, increase, or new SIPs\n"
        "\n"
        "No need to share OTP or full account numbers in this chat."
    ),
    Topic.STATEMENTS_TAX_DOCS: (
        "### Statements / Tax Docs — what to prepare\n"
        "- Financial year or period you need statements for\n"
        "- Folio / scheme references if you have them\n"
        "- Whether you need capital-gains, account, or tax certificates\n"
        "- Preferred delivery channel (to be completed via the secure link later)\n"
        "\n"
        "The advisor can explain which documents apply; this chat will not collect PII."
    ),
    Topic.WITHDRAWALS_TIMELINES: (
        "### Withdrawals & Timelines — what to prepare\n"
        "- Approximate amount and scheme/folio you want to discuss\n"
        "- Whether the request is partial or full redemption\n"
        "- Any known lock-in or exit-load questions\n"
        "- Preferred payout timeline expectations\n"
        "\n"
        "Final instructions and bank details are completed via the secure link — not here."
    ),
    Topic.ACCOUNT_CHANGES_NOMINEE: (
        "### Account Changes / Nominee — what to prepare\n"
        "- Type of change (nominee, contact, bank link, etc.)\n"
        "- Folio or account reference if available\n"
        "- Supporting ID/address docs you may need for the advisor call\n"
        "- Nominee details to discuss (completed securely later)\n"
        "\n"
        "Do not share phone, email, or account numbers in this chat."
    ),
}

GENERIC_PREPARE = (
    "I can share a short checklist once you pick a topic:\n"
    "• KYC Onboarding\n"
    "• SIP Mandates\n"
    "• Statements/Tax Docs\n"
    "• Withdrawals & Timelines\n"
    "• Account Changes/Nominee\n"
    'Say e.g. “topic kyc” or “SIP”.'
)


def prepare_snippet(topic: Topic) -> str:
    return _PREPARE[topic]
