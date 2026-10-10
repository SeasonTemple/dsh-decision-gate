import json
from pathlib import Path
from typing import Callable

import httpx2
import pytest
from typesafe_sdk import TypeSafeAPIError, TypeSafeClient

from muiltilab import Ticket, TypeSafeJudge, triage

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "payout-failure.json"

CANNED_RESPONSE = {
    "model": "jev-latest",
    "answers": {
        "intent": {
            "type": "choice",
            "choice": "billing",
            "confidence": 0.91,
            "probabilities": {"billing": 0.91, "technical": 0.03, "account": 0.03, "other": 0.03},
        },
        "urgency": {
            "type": "score",
            "score": 2.0,
            "confidence": 0.84,
            "legend": {"0": "none", "1": "degraded", "2": "blocked"},
            "probabilities": {"0": 0.03, "1": 0.1, "2": 0.87},
        },
        "security_risk": {"type": "noul", "noul": 0.04},
        "wants_refund": {"type": "noul", "noul": 0.88},
    },
    "usage": {"input_tokens": 312, "output_tokens": 48},
}


def client_with(handler: Callable[[httpx2.Request], httpx2.Response]) -> TypeSafeClient:
    return TypeSafeClient(api_key="test-key", transport=httpx2.MockTransport(handler))


def test_sends_the_documented_request_and_routes_the_answer():
    sent: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        sent.append(request)
        return httpx2.Response(200, json=CANNED_RESPONSE)

    ticket = Ticket.load(EXAMPLE)
    decision, judgments = triage(ticket, TypeSafeJudge(client_with(handler)))

    assert (decision.queue, decision.priority) == ("billing-refunds", "high")
    assert judgments.wants_refund == pytest.approx(0.88)

    assert len(sent) == 1
    request = sent[0]
    assert request.method == "POST"
    assert str(request.url) == "https://api.typesafe.ai/v1/systemone"
    assert request.headers["authorization"] == "Bearer test-key"

    body = json.loads(request.content)
    assert body["model"] == "jev-latest"
    assert body["state"]["ticket"]["subject"] == ticket.subject
    assert body["state"]["customer"] == {"plan": "pro", "country": "US"}
    assert set(body["questions"]) == {"intent", "urgency", "security_risk", "wants_refund"}
    assert body["questions"]["intent"]["type"] == "choice"
    assert body["questions"]["urgency"]["criteria"] == [
        "No deadline pressure: a question, a preference, or a plan for later",
        "Degraded but usable: a workaround exists, or the impact starts within days",
        "Blocked or losing money now: work has stopped, or money or data is at risk today",
    ]


def test_service_failures_stay_separate_from_model_answers():
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(429, json={"error": "rate limited"})

    with pytest.raises(TypeSafeAPIError) as caught:
        triage(Ticket.load(EXAMPLE), TypeSafeJudge(client_with(handler)))

    assert caught.value.status == 429
