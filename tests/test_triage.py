import json
from dataclasses import fields
from pathlib import Path

import pytest
from typesafe_sdk import (
    Choice,
    ChoiceAnswer,
    Noul,
    NoulAnswer,
    Score,
    ScoreAnswer,
    SystemOneResponse,
    Usage,
)

from muiltilab import AnswerShapeError, Judgments, ScriptedJudge, Ticket, to_judgments, triage
from muiltilab.questions import URGENCY_LEVELS, build_questions
from muiltilab.triage import EXIT_OK, main

EXAMPLES = sorted(Path(__file__).resolve().parents[1].joinpath("examples").glob("*.json"))

EXPECTED_QUEUES = {
    "payout-failure.json": ("billing-refunds", "high"),
    "leaked-api-key.json": ("security", "high"),
    "vague.json": ("human", "normal"),
}


def response(**answers):
    return SystemOneResponse(
        model="jev-latest",
        usage=Usage(input_tokens=1, output_tokens=1),
        answers=answers,
    )


def test_question_set_covers_every_answer_the_policy_reads():
    questions = build_questions()
    assert set(questions) == {"intent", "urgency", "security_risk", "wants_refund"}
    assert isinstance(questions["intent"], Choice)
    assert isinstance(questions["urgency"], Score)
    assert isinstance(questions["security_risk"], Noul)
    assert isinstance(questions["wants_refund"], Noul)


def test_choice_offers_a_no_match_option():
    criteria = build_questions()["intent"].criteria
    assert "other" in criteria
    assert all(description for description in criteria.values())


def test_score_levels_stand_on_their_own():
    criteria = build_questions()["urgency"].criteria
    assert list(criteria) == list(URGENCY_LEVELS)
    assert len(criteria) >= 2


def test_request_body_matches_the_documented_contract():
    body = {key: question.model_dump() for key, question in build_questions().items()}
    round_tripped = json.loads(json.dumps(body))
    assert round_tripped["intent"]["type"] == "choice"
    assert set(round_tripped["intent"]["criteria"]) == {"billing", "technical", "account", "other"}
    assert round_tripped["urgency"]["type"] == "score"
    assert round_tripped["security_risk"]["type"] == "noul"
    assert set(round_tripped["security_risk"]["criteria"]) == {"true", "false"}


def test_answers_map_onto_judgments():
    judgments = to_judgments(
        response(
            intent=ChoiceAnswer(choice="billing", confidence=0.91, probabilities={"billing": 0.91, "other": 0.09}),
            urgency=ScoreAnswer(score=2.0, confidence=0.84, legend={0: "a", 1: "b", 2: "c"}, probabilities={0: 0.03, 1: 0.1, 2: 0.87}),
            security_risk=NoulAnswer(noul=0.04),
            wants_refund=NoulAnswer(noul=0.88),
        )
    )
    assert judgments.intent == "billing"
    assert judgments.intent_confidence == pytest.approx(0.91)
    assert judgments.urgency == pytest.approx(2.0)
    assert judgments.security_risk == pytest.approx(0.04)
    assert judgments.wants_refund == pytest.approx(0.88)


def test_unexpected_answer_shape_is_not_silently_accepted():
    with pytest.raises(AnswerShapeError, match="unexpected answer shape"):
        to_judgments(
            response(
                intent=NoulAnswer(noul=0.5),
                urgency=ScoreAnswer(score=1.0, confidence=0.5, legend={0: "a", 1: "b"}, probabilities={0: 0.5, 1: 0.5}),
                security_risk=NoulAnswer(noul=0.1),
                wants_refund=NoulAnswer(noul=0.1),
            )
        )


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.stem)
def test_example_tickets_route_as_expected(path):
    ticket = Ticket.load(path)
    decision, _ = triage(ticket, ScriptedJudge(ticket.offline))
    assert (decision.queue, decision.priority) == EXPECTED_QUEUES[path.name]


def test_offline_judgments_supply_every_field_the_policy_reads():
    expected = {field.name for field in fields(Judgments)}
    for path in EXAMPLES:
        assert set(Ticket.load(path).offline_judgments) == expected


def test_cli_runs_end_to_end_offline(capsys):
    path = next(p for p in EXAMPLES if p.name == "payout-failure.json")
    exit_code = main([str(path), "--offline", "--json"])
    assert exit_code == EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    assert payload["decision"]["queue"] == "billing-refunds"
    assert payload["judgments"]["intent"] == "billing"


def test_offline_mode_requires_offline_judgments(tmp_path):
    path = tmp_path / "t.json"
    path.write_text(
        json.dumps({"subject": "s", "body": "b", "plan": "free", "country": "US"}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="no offline_judgments"):
        Ticket.load(path).offline
