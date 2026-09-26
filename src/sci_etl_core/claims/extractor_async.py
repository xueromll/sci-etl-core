from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Sequence
from datetime import UTC, datetime

from sci_etl_core.claims.drafts import ClaimDraft
from sci_etl_core.claims.locate import locate_quote
from sci_etl_core.claims.models import Claim, EvidenceSpan, ExtractionStamp
from sci_etl_core.claims.rejections import AsyncRejectionStore, RejectedEntity, rejection_id
from sci_etl_core.llm.async_base import AsyncLLMClient
from sci_etl_core.llm.extraction_async import AsyncEntityExtractor, AsyncLLMEntityExtractor
from sci_etl_core.models import RawRecord
from sci_etl_core.parsers.base import Parser
from sci_etl_core.processors.validation import RecordValidator, Violation

_logger = logging.getLogger(__name__)


class AsyncLLMClaimExtractor(AsyncEntityExtractor[Claim]):
    """Extract claims with their evidence and provenance from a record's full text.

    One LLM call per record returns :class:`~sci_etl_core.claims.drafts.ClaimDraft`
    objects, validated against ``schema`` through an inner
    :class:`~sci_etl_core.llm.extraction_async.AsyncLLMEntityExtractor`, so
    structured output, validation, and the schema's place in the LLM cache key
    all apply. Each draft's quote is then located in the text the model was
    sent; a draft whose quote cannot be found is ungrounded, logged, and put in
    ``rejections`` with the code ``"ungrounded"``. Every other draft becomes a
    :class:`~sci_etl_core.claims.models.Claim` stamped with the model, prompt,
    schema, and library version.

    A claim cannot be built without its record, so ``requires_record`` is
    ``True``: call :meth:`extract_record`. An extractor that wraps this one
    must delegate to its ``extract_record``.
    """

    requires_record = True

    def __init__(
        self,
        llm_client: AsyncLLMClient,
        system_prompt: str,
        *,
        schema: type[ClaimDraft] = ClaimDraft,
        result_key: str = "claims",
        validator: RecordValidator | None = None,
        rejections: AsyncRejectionStore | None = None,
        min_ratio: float = 0.9,
        html_parser: Parser | None = None,
        max_chars: int = 120_000,
        max_tokens: int | None = None,
        timeout: int = 120,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        """Configure the extractor.

        ``validator`` sees each draft as a ``dict`` after the schema check.
        ``min_ratio`` is the share of a quote's characters that must be found
        in one or two adjacent sentences of the text for a fuzzy match. The
        other arguments are those of
        :class:`~sci_etl_core.llm.extraction_async.AsyncLLMEntityExtractor`.

        Raises:
            ValueError: ``min_ratio`` is not between 0 and 1.
        """
        if not 0.0 <= min_ratio <= 1.0:
            raise ValueError("min_ratio must be between 0 and 1")
        self._drafts = AsyncLLMEntityExtractor(
            llm_client,
            system_prompt,
            schema=schema,
            html_parser=html_parser,
            result_key=result_key,
            max_chars=max_chars,
            timeout=timeout,
            max_tokens=max_tokens,
            validator=validator,
            rejections=rejections,
            label_field="subject",
            now=now,
        )
        self._rejections = rejections
        self._min_ratio = min_ratio
        self._now = now or (lambda: datetime.now(UTC))

    @property
    def stamp(self) -> ExtractionStamp:
        """What produces this extractor's claims."""
        return self._drafts.stamp

    @property
    def answer_schema(self) -> dict[str, object] | None:
        """The JSON Schema requested for the whole answer."""
        return self._drafts.answer_schema

    async def extract(self, text: str | bytes) -> Sequence[Claim]:
        """Refuse: a claim needs its record.

        Raises:
            TypeError: Always; call :meth:`extract_record` instead.
        """
        raise TypeError("AsyncLLMClaimExtractor needs the record; call extract_record(record, text)")

    async def extract_record(self, record: RawRecord, text: str | bytes) -> Sequence[Claim]:
        """Extract the record's grounded claims.

        Raises:
            LLMError: As for
                :meth:`~sci_etl_core.llm.extraction_async.AsyncLLMEntityExtractor.extract_record`.
            ClaimStoreError: The rejection store could not be written.
        """
        drafts = await self._drafts.extract_record(record, text)
        prepared = await asyncio.to_thread(self._drafts.prepare, text)
        stamp = self.stamp
        claims: list[Claim] = []
        ungrounded: list[ClaimDraft] = []
        for draft in drafts:
            located = locate_quote(prepared, draft.quote, min_ratio=self._min_ratio)
            if located is None:
                _logger.info("Claim rejected as ungrounded: %r (quote not found in the text)", draft.subject)
                ungrounded.append(draft)
                continue
            start, end, _ratio = located
            span = EvidenceSpan(record_id=record.record_id, start=start, end=end, quote=draft.quote)
            claims.append(Claim.from_draft(draft, span=span, stamp=stamp))
        if ungrounded and self._rejections is not None:
            await self._store_ungrounded(self._rejections, record.record_id, ungrounded, stamp)
        return claims

    async def _store_ungrounded(
        self, store: AsyncRejectionStore, record_id: str, drafts: list[ClaimDraft], stamp: ExtractionStamp
    ) -> None:
        violation = Violation(
            code="ungrounded", field="quote", severity="error", message="The quote was not found in the text"
        )
        created_at = self._now().isoformat()
        entries = []
        for draft in drafts:
            entity = draft.model_dump(mode="json")
            entries.append(
                RejectedEntity(
                    entry_id=rejection_id(record_id, entity, (violation,), stamp),
                    record_id=record_id,
                    entity=entity,
                    violations=(violation,),
                    stamp=stamp,
                    quote=draft.quote,
                    created_at=created_at,
                )
            )
        await store.put(entries)
