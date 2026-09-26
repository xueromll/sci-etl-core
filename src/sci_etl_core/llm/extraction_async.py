from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, ClassVar, Generic, TypeVar, overload

from pydantic import BaseModel, ValidationError

from sci_etl_core._user_agent import DEFAULT_USER_AGENT
from sci_etl_core.claims.models import ExtractionStamp, content_hash
from sci_etl_core.claims.rejections import AsyncRejectionStore, RejectedEntity, rejection_id
from sci_etl_core.exceptions import LLMError
from sci_etl_core.llm._chunking import truncate_to_tokens
from sci_etl_core.llm.async_base import AsyncLLMClient
from sci_etl_core.models import RawRecord
from sci_etl_core.parsers.base import Parser
from sci_etl_core.processors.validation import ValidationResult, Violation

if TYPE_CHECKING:
    from sci_etl_core.processors.validation import RecordValidator

E = TypeVar("E", covariant=True)
M = TypeVar("M", bound=BaseModel)

_logger = logging.getLogger(__name__)


class AsyncEntityExtractor(ABC, Generic[E]):
    """Contract for turning a record's full text into structured entities.

    ``E`` is the entity type: ``dict[str, Any]`` for untyped extraction, or a
    Pydantic model or dataclass for typed extraction. The pipeline calls
    :meth:`extract_record`, whose default calls :meth:`extract`, so an
    extractor that overrides only :meth:`extract` works unchanged.

    An extractor that cannot work without the record, such as
    :class:`~sci_etl_core.claims.extractor_async.AsyncLLMClaimExtractor`, sets
    ``requires_record`` to ``True`` and overrides :meth:`extract_record`. An
    extractor that wraps another calls the inner one's :meth:`extract_record`
    and copies its ``requires_record``.
    """

    requires_record: ClassVar[bool] = False

    @abstractmethod
    async def extract(self, text: str | bytes) -> Sequence[E]:
        """Extract structured entities from ``text`` alone.

        An empty result means the text holds no entities, and the pipeline
        marks the record processed. Raising any exception instead fails the
        record, which stays unmarked and is retried on the next run.

        Raises:
            TypeError: ``requires_record`` is ``True``; call
                :meth:`extract_record` instead.
        """

    async def extract_record(self, record: RawRecord, text: str | bytes) -> Sequence[E]:
        """Extract entities from ``text``, knowing which record it belongs to.

        This is the entry point for every caller, the pipeline and wrapping
        extractors included. The default ignores ``record`` and calls
        :meth:`extract`.
        """
        return await self.extract(text)


def entity_list_schema(entity_schema: Any, result_key: str) -> dict[str, Any]:
    """Return the JSON Schema of an answer holding a list of entities under ``result_key``.

    ``entity_schema`` is a Pydantic model class or a JSON Schema mapping for
    one entity. Its ``$defs`` move to the root so that every ``$ref`` still
    resolves.
    """
    is_model = isinstance(entity_schema, type) and issubclass(entity_schema, BaseModel)
    item = dict(entity_schema.model_json_schema() if is_model else entity_schema)
    definitions = item.pop("$defs", None)
    answer: dict[str, Any] = {
        "type": "object",
        "properties": {result_key: {"type": "array", "items": item}},
        "required": [result_key],
        "additionalProperties": False,
    }
    if definitions:
        answer["$defs"] = definitions
    return answer


