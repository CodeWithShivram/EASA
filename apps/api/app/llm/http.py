"""HTTP plumbing shared by the chat model adapters.

Clients ignore proxy environment variables (``trust_env=False``) and do not
follow redirects, so prompts containing document text go only to the
configured local server. Errors never include request or response bodies.
"""

from typing import Any

import httpx

from app.llm.base import ModelResponseError, ModelUnavailableError

# Readiness must stay fast even if the server hangs.
AVAILABILITY_TIMEOUT_SECONDS = 2.0
CONNECT_TIMEOUT_SECONDS = 5.0
# Defensive cap on reply text; max_tokens normally keeps replies far shorter.
MAX_REPLY_CHARS = 20_000


def build_client(
    base_url: str, timeout_seconds: float, transport: httpx.BaseTransport | None
) -> httpx.Client:
    return httpx.Client(
        base_url=base_url,
        timeout=httpx.Timeout(timeout_seconds, connect=CONNECT_TIMEOUT_SECONDS),
        transport=transport,
        follow_redirects=False,
        trust_env=False,
    )


def post_json(client: httpx.Client, path: str, payload: dict[str, Any]) -> Any:
    """POST and decode JSON, mapping every failure to a model error."""
    try:
        response = client.post(path, json=payload)
    except httpx.TimeoutException:
        raise ModelResponseError("the model did not answer in time") from None
    except httpx.TransportError:
        raise ModelUnavailableError("the model server cannot be reached") from None
    if response.status_code == httpx.codes.NOT_FOUND:
        raise ModelUnavailableError("the configured model is not installed")
    if response.status_code == httpx.codes.SERVICE_UNAVAILABLE:
        raise ModelUnavailableError("the model server is not ready")
    if response.status_code != httpx.codes.OK:
        raise ModelResponseError(f"the model server returned status {response.status_code}")
    try:
        return response.json()
    except ValueError:
        raise ModelResponseError("the model server returned a malformed response") from None


def count(value: Any) -> int | None:
    """A token count from a reply, or None if absent or invalid."""
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None
