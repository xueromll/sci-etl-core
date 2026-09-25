"""Measure exporter throughput through the real ``AsyncETLPipeline``.

Each exporter sees the same call pattern as in production, because the
benchmark never calls it directly: a synthetic listing of N records, every
record relevant and yielding 3 entities with distinct keys, runs through the
pipeline with ``page_size = 100``, ``max_concurrency = 6``, no wait between
pages, and an ``AsyncFileStateManager`` in a temporary directory. The
``discard`` exporter measures the pipeline's own overhead.

Export cost is linear when the time per record at the largest size is at most
1.5 times the time per record at the smallest. Run from the repository root::

    python benchmarks/run_throughput.py
    python benchmarks/run_throughput.py --sizes 1000 10000 --repeats 1 --exporters csv_upsert

Results are written as JSON to ``benchmarks/results/<version>.json`` unless
``--output`` names another file.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import platform
import statistics
import sys
import tempfile
import time
from collections.abc import Callable
from importlib.metadata import version
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sci_etl_core import (  # noqa: E402
    AsyncCsvUpsertExporter,
    AsyncEntityExtractor,
    AsyncETLPipeline,
    AsyncExporter,
    AsyncExtractor,
    AsyncFileStateManager,
    AsyncRelevanceFilter,
    RawRecord,
)
from sci_etl_core.processors import DefaultKeyNormalizer  # noqa: E402

PAGE_SIZE = 100
MAX_CONCURRENCY = 6
ENTITIES_PER_RECORD = 3
LINEARITY_LIMIT = 1.5
DEFAULT_SIZES = (1_000, 10_000, 50_000)


class SyntheticListing(AsyncExtractor):
    def __init__(self, size: int) -> None:
        self._size = size

    async def search(self, query: str, max_results: int, start_index: int) -> bytes:
        end = min(start_index + max_results, self._size)
        return f"{start_index}:{end}".encode()

    def parse_listing(self, raw_listing: bytes, seen_ids: set[str]) -> tuple[list[RawRecord], int]:
        start, end = (int(bound) for bound in raw_listing.decode().split(":"))
        records = [
            RawRecord(record_id=f"r{index}", title=f"record {index}", abstract="synthetic")
            for index in range(start, end)
            if f"r{index}" not in seen_ids
        ]
        return records, end - start

    async def fetch_full_text(self, record: RawRecord) -> str:
        return record.record_id


class AlwaysRelevant(AsyncRelevanceFilter):
    async def is_relevant(self, record: RawRecord) -> bool:
        return True


class DistinctEntities(AsyncEntityExtractor):
    async def extract(self, text: str | bytes) -> list[dict[str, Any]]:
        return [{"name": f"{text!s}-{index}", "value": float(index)} for index in range(ENTITIES_PER_RECORD)]


class DiscardingExporter(AsyncExporter):
    async def export(self, data: Any, destination: str) -> None:
        return None


EXPORTERS: dict[str, Callable[[], AsyncExporter]] = {
    "discard": DiscardingExporter,
    "csv_upsert": lambda: AsyncCsvUpsertExporter(
        key_column="name", value_columns=["value"], normalizer=DefaultKeyNormalizer()
    ),
}


async def measure(exporter: str, size: int) -> float:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        pipeline = AsyncETLPipeline(
            extractor=SyntheticListing(size),
            relevance_filter=AlwaysRelevant(),
            entity_extractor=DistinctEntities(),
            exporter=EXPORTERS[exporter](),
            state_manager=AsyncFileStateManager(root / "processed_ids.txt", root / "metadata.json"),
            destination=str(root / "entities.csv"),
            max_concurrency=MAX_CONCURRENCY,
        )
        started = time.perf_counter()
        processed = await pipeline.run(query="synthetic", page_size=PAGE_SIZE, total_limit=size, sleep_between=0)
        elapsed = time.perf_counter() - started
    if processed != size:
        raise RuntimeError(f"{exporter} processed {processed} of {size} records")
    return elapsed


def benchmark(exporters: list[str], sizes: list[int], repeats: int) -> dict[str, Any]:
    results: dict[str, Any] = {}
    linearity: dict[str, Any] = {}
    for exporter in exporters:
        per_size: dict[str, Any] = {}
        for size in sizes:
            runs = [asyncio.run(measure(exporter, size)) for _ in range(repeats)]
            median = statistics.median(runs)
            per_size[str(size)] = {"runs": runs, "median_seconds": median, "seconds_per_record": median / size}
            print(f"{exporter:>10} N={size:>6}: {median:9.3f} s, {1e3 * median / size:8.4f} ms per record", flush=True)
        results[exporter] = per_size
        smallest, largest = per_size[str(min(sizes))], per_size[str(max(sizes))]
        ratio = largest["seconds_per_record"] / smallest["seconds_per_record"]
        linearity[exporter] = {"ratio": ratio, "linear": ratio <= LINEARITY_LIMIT}
    return {
        "sci_etl_core": version("sci-etl-core"),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "page_size": PAGE_SIZE,
        "max_concurrency": MAX_CONCURRENCY,
        "entities_per_record": ENTITIES_PER_RECORD,
        "repeats": repeats,
        "results": results,
        "linearity": linearity,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sizes", type=int, nargs="+", default=list(DEFAULT_SIZES))
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--exporters", nargs="+", choices=sorted(EXPORTERS), default=sorted(EXPORTERS))
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    report = benchmark(arguments.exporters, sorted(arguments.sizes), arguments.repeats)
    output = arguments.output or ROOT / "benchmarks" / "results" / f"{report['sci_etl_core']}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    for exporter, verdict in report["linearity"].items():
        print(f"{exporter}: per-record ratio {verdict['ratio']:.2f}, {'linear' if verdict['linear'] else 'NOT linear'}")
    print(f"Wrote {output}")


if __name__ == "__main__":
    main()