class AsyncLLMEntityExtractor(AsyncEntityExtractor[E]):
    """Extract entities from full text with one LLM call per record.

    Text that starts with markup is stripped with ``html_parser``. The text is
    then truncated to ``max_tokens`` tokens when that is set and ``tiktoken``
    is installed, or to ``max_chars`` characters otherwise.

    Without ``schema``, entities are the ``dict`` objects the model returned.
    With a Pydantic model class as ``schema``, the request asks for JSON-schema
    structured output through
    :meth:`~sci_etl_core.llm.async_base.AsyncLLMClient.complete_structured`,
    every entity is validated against the model, and entities are model
    instances. A client that cannot request structured output answers in JSON
    mode, and the validation still applies, so the system prompt should still
    describe the fields.
    """

    @overload
    def __init__(
        self: AsyncLLMEntityExtractor[dict[str, Any]],
        llm_client: AsyncLLMClient,
        system_prompt: str,
        *,
        schema: None = None,
        html_parser: Parser | None = None,
        result_key: str = "items",
        max_chars: int = 120_000,
        timeout: int = 120,
        max_tokens: int | None = None,
        encoding_name: str = "cl100k_base",
        validator: RecordValidator | None = None,
        rejections: AsyncRejectionStore | None = None,
        label_field: str | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None: ...

    @overload
    def __init__(
        self: AsyncLLMEntityExtractor[M],
        llm_client: AsyncLLMClient,
        system_prompt: str,
        *,
        schema: type[M],
        html_parser: Parser | None = None,
        result_key: str = "items",
        max_chars: int = 120_000,
        timeout: int = 120,
        max_tokens: int | None = None,
        encoding_name: str = "cl100k_base",
        validator: RecordValidator | None = None,
        rejections: AsyncRejectionStore | None = None,
        label_field: str | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None: ...

    def __init__(
        self,
        llm_client: AsyncLLMClient,
        system_prompt: str,
        *,
        schema: type[BaseModel] | None = None,
        html_parser: Parser | None = None,
        result_key: str = "items",
        max_chars: int = 120_000,
        timeout: int = 120,
        max_tokens: int | None = None,
        encoding_name: str = "cl100k_base",
        validator: RecordValidator | None = None,
        rejections: AsyncRejectionStore | None = None,
        label_field: str | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        """Configure the extractor.

        An entity that fails ``schema`` validation, or that ``validator``
        rejects, is dropped and logged at ``INFO`` as
        ``Entity rejected by validation: <label> (<reasons>)``. The label is
        the entity's ``label_field`` value when that is given, and its
        position in the response otherwise. ``validator`` sees the entity as a
        ``dict``, after the schema check when there is one. With
        ``rejections``, each rejected entity is also stored there with its
        :class:`~sci_etl_core.processors.validation.Violation` list and the
        :attr:`stamp`, at the time ``now`` returns. A record whose every
        entity is rejected exports nothing and is still marked processed, as
        for a response with no entities.
        """
        self._llm_client = llm_client
        self._system_prompt = system_prompt
        self._schema = schema
        self._html_parser = html_parser
        self._result_key = result_key
        self._max_chars = max_chars
        self._timeout = timeout
        self._max_tokens = max_tokens
        self._encoding_name = encoding_name
        self._validator = validator
        self._rejections = rejections
        self._label_field = label_field
        self._now = now or (lambda: datetime.now(UTC))
        self._answer_schema = None if schema is None else entity_list_schema(schema, result_key)

    @property
    def answer_schema(self) -> dict[str, Any] | None:
        """The JSON Schema requested for the whole answer, or ``None`` without ``schema``."""
        return self._answer_schema

    @property
    def stamp(self) -> ExtractionStamp:
        """What produces this extractor's entities: model, prompt and schema hashes, and library version."""
        return ExtractionStamp(
            model=_model_name(self._llm_client),
            prompt_hash=content_hash(self._system_prompt),
            schema_hash="" if self._answer_schema is None else content_hash(self._answer_schema),
            extractor_version=DEFAULT_USER_AGENT,
        )

    async def extract(self, text: str | bytes) -> Sequence[E]:
        """Extract entities from ``text`` with a single LLM call.

        Rejected entities are stored with an empty ``record_id``; the pipeline
        calls :meth:`extract_record`, which stores the record's id.
        """
        return await self._extract("", text)

    async def extract_record(self, record: RawRecord, text: str | bytes) -> Sequence[E]:
        """Extract entities from ``text`` and file any rejections under ``record``'s id.

        The entity list is read from ``result_key``, or from the only value
        when the response has exactly one key. ``null`` reads as no entities
        and a lone object as a one-entity list. Preparing the text runs in a
        worker thread, since stripping and token counting are CPU-bound.

        Raises:
            LLMError: The completion failed; the response holds no entity list,
                because it is empty or has several keys and none is
                ``result_key``; or the entity list is not a list of objects.
                The error propagates instead of reading as "no entities", so
                the pipeline leaves the record unmarked and retries it on the
                next run. A rejected response is reported through
                :meth:`~sci_etl_core.llm.async_base.AsyncLLMClient.invalidate`,
                so a caching client does not replay it.
            ClaimStoreError: The rejection store could not be written.
        """
        return await self._extract(record.record_id, text)

    def prepare(self, text: str | bytes) -> str:
        """Return the text the model is sent: markup stripped, then truncated.

        Bytes are decoded as UTF-8, ignoring undecodable bytes. Text whose
        first 200 characters start with ``<`` is parsed with ``html_parser``,
        by default an :class:`~sci_etl_core.parsers.html.HtmlTextParser`,
        which needs the ``html`` extra.
        Preparing already prepared plain text returns it unchanged.
        """
        cleaned = text.decode("utf-8", errors="ignore") if isinstance(text, bytes) else text
        if cleaned[:200].lstrip().startswith("<"):
            cleaned = self._markup_parser().extract_text(cleaned.encode("utf-8"))
        return self._truncate(cleaned)

    def _markup_parser(self) -> Parser:
        if self._html_parser is None:
            from sci_etl_core.parsers.html import HtmlTextParser

            self._html_parser = HtmlTextParser()
        return self._html_parser

    async def _extract(self, record_id: str, text: str | bytes) -> Sequence[E]:
        prepared = await asyncio.to_thread(self.prepare, text)
        result = await self._complete(prepared)
        try:
            entities = self._entity_list(result)
        except LLMError:
            await self._invalidate(prepared)
            raise
        return await self._screened(record_id, entities)

    async def _complete(self, prepared: str) -> Any:
        if self._answer_schema is None:
            return await self._llm_client.complete_json(self._system_prompt, prepared, self._timeout)
        return await self._llm_client.complete_structured(
            self._system_prompt, prepared, self._answer_schema, self._timeout
        )

    async def _invalidate(self, prepared: str) -> None:
        if self._answer_schema is None:
            await self._llm_client.invalidate(self._system_prompt, prepared)
        else:
            await self._llm_client.invalidate(self._system_prompt, prepared, schema=self._answer_schema)

    def _entity_list(self, result: Any) -> list[dict[str, Any]]:
        if not isinstance(result, dict):
            raise LLMError(f"LLM returned {type(result).__name__}, not a JSON object")
        if self._result_key in result:
            return self._entities(result[self._result_key])
        if len(result) == 1:
            return self._entities(next(iter(result.values())))
        raise LLMError(f"LLM response has no {self._result_key!r} key and {len(result)} keys instead of one")

    async def _screened(self, record_id: str, entities: list[dict[str, Any]]) -> list[Any]:
        accepted: list[Any] = []
        rejected: list[tuple[dict[str, Any], ValidationResult]] = []
        for position, entity in enumerate(entities):
            kept, result = self._screen(entity)
            if result.ok:
                accepted.append(kept)
                continue
            reasons = "; ".join(violation.message for violation in result.violations)
            _logger.info("Entity rejected by validation: %s (%s)", self._label(entity, position), reasons)
            rejected.append((entity, result))
        if rejected and self._rejections is not None:
            await self._store_rejections(self._rejections, record_id, rejected)
        return accepted

    def _screen(self, entity: dict[str, Any]) -> tuple[Any, ValidationResult]:
        kept: Any = entity
        checked = entity
        if self._schema is not None:
            try:
                kept = self._schema.model_validate(entity)
            except ValidationError as error:
                return entity, _schema_violations(error)
            checked = kept.model_dump()
        if self._validator is None:
            return kept, ValidationResult()
        return kept, self._validator.validate(checked)

    async def _store_rejections(
        self,
        store: AsyncRejectionStore,
        record_id: str,
        rejected: list[tuple[dict[str, Any], ValidationResult]],
    ) -> None:
        stamp = self.stamp
        created_at = self._now().isoformat()
        await store.put(
            [
                RejectedEntity(
                    entry_id=rejection_id(record_id, entity, result.violations, stamp),
                    record_id=record_id,
                    entity=entity,
                    violations=result.violations,
                    stamp=stamp,
                    quote=str(entity.get("quote", "")),
                    created_at=created_at,
                )
                for entity, result in rejected
            ]
        )

    def _label(self, entity: dict[str, Any], position: int) -> str:
        if self._label_field is None:
            return f"entity {position}"
        return repr(entity.get(self._label_field))

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


def _model_name(client: AsyncLLMClient) -> str:
    name = getattr(client, "model", "")
    return name if isinstance(name, str) else ""


def _schema_violations(error: ValidationError) -> ValidationResult:
    return ValidationResult(
        violations=tuple(
            Violation(
                code="schema",
                field=".".join(str(part) for part in detail["loc"]) or None,
                severity="error",
                message=f"{'.'.join(str(part) for part in detail['loc']) or 'entity'}: {detail['msg']}",
            )
            for detail in error.errors(include_url=False, include_input=False)
        )
    )
