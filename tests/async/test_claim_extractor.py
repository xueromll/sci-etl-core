from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from sci_etl_core.claims.exporter_async import AsyncClaimStoreExporter
from sci_etl_core.claims.extractor_async import AsyncLLMClaimExtractor
from sci_etl_core.claims.rejections import InMemoryRejectionStore
from sci_etl_core.claims.store_memory import InMemoryClaimStore
from sci_etl_core.extractors.async_base import AsyncExtractor
from sci_etl_core.llm.async_base import AsyncLLMClient
from sci_etl_core.llm.extraction_async import AsyncEntityExtractor
from sci_etl_core.llm.relevance_async import AsyncRelevanceFilter
from sci_etl_core.models import ListingPage, RawRecord
from sci_etl_core.pipeline_async import AsyncETLPipeline
from sci_etl_core.processors.validation import RecordValidator
from sci_etl_core.state.async_file_state import AsyncFileStateManager

TEXT = "DF44 is an ultra-diffuse galaxy. Its effective radius is 4.6 kpc in the g band. It hosts many clusters."
RECORD = RawRecord(record_id="1608.00001", title="DF44", abstract="a")


def radius(quote: str = "Its effective radius is 4.6 kpc in the g band.", **changes: Any) -> dict[str, Any]:
    draft = {
        "kind": "measurement",
        "subject": "DF44",
        "predicate": "effective_radius",
        "quantity": {"verbatim": "4.6 kpc", "value": 4.6, "unit_text": "kpc"},
        "context": {"band": "g"},
        "quote": quote,
    }
    draft.update(changes)
    return draft


class Answers(AsyncLLMClient):
    model = "m-1"

    def __init__(self, *answers: Any) -> None:
        self.answers = list(answers)
        self.schemas: list[Any] = []

    async def complete_json(self, system_prompt, user_content, timeout=None):  # noqa: ASYNC109
        raise AssertionError("claims are requested with a schema")

    async def complete_structured(self, system_prompt, user_content, schema, timeout=None):  # noqa: ASYNC109
        self.schemas.append(schema)
        return self.answers.pop(0)


