"""NLU layer: structured extraction, resolvers, policy, engines."""

from nlu.types import NluResult
from nlu.engine import (
    NluEngine,
    PipelineNluEngine,
    RuleNluEngine,
    StubNluEngine,
    build_default_nlu_engine,
)
from nlu.schema import StructuredExtraction, TOPIC_KEYS
from nlu.resolvers import RelativeDateResolver, TopicMapper
from nlu.policy import IntentPolicy, CLARIFY_TOPIC
from nlu.pii import detect_pii, PII_REDIRECT_MESSAGE
from nlu.advice import (
    detect_investment_advice,
    ADVICE_REFUSAL_MESSAGE,
    advice_refusal_message,
    educational_url,
)

__all__ = [
    "NluResult",
    "NluEngine",
    "PipelineNluEngine",
    "RuleNluEngine",
    "StubNluEngine",
    "build_default_nlu_engine",
    "StructuredExtraction",
    "TOPIC_KEYS",
    "RelativeDateResolver",
    "TopicMapper",
    "IntentPolicy",
    "CLARIFY_TOPIC",
    "detect_pii",
    "PII_REDIRECT_MESSAGE",
    "detect_investment_advice",
    "ADVICE_REFUSAL_MESSAGE",
    "advice_refusal_message",
    "educational_url",
]
