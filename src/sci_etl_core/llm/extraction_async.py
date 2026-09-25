from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from sci_etl_core._deprecation import warn_logger_argument
from sci_etl_core.exceptions import LLMError
from sci_etl_core.llm._chunking import truncate_to_tokens
from sci_etl_core.llm.async_base import AsyncLLMClient
from sci_etl_core.parsers.base import Parser
from sci_etl_core.parsers.html import HtmlTextParser

if TYPE_CHECKING:
    from sci_etl_core.processors.validation import RecordValidator


class AsyncEntityExtractor(ABC):
    """Contract for turning a record's full text into structured entities."""

    @abstractmethod
    async def extract(self, text: str | bytes) -> list[dict[str, Any]]:
        """Extract structured entities from raw text.

        An empty list means the text holds no entities, and the pipeline marks
        the record processed. Raising any exception instead fails the record,
        which stays unmarked and is retried on the next run.
        """


class AsyncLLMEntityExtractor(AsyncEntityExtractor):
    """Extract entities from full text with one JSON-mode LLM call per record.

    Text that starts with markup is stripped with ``html_parser``. The text is
    then truncated to ``max_tokens`` tokens when that is set and ``tiktoken``
    is installed, or to ``max_chars`` characters otherwise.
    """

    def __init__(
        self,
        llm_client: AsyncLLMClient,
        system_prompt: str,
        html_parser: Parser | None = None,
        result_key: str = "items",
        max_chars: int = 120_000,
        timeout: int = 120,
        max_tokens: int | None = None,
        encoding_name: str = "cl100k_base",
        validator: RecordValidator | None = None,
        logger: Callable[[str], None] | None = None,
        label_field: str | None = None,
    ) -> None:
        """Configure the extractor.

        With a ``validator``, each extracted entity is checked before it is
        returned, and an entity the validator rejects is dropped and logged as
        ``Entity rejected by validation: <label>``. The label is the entity's
        ``label_field`` value when that is given, and its position in the
        response otherwise. A record whose every entity is rejected exports
        nothing and is still marked processed, as for a response with no
        entities.
        """
        self._validator = validator
        warn_logger_argument("AsyncLLMEntityExtractor", logger)
        self._log = logger or (lambda _msg: None)
        self._label_field = label_field
        self._llm_client = llm_client
        self._system_prompt = system_prompt
        self._html_parser = html_parser or HtmlTextParser()
        self._result_key = result_key
        self._max_chars = max_chars
        self._timeout = timeout
        self._max_tokens = max_tokens
        self._encoding_name = encoding_name

    async def extract(self, text: str | bytes) -> list[dict[str, Any]]:
        """Extract entities from ``text`` with a single LLM call.

        The entity list is read from ``result_key``, or from the only value when
        the response has exactly one key; any other shape yields no entities.
        ``null`` reads as no entities and a lone object as a one-entity list.
        HTML stripping and truncation run in a worker thread, since both are
        CPU-bound and token counting may load encoding data on first use.

        Raises:
            LLMError: The completion failed, or the entity list is not a list of
                objects (for example a string or a list of strings). The error
                propagates instead of reading as "no entities", so the pipeline
                leaves the record unmarked and retries it on the next run rather
                than recording it as processed with nothing exported.
        """
        prepared = await asyncio.to_thread(self._prepare, text)
        result = await self._llm_client.complete_json(self._system_prompt, prepared, self._timeout)
        if not isinstance(result, dict):
            raise LLMError(f"LLM returned {type(result).__name__}, not a JSON object")
        if self._result_key in result:
            return self._validated(self._entities(result[self._result_key]))
        if len(result) == 1:
            return self._validated(self._entities(next(iter(result.values()))))
        return []

    def _validated(self, entities: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if self._validator is None:
            return entities
        accepted: list[dict[str, Any]] = []
        for position, entity in enumerate(entities):
            if self._validator.is_valid(entity):
                accepted.append(entity)
            else:
                self._log(f"Entity rejected by validation: {self._label(entity, position)}")
        return accepted

    def _label(self, entity: dict[str, Any], position: int) -> str:
        if self._label_field is None:
            return f"entity {position}"
        return repr(entity.get(self._label_field))

    def _prepare(self, text: str | bytes) -> str:
        cleaned = text.decode("utf-8", errors="ignore") if isinstance(text, bytes) else text
        if cleaned[:200].lstrip().startswith("<"):
            cleaned = self._html_parser.extract_text(cleaned.encode("utf-8"))
        return self._truncate(cleaned)

    @staticmethod
    def _entities(value: Any) -> list[dict[str, Any]]:
        if value is None:
            return []
        if isinstance(value, dict):
            return [value]
        if isinstance(value, list) and all(isinstance(item, dict) for item in value):
            return list(value)
        raise LLMError(
            f"LLM returned {type(value).__name__} where a list of entity objects was expected"
        )

    def _truncate(self, text: str) -> str:
        """Truncate by token count when configured, else by character count.

        Token-aware truncation requires ``tiktoken``; when it is absent the
        character cap (``max_chars``) is used instead.
        """
        if self._max_tokens is not None:
            truncated = truncate_to_tokens(text, self._max_tokens, self._encoding_name)
            if truncated is not None:
                return truncated
        return text[: self._max_chars]
