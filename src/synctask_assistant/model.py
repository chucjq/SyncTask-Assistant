from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Protocol

from .config import ModelSettings

THINK_BLOCK = re.compile(r"<think>.*?</think>|<\|channel>.*?<channel\|>", re.S)
log = logging.getLogger("synctask_assistant")


class ModelError(RuntimeError):
    """The model could not be reached or returned an error. Nothing was run."""


@dataclass(frozen=True)
class ChatResult:
    text: str
    reasoning_chars: int = 0
    eval_count: int | None = None


class Chat(Protocol):
    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        format_schema: dict[str, Any] | None = None,
        num_predict: int | None = None,
        think: bool | None = None,
    ) -> ChatResult: ...


def strip_reasoning(text: str) -> str:
    """Remove reasoning blocks some models print before the answer."""
    if "</think>" in text:
        text = text.rsplit("</think>", 1)[1]
    return THINK_BLOCK.sub("", text).strip()


@dataclass
class OllamaChat:
    settings: ModelSettings
    _client: Any = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self._client is None:
            import ollama

            self._client = ollama.Client(host=self.settings.host, timeout=self.settings.timeout)

    def options(self, num_predict: int | None) -> dict[str, Any]:
        options: dict[str, Any] = {"temperature": self.settings.temperature}
        if self.settings.top_p is not None:
            options["top_p"] = self.settings.top_p
        if num_predict is not None:
            options["num_predict"] = num_predict
        if self.settings.num_ctx is not None:
            options["num_ctx"] = self.settings.num_ctx
        return options

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        format_schema: dict[str, Any] | None = None,
        num_predict: int | None = None,
        think: bool | None = None,
    ) -> ChatResult:
        wanted = self.settings.think if think is None else think
        extra: dict[str, Any] = {} if wanted is None else {"think": wanted}
        try:
            response = self._client.chat(
                model=self.settings.model,
                messages=messages,
                format=format_schema,
                options=self.options(num_predict),
                **extra,
            )
        except Exception as error:
            raise ModelError(f"The model call failed: {type(error).__name__}.") from error
        raw = response["message"]["content"] or ""
        thinking = response["message"].get("thinking") or ""
        text = strip_reasoning(raw)
        reasoning_chars = len(thinking) + (len(raw) - len(text))
        result = ChatResult(
            text=text,
            reasoning_chars=reasoning_chars,
            eval_count=response.get("eval_count"),
        )
        if not text:
            log.warning(
                "model returned no text: raw_chars=%d reasoning_chars=%d eval_count=%s "
                "num_predict=%s",
                len(raw), reasoning_chars, result.eval_count, num_predict,
            )
        return result
