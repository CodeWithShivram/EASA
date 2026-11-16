import pytest

from app.services.agent import (
    FINAL_ANSWER,
    MAX_ANSWER_CHARS,
    Step,
    confirmation_message,
    drop_unstated,
    parse_step,
    step_schema,
    unsupported_claim,
)
from app.tools.support import CreateDraftTicket, GetTicket

TOOLS = [
    {
        "name": "get_ticket",
        "description": "Show a ticket.",
        "consequential": False,
        "input_schema": {
            "type": "object",
            "properties": {"number": {"type": "integer", "minimum": 1}},
            "required": ["number"],
            "additionalProperties": False,
        },
    },
    {
        "name": "create_draft_ticket",
        "description": "Create a draft.",
        "consequential": True,
        "input_schema": {
            "$defs": {"TicketPriority": {"enum": ["low", "normal", "high"], "type": "string"}},
            "type": "object",
            "properties": {"priority": {"$ref": "#/$defs/TicketPriority"}},
            "additionalProperties": False,
        },
    },
]


def test_step_schema_allows_only_permitted_tools_and_a_final_answer() -> None:
    schema = step_schema(TOOLS)

    actions = [branch["properties"]["action"]["enum"] for branch in schema["anyOf"]]
    assert actions == [["get_ticket"], ["create_draft_ticket"], [FINAL_ANSWER]]
    assert all(branch["additionalProperties"] is False for branch in schema["anyOf"])
    # Definitions are hoisted to the root so "#/$defs/..." references resolve.
    assert schema["$defs"] == {
        "TicketPriority": {"enum": ["low", "normal", "high"], "type": "string"}
    }
    assert "$defs" not in schema["anyOf"][1]["properties"]["arguments"]
    assert "$defs" in TOOLS[1]["input_schema"]  # the tool description is not modified


def test_final_only_and_toolless_schemas_allow_only_an_answer() -> None:
    for schema in (step_schema(TOOLS, final_only=True), step_schema([])):
        assert "anyOf" not in schema
        assert schema["properties"]["action"]["enum"] == [FINAL_ANSWER]
        assert schema["properties"]["answer"]["maxLength"] == MAX_ANSWER_CHARS


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ('{"action": "get_ticket", "arguments": {"number": 3}}', Step("get_ticket", {"number": 3})),
        ('{"action": "get_ticket"}', Step("get_ticket", {})),
        ('{"action": "final_answer", "answer": "  Done. "}', Step(FINAL_ANSWER, answer="Done.")),
        ("not json", None),
        ("[1, 2]", None),
        ('{"tool": "get_ticket"}', None),
        ('{"action": "get_ticket", "arguments": [3]}', None),
        ('{"action": "final_answer", "answer": "  "}', None),
        ('{"action": "final_answer"}', None),
    ],
)
def test_parse_step(text: str, expected: Step | None) -> None:
    assert parse_step(text) == expected


def test_long_answers_are_cut() -> None:
    step = parse_step('{"action": "final_answer", "answer": "' + "x" * 5000 + '"}')

    assert step is not None
    assert len(step.answer) == MAX_ANSWER_CHARS


def test_confirmation_message_states_exactly_what_would_run() -> None:
    message = confirmation_message(
        "create_draft_ticket", {"title": "HACKED", "description": "x", "priority": "high"}
    )

    assert message == (
        'Nothing has been done yet. Confirm to run create_draft_ticket with title="HACKED", '
        'description="x", priority="high", or cancel.'
    )


TICKET_1 = '{"outcome": "succeeded", "output": {"number": 1, "status": "open"}}'
TICKET_5 = '{"outcome": "succeeded", "output": {"number": 5, "status": "closed"}}'


@pytest.mark.parametrize(
    ("answer", "evidence", "expected"),
    [
        # Seen in the P5-M5 evaluation: nothing was changed.
        ("Ticket 1 has been closed.", TICKET_1, True),
        ("I have sent the email to the IT team.", "", True),
        ("Your ticket was successfully deleted.", "", True),
        ("The priority is now changed to high.", "", True),
        ("Ticket 3 is now escalated.", "", True),
        ("I've CREATED a ticket for you.", "", True),
        # Reports of states that a tool result shows are kept.
        ("Ticket 5 was closed last week.", TICKET_5, False),
        ("Yes, your ticket 4 has been resolved.", '{"status": "resolved"}', False),
        # Ordinary answers are not claims.
        ("Expense claims must be submitted within 30 days.", "", False),
        ("Ticket 6 was not found.", "", False),
        # Seen for a missing ticket in the P5-M5 follow-up run: speculation, not a claim.
        ("I couldn't find ticket 6. It might not exist or it may have been deleted.", "", False),
        ("It could have been closed by IT.", "", False),
        ("I cannot close tickets.", "", False),
        ("The printer has moved to room 2.14.", "", False),
    ],
)
def test_unsupported_claim(answer: str, evidence: str, expected: bool) -> None:
    assert unsupported_claim(answer, evidence) is expected


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("My headset does not work, open a ticket.", {"title": "Headset broken"}),
        (
            "File a ticket with HIGH priority: no keyboard.",
            {"title": "Headset broken", "priority": "high"},
        ),
        ("This is highly annoying, open a ticket.", {"title": "Headset broken"}),  # word match only
    ],
)
def test_user_only_fields_need_the_users_words(message: str, expected: dict[str, str]) -> None:
    proposed = {"title": "Headset broken", "priority": "high"}

    assert drop_unstated(CreateDraftTicket(), proposed, message) == expected


def test_tools_without_user_only_fields_keep_every_argument() -> None:
    assert drop_unstated(GetTicket(), {"number": 3}, "ticket 3") == {"number": 3}
    assert drop_unstated(None, {"x": 1}, "") == {"x": 1}