class TestAsyncLLMClaimExtractor:
    @pytest.mark.asyncio
    async def test_grounded_drafts_become_stamped_claims_with_sentence_spans(self):
        client = Answers({"claims": [radius()]})
        extractor = AsyncLLMClaimExtractor(client, "Extract claims.")

        [claim] = await extractor.extract_record(RECORD, TEXT)

        assert TEXT[claim.span.start : claim.span.end] == "Its effective radius is 4.6 kpc in the g band."
        assert claim.record_id == RECORD.record_id
        assert claim.stamp == extractor.stamp
        assert claim.stamp.model == "m-1"
        assert client.schemas == [extractor.answer_schema]
        assert extractor.requires_record is True

    @pytest.mark.asyncio
    async def test_an_ungrounded_draft_is_logged_and_stored_as_a_rejection(self, caplog):
        rejections = InMemoryRejectionStore()
        client = Answers({"claims": [radius(), radius(quote="Its mass is 1e9 Msun.", subject="DF2")]})
        extractor = AsyncLLMClaimExtractor(
            client, "p", rejections=rejections, now=lambda: datetime(2026, 9, 26, tzinfo=UTC)
        )

        with caplog.at_level("INFO", logger="sci_etl_core.claims.extractor_async"):
            claims = await extractor.extract_record(RECORD, TEXT)

        [entry] = await rejections.unresolved()
        assert [claim.subject for claim in claims] == ["DF44"]
        assert entry.violations[0].code == "ungrounded"
        assert (entry.record_id, entry.quote) == (RECORD.record_id, "Its mass is 1e9 Msun.")
        assert entry.entity["subject"] == "DF2"
        assert caplog.messages == ["Claim rejected as ungrounded: 'DF2' (quote not found in the text)"]

    @pytest.mark.asyncio
    async def test_an_ungrounded_draft_without_a_store_is_only_logged(self):
        client = Answers({"claims": [radius(quote="Nothing like this appears.")]})

        assert await AsyncLLMClaimExtractor(client, "p").extract_record(RECORD, TEXT) == []

    @pytest.mark.asyncio
    async def test_schema_and_validator_rejections_reach_the_store(self):
        class NoGBand(RecordValidator):
            def is_valid(self, record):
                return record["context"].get("band") != "g"

        rejections = InMemoryRejectionStore()
        client = Answers({"claims": [radius(), {"kind": "measurement", "quote": "x"}]})
        extractor = AsyncLLMClaimExtractor(client, "p", validator=NoGBand(), rejections=rejections)

        assert await extractor.extract_record(RECORD, TEXT) == []
        codes = {violation.code for entry in await rejections.unresolved() for violation in entry.violations}
        assert codes == {"rejected", "schema"}

    @pytest.mark.asyncio
    async def test_extract_without_the_record_raises_the_declared_type_error(self):
        with pytest.raises(TypeError, match="extract_record"):
            await AsyncLLMClaimExtractor(Answers(), "p").extract(TEXT)

    def test_min_ratio_must_be_a_share(self):
        with pytest.raises(ValueError, match="min_ratio"):
            AsyncLLMClaimExtractor(Answers(), "p", min_ratio=2.0)

    @pytest.mark.asyncio
    async def test_a_wrapper_that_delegates_extract_record_works(self):
        class Wrapper(AsyncEntityExtractor[Any]):
            def __init__(self, inner: AsyncEntityExtractor[Any]) -> None:
                self.inner = inner
                self.requires_record = inner.requires_record

            async def extract(self, text):
                return await self.inner.extract(text)

            async def extract_record(self, record, text):
                return await self.inner.extract_record(record, text)

        wrapper = Wrapper(AsyncLLMClaimExtractor(Answers({"claims": [radius()]}), "p"))

        assert wrapper.requires_record is True
        assert len(await wrapper.extract_record(RECORD, TEXT)) == 1


class OnePaper(AsyncExtractor):
    def __init__(self, record: RawRecord) -> None:
        self.record = record

    async def fetch_page(self, query: str, cursor: str | None, page_size: int) -> ListingPage:
        return ListingPage(records=(self.record,), entries=1, next_cursor=None)

    async def fetch_full_text(self, record: RawRecord) -> str:
        return TEXT


class Relevant(AsyncRelevanceFilter):
    async def is_relevant(self, record: RawRecord) -> bool:
        return True


class TestClaimsThroughThePipeline:
    @pytest.mark.asyncio
    async def test_claims_are_stored_and_a_re_extraction_to_zero_clears_them(self, tmp_path):
        store = InMemoryClaimStore()

        async def run(answer: dict[str, Any], state_dir: str) -> None:
            pipeline = AsyncETLPipeline(
                OnePaper(RECORD),
                Relevant(),
                AsyncLLMClaimExtractor(Answers(answer), "p"),
                AsyncClaimStoreExporter(store),
                AsyncFileStateManager(tmp_path / state_dir / "ids.txt", tmp_path / state_dir / "meta.json"),
            )
            await pipeline.run("q", page_size=1, total_limit=1)

        await run({"claims": [radius()]}, "first")
        assert await store.count() == 1

        await run({"claims": []}, "second")
        assert await store.count() == 0
        assert [change.op for change in (await store.changes_since(0)).changes] == ["replace", "replace"]

    @pytest.mark.asyncio
    async def test_the_exporter_writes_durably_and_closes_its_store(self, mocker):
        store = InMemoryClaimStore()
        close = mocker.spy(store, "aclose")
        exporter = AsyncClaimStoreExporter(store)

        await exporter.aclose()

        assert exporter.store is store
        assert exporter.durable_writes is True
        close.assert_awaited_once()
