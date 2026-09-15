from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"


def _loaded_modules(code: str) -> set[str]:
    script = textwrap.dedent(code) + "\nimport sys\nprint('\\n'.join(sys.modules))\n"
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(SRC)},
        timeout=120,
        check=True,
    )
    return set(result.stdout.split())


def test_boolean_search_loads_only_the_standard_library():
    baseline = _loaded_modules("")
    loaded = _loaded_modules(
        """
        from sci_etl_core.discovery import DiscoveryResult, Facet
        from sci_etl_core.search import (
            AsyncHybridSearcher,
            AsyncSearchIndexer,
            AsyncSqliteFts5Store,
            EmbeddingEdgeSource,
            InMemoryTextSearchStore,
            MetadataEdgeSource,
            Unicode61Tokenizer,
            build_discovery_graph,
            normalize,
            parse_query,
            reciprocal_rank_fusion,
        )
        normalize(parse_query('title:"dwarf galaxy" photometr* -quasar'))
        Unicode61Tokenizer().tokens("Müller's H-alpha")
        """
    )
    added = {name.partition(".")[0] for name in loaded - baseline}
    assert added - set(sys.stdlib_module_names) == {"sci_etl_core"}


def test_the_read_model_loads_no_graph_code_store_or_numpy():
    loaded = _loaded_modules("from sci_etl_core.discovery import DiscoveryResult, Facet")
    assert "numpy" not in loaded
    heavier = {"sci_etl_core.search.graph", "sci_etl_core.search.fusion", "sci_etl_core.search.store_base"}
    assert heavier & loaded == set()


def test_the_memory_ingest_protocol_and_composite_never_load_the_pipeline():
    loaded = _loaded_modules(
        """
        from sci_etl_core.ingest_async import AsyncCompositeIngestor
        from sci_etl_core.ingest_protocol import MEMORY_FAULTS, MemoryIngestor
        """
    )
    assert "sci_etl_core.pipeline_async" not in loaded
    assert "numpy" not in loaded
