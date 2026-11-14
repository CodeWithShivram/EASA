import asyncio
import json

from starlette.types import Message, Receive, Scope, Send

from app.core.middleware import BodySizeLimitMiddleware


async def _never_called(scope: Scope, receive: Receive, send: Send) -> None:
    raise AssertionError("the app must not be reached")


def _call(content_length: bytes) -> list[Message]:
    sent: list[Message] = []

    async def receive() -> Message:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: Message) -> None:
        sent.append(message)

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/",
        "headers": [(b"content-length", content_length)],
    }
    asyncio.run(BodySizeLimitMiddleware(_never_called, max_body_bytes=100)(scope, receive, send))
    return sent


def test_non_ascii_digit_content_length_is_a_bad_request() -> None:
    # "\u00b2".isdigit() is True but int() rejects it; this used to raise (500).
    sent = _call("\u00b2".encode())

    assert sent[0]["status"] == 400
    assert json.loads(sent[1]["body"])["error"]["code"] == "invalid_content_length"
