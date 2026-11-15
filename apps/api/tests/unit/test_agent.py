import pytest

from app.services.agent import FINAL_ANSWER, MAX_ANSWER_CHARS, Step, parse_step, step_schema

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
