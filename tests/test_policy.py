import pytest

from muiltilab import Judgments, Policy, decide


def make(**overrides):
    base = {
        "intent": "technical",
        "intent_confidence": 0.9,
        "urgency": 0.5,
        "urgency_confidence": 0.9,
        "security_risk": 0.02,
        "wants_refund": 0.01,
    }
    base.update(overrides)
    return Judgments(**base)


@pytest.mark.parametrize(
    ("judgments", "queue", "priority"),
    [
        (make(intent="technical"), "technical", "normal"),
        (make(intent="account"), "account", "normal"),
        (make(intent="billing"), "billing", "normal"),
        (make(intent="other"), "human", "normal"),
        (make(intent="not-a-real-option"), "human", "normal"),
        (make(intent_confidence=0.49), "human", "normal"),
        (make(intent_confidence=0.5), "technical", "normal"),
        (make(security_risk=0.5), "security", "high"),
        (make(security_risk=0.93, intent_confidence=0.2), "security", "high"),
        (make(intent="billing", wants_refund=0.88, intent_confidence=0.91), "billing-refunds", "normal"),
        (make(intent="billing", wants_refund=0.5, intent_confidence=0.8), "billing-refunds", "normal"),
        (make(intent="billing", wants_refund=0.88, intent_confidence=0.79), "human", "high"),
        (make(intent="technical", wants_refund=0.95), "technical", "normal"),
        (make(urgency=2.0, urgency_confidence=0.84), "technical", "high"),
        (make(urgency=2.0, urgency_confidence=0.49), "technical", "normal"),
        (make(urgency=1.99, urgency_confidence=0.99), "technical", "normal"),
    ],
)
def test_routing_table(judgments, queue, priority):
    decision = decide(judgments)
    assert decision.queue == queue
    assert decision.priority == priority


def test_every_decision_explains_itself():
    for judgments in (make(), make(intent="other"), make(security_risk=0.9)):
        assert decide(judgments).reasons


def test_unknown_intent_is_reported_as_such():
    decision = decide(make(intent="nonsense"))
    assert decision.reasons == ("model returned unknown intent 'nonsense'",)


def test_thresholds_are_code_owned_and_retunable_without_new_judgments():
    judgments = make(intent_confidence=0.9)
    assert decide(judgments).queue == "technical"
    assert decide(judgments, Policy(min_intent_confidence=0.95)).queue == "human"


def test_default_policy_is_immutable_shared_instance():
    assert decide(make()) == decide(make(), Policy())
