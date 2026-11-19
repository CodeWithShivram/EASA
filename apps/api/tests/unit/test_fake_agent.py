"""The development fake model's scripted agent (P8-M3): lets every flow run without a model."""

import json

import pytest

from app.llm.base import ChatMessage
from app.llm.fake import development_reply

AGENT_SYSTEM = ChatMessage("system", "You are a company support assistant that can use tools.")


def first_step(request: str) -> dict[str, object]:
    step: dict[str, object] = json.loads(
        development_reply([AGENT_SYSTEM, ChatMessage("user", request)])
    )
    return step


def test_a_ticket_request_becomes_a_draft_proposal() -> None:
    assert first_step("Open a ticket: my headset does not work.") == {
        "action": "create_draft_ticket",
        "arguments": {
            "title": "my headset does not work.",
            "description": "Open a ticket: my headset does not work.",
        },
    }
    short = first_step("Open a ticket: pc")
    assert short["arguments"] == {"title": "Support request", "description": "Open a ticket: pc"}


@pytest.mark.parametrize(
    ("request_text", "expected"),
    [
        (
            "What is the status of my ticket 2?",
            {"action": "get_ticket_status", "arguments": {"number": 2}},
        ),
        (
            "How many leave days do I get?",
            {
                "action": "search_knowledge_base",
                "arguments": {"query": "How many leave days do I get?"},
            },
        ),
    ],
)
def test_other_requests_look_up_a_ticket_or_search(
    request_text: str, expected: dict[str, object]
) -> None:
    assert first_step(request_text) == expected


@pytest.mark.parametrize(
    ("result", "answer"),
    [
        (
            '{"outcome": "succeeded", "output": {"number": 2, "status": "in_progress"}}',
            "The ticket's status is in progress.",
        ),
        ('{"outcome": "succeeded", "output": {"results": []}}', "Here is what I found."),
        (
            '{"outcome": "failed", "message": "Ticket 9 was not found."}',
            "I could not complete that request.",
        ),
    ],
)
def test_after_a_tool_result_it_answers(result: str, answer: str) -> None:
    messages = [
        AGENT_SYSTEM,
        ChatMessage("user", "Ticket 2?"),
        ChatMessage("assistant", "{}"),
        ChatMessage("user", f"<tool_result>{result}</tool_result>"),
    ]

    assert json.loads(development_reply(messages)) == {"action": "final_answer", "answer": answer}


def test_other_prompts_get_the_extractive_reply() -> None:
    sources = '<source id="S1" document="a.txt">\nLeave is 25 days. More text.\n</source>'
    messages = [ChatMessage("system", "Answer."), ChatMessage("user", sources)]

    assert development_reply(messages) == "Leave is 25 days. [S1]"
