"""Closed enumerations matching the problem statement / MCP title keys."""

from __future__ import annotations

from enum import Enum


class Topic(str, Enum):
    """Exact string keys used in MCP calendar titles."""

    KYC_ONBOARDING = "KYC Onboarding"
    SIP_MANDATES = "SIP Mandates"
    STATEMENTS_TAX_DOCS = "Statements/Tax Docs"
    WITHDRAWALS_TIMELINES = "Withdrawals & Timelines"
    ACCOUNT_CHANGES_NOMINEE = "Account Changes/Nominee"


class Intent(str, Enum):
    BOOK_NEW = "book_new"
    RESCHEDULE = "reschedule"
    CANCEL = "cancel"
    WHAT_TO_PREPARE = "what_to_prepare"
    CHECK_AVAILABILITY = "check_availability"
    UNKNOWN = "unknown"


class AdvisorDisclaimerStatus(str, Enum):
    PENDING = "pending"
    ACKNOWLEDGED = "acknowledged"


class TimeWindow(str, Enum):
    MORNING = "morning"  # 09:00–12:00 IST
    AFTERNOON = "afternoon"  # 12:00–17:00 IST
    EVENING = "evening"  # 17:00–20:00 IST
    EXACT = "exact"


class BookingStatus(str, Enum):
    TENTATIVE = "tentative"
    WAITLISTED = "waitlisted"
    CANCELLED = "cancelled"
