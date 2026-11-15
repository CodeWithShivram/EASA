"""Build the configured chat model."""

from app.core.config import Settings
from app.llm.base import ChatModel
from app.llm.fake import FakeChatModel, extractive_reply
from app.llm.llamacpp import LlamaCppChatModel
from app.llm.ollama import OllamaChatModel


def build_chat_model(settings: Settings) -> ChatModel | None:
    """None when answer generation is disabled (``model_provider = "none"``)."""
    if settings.model_provider == "fake":
        # Quotes the first retrieved source, so answers can be tried without a model.
        return FakeChatModel(extractive_reply)
    if settings.model_provider == "llamacpp":
        return LlamaCppChatModel(
            settings.llamacpp_base_url,
            settings.model_name,
            timeout_seconds=settings.model_timeout_seconds,
        )
    if settings.model_provider == "ollama":
        return OllamaChatModel(
            settings.ollama_base_url,
            settings.model_name,
            timeout_seconds=settings.model_timeout_seconds,
        )
    return None
