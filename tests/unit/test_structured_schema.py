"""StructuredExtraction JSON schema round-trip."""

from nlu.schema import StructuredExtraction, topic_enum
from domain.enums import Topic


def test_from_dict_normalizes_intent_and_topic() -> None:
    ext = StructuredExtraction.from_dict(
        {
            "intent": "BOOK_NEW",
            "topic": "kyc_onboarding",
            "date_phrase": "next Tuesday",
            "time_window": "afternoon",
            "booking_code_guess": "NL-A742",
            "wants_investment_advice": False,
            "confidence": 0.88,
        }
    )
    assert ext.intent == "book_new"
    assert ext.topic == "kyc_onboarding"
    assert ext.time_window == "afternoon"
    assert topic_enum(ext.topic) is Topic.KYC_ONBOARDING
    assert ext.to_json_dict()["date_phrase"] == "next Tuesday"


def test_invalid_intent_becomes_unknown() -> None:
    ext = StructuredExtraction.from_dict({"intent": "dance", "confidence": 1})
    assert ext.intent == "unknown"
