# Migrating `udg-catalogue` to `sci-etl-core`

This shows the concrete adaptation. `sci-etl-core` owns the reusable
mechanics (retry/backoff HTTP, parsing, LLM calls, dedup/cluster/quality
math, CSV upsert, incremental state). `udg-catalogue` keeps everything that
is actually about ultra-diffuse galaxies: sky-coordinate matching,
Dragonfly/VCC name conventions, forbidden-keyword lists, prompt text, and
the Streamlit dashboard.

## 1. Install

```bash
pip install -e ../sci-etl-core          # local dev
# or, once published:
pip install sci-etl-core
```

`udg-catalogue/requirements.txt` drops `requests`, `pandas`, `numpy`,
`scikit-learn`, `openai`, `beautifulsoup4`, `pdfplumber`, `plotly`,
`pydantic`, `python-dotenv`, `PyYAML` as direct pins (they come in
transitively via `sci-etl-core`) and keeps `astropy`, `streamlit`,
`seaborn`, `matplotlib` — the astronomy- and dashboard-specific pieces
that don't belong in the core.

## 2. Module mapping

| Old file (udg-catalogue)          | New home                                                                 |
|------------------------------------|---------------------------------------------------------------------------|
| `logger.py`                        | `sci_etl_core.configure_logging`                                          |
| `config.py` (loader plumbing)      | `sci_etl_core.config.load_config` + a project-local `UdgConfig` subclass  |
| `arxiv_client.py` (HTTP/retry/parse)| `sci_etl_core.extractors.ArxivExtractor` + `parsers.PdfPlumberParser`/`LatexTarballParser` |
| `arxiv_client.py` (LLM relevance & extraction) | `sci_etl_core.llm.LLMRelevanceFilter` / `LLMEntityExtractor` + local prompts |
| `data_processor.py` (name normalization) | `sci_etl_core.processors.KeyNormalizer` subclass (local)             |
| `data_processor.py` (forbidden keywords, ra/dec bounds) | `sci_etl_core.processors.KeywordExclusionValidator` + `NumericRangeValidator` |
| `data_processor.py` (dedup by sky separation) | `sci_etl_core.processors.DeduplicationStep` + local `NeighborMatcher` (astropy) |
| `data_processor.py` (DBSCAN clustering) | `sci_etl_core.processors.ClusteringStep` + local `FeatureExtractor` (ra/dec/dist → xyz) |
| `data_processor.py` (completeness/quality) | `sci_etl_core.processors.CompletenessStep` / `QualityFlagStep`       |
| `data_processor.py` (CSV upsert)   | `sci_etl_core.exporters.CsvUpsertExporter`                                |
| `incremental.py`                   | `sci_etl_core.state.FileStateManager`                                     |
| `main.py` (crawl loop)             | `sci_etl_core.pipeline.ETLPipeline`                                       |
| `visualization.py`, `analytics.py`, `cross_match.py`, `app.py`, `prompts.py` | stay in `udg-catalogue`, domain-specific |

## 3. Config

```python
# udg_catalogue/config.py
from pathlib import Path
from pydantic import Field
from sci_etl_core import BaseAppConfig, load_config


class UdgConfig(BaseAppConfig):
    csv_file: str = "udg_catalogue.csv"
    processed_ids_file: str = "state/processed_ids.txt"
    metadata_file: str = "state/metadata.json"
    log_file: str = "logs/udg_catalogue.log"
    max_dist_mpc: float = 5.0
    dbscan_eps_mpc: float = 0.3
    dbscan_min_samples: int = 2
    forbidden_keywords: list[str] = Field(default_factory=lambda: ["simulation", "mock", "synthetic"])


def load_udg_config() -> UdgConfig:
    return load_config(
        UdgConfig,
        yaml_path=Path("config.yaml"),
        env_path=Path(".env"),
        api_key_env_var="DEEPSEEK_API_KEY",
    )
```

Nothing astronomy-specific leaks into `sci-etl-core` — `UdgConfig` just
extends `BaseAppConfig` with the extra fields this project needs.

## 4. Domain adapters (new, small, local files)

```python
# udg_catalogue/normalizers.py
import re
from sci_etl_core.processors import KeyNormalizer

DESIGNATION_ALIASES = {"dragonfly": "df", "virgo cluster catalog": "vcc"}


class GalaxyKeyNormalizer(KeyNormalizer):
    def normalize(self, raw_value: str) -> str:
        if not raw_value:
            return ""
        value = str(raw_value).strip().lower()
        for full, short in DESIGNATION_ALIASES.items():
            value = value.replace(full, short)
        return re.sub(r"[^a-z0-9]", "", value)
```

```python
# udg_catalogue/matching.py
import numpy as np
import pandas as pd
from astropy.coordinates import SkyCoord
import astropy.units as u
from sci_etl_core.processors import NeighborMatcher, FeatureExtractor


class SkyCoordNeighborMatcher(NeighborMatcher):
    def find_matches(self, frame: pd.DataFrame, threshold: float) -> list[tuple[int, int]]:
        coords = SkyCoord(ra=frame["ra"].to_numpy() * u.deg, dec=frame["dec"].to_numpy() * u.deg)
        matches: list[tuple[int, int]] = []
        seen: set[int] = set()
        for i in frame.index:
            if i in seen:
                continue
            separations = coords[i].separation(coords).arcsec
            close = frame.index[(separations < threshold) & (frame.index != i)]
            for j in close:
                if j not in seen:
                    matches.append((i, j))
                    seen.add(j)
        return matches


class RaDecDistanceFeatureExtractor(FeatureExtractor):
    def extract(self, frame: pd.DataFrame):
        valid = frame.dropna(subset=["ra", "dec", "distance_mpc"])
        ra, dec, dist = np.radians(valid["ra"]), np.radians(valid["dec"]), valid["distance_mpc"]
        x = dist * np.cos(dec) * np.cos(ra)
        y = dist * np.cos(dec) * np.sin(ra)
        z = dist * np.sin(dec)
        return np.column_stack([x, y, z]), valid.index
```

## 5. `arxiv_client.py` becomes wiring, not logic

```python
# udg_catalogue/arxiv_client.py
from sci_etl_core.extractors import ArxivExtractor
from sci_etl_core.parsers import PdfPlumberParser, LatexTarballParser
from sci_etl_core.llm import OpenAICompatibleClient, LLMRelevanceFilter, LLMEntityExtractor
from udg_catalogue.prompts import RELEVANCE_PROMPT, EXTRACTION_PROMPT


def build_extractor(config, logger) -> ArxivExtractor:
    return ArxivExtractor(
        user_agent="udg-catalogue/2.0 (mailto:you@example.com)",
        pdf_parser=PdfPlumberParser(),
        latex_parser=LatexTarballParser(),
        max_retries=config.http.max_retries,
        logger=logger.warning,
    )


def build_llm_client(config) -> OpenAICompatibleClient:
    return OpenAICompatibleClient(
        api_key=config.llm.api_key, base_url=config.llm.base_url, model=config.llm.model
    )


def build_relevance_filter(llm_client) -> LLMRelevanceFilter:
    return LLMRelevanceFilter(llm_client, system_prompt=RELEVANCE_PROMPT)


def build_entity_extractor(llm_client) -> LLMEntityExtractor:
    return LLMEntityExtractor(llm_client, system_prompt=EXTRACTION_PROMPT, result_key="galaxies")
```

## 6. `data_processor.py` becomes a `ProcessorChain`

```python
# udg_catalogue/data_processor.py
from sci_etl_core.processors import (
    ProcessorChain, NormalizationStep, DeduplicationStep,
    ClusteringStep, CompletenessStep, QualityFlagStep,
)
from udg_catalogue.normalizers import GalaxyKeyNormalizer
from udg_catalogue.matching import SkyCoordNeighborMatcher, RaDecDistanceFeatureExtractor

TRACKED_FIELDS = ["name", "ra", "dec", "distance_mpc", "effective_radius_arcsec", "surface_brightness"]


def build_pipeline(config) -> ProcessorChain:
    return ProcessorChain([
        NormalizationStep(key_column="name", normalizer=GalaxyKeyNormalizer()),
        DeduplicationStep(
            norm_key_column="_norm_key",
            matcher=SkyCoordNeighborMatcher(),
            match_threshold=5.0,
        ),
        ClusteringStep(
            feature_extractor=RaDecDistanceFeatureExtractor(),
            eps=config.dbscan_eps_mpc,
            min_samples=config.dbscan_min_samples,
        ),
        CompletenessStep(tracked_fields=TRACKED_FIELDS),
        QualityFlagStep(),
    ])
```

The keyword/coordinate-range validation used to gate LLM output before it
ever hits the dataframe:

```python
from sci_etl_core.processors import CompositeValidator, KeywordExclusionValidator, NumericRangeValidator

def build_record_validator(config) -> CompositeValidator:
    return CompositeValidator([
        KeywordExclusionValidator(key_field="name", forbidden_keywords=config.forbidden_keywords),
        NumericRangeValidator({"ra": (0.0, 360.0), "dec": (-90.0, 90.0)}),
    ])
```

## 7. `main.py` shrinks to orchestration

```python
# udg_catalogue/main.py
from sci_etl_core import ETLPipeline, configure_logging
from sci_etl_core.exporters import CsvUpsertExporter
from sci_etl_core.state import FileStateManager
from udg_catalogue.config import load_udg_config
from udg_catalogue.normalizers import GalaxyKeyNormalizer
from udg_catalogue.arxiv_client import build_extractor, build_llm_client, build_relevance_filter, build_entity_extractor

VALUE_COLUMNS = ["ra", "dec", "distance_mpc", "effective_radius_arcsec", "surface_brightness"]


def main() -> None:
    config = load_udg_config()
    logger = configure_logging("udg_catalogue", config.log_file)

    llm_client = build_llm_client(config)
    pipeline = ETLPipeline(
        extractor=build_extractor(config, logger),
        relevance_filter=build_relevance_filter(llm_client),
        entity_extractor=build_entity_extractor(llm_client),
        exporter=CsvUpsertExporter(
            key_column="name", value_columns=VALUE_COLUMNS, normalizer=GalaxyKeyNormalizer()
        ),
        state_manager=FileStateManager(config.processed_ids_file, config.metadata_file),
        destination=config.csv_file,
        max_workers=config.pipeline.max_workers,
        logger=logger.info,
    )

    processed = pipeline.run(
        query=config.pipeline.search_query,
        max_records=config.pipeline.max_records,
        sleep_between=config.pipeline.sleep_between,
    )
    logger.info(f"Processed {processed} new records this run.")


if __name__ == "__main__":
    main()
```

Then run the clustering/dedup/quality pass over the accumulated CSV as a
separate maintenance step whenever you like:

```python
import pandas as pd
from udg_catalogue.data_processor import build_pipeline

frame = pd.read_csv(config.csv_file)
frame = build_pipeline(config).process(frame)
frame.to_csv(config.csv_file, index=False)
```

## 8. What stays untouched

- `visualization.py` — keep it, but its base 3D scatter can delegate to
  `sci_etl_core.exporters.Plotly3DExporter(ScatterPlotConfig(...))` for
  the generic figure, then layer your custom hover template and unit
  formatting on top of the returned `Figure` before `write_html`.
- `analytics.py`, `cross_match.py`, `app.py`, `prompts.py` — fully
  domain-specific, no generalizable mechanics to extract.

## 9. Tests

Existing tests that mocked internal functions (`clean_duplicates`,
`upsert_to_csv`, `search_arxiv`, ...) now mock `sci_etl_core` classes
instead — inject a `mocker.MagicMock(spec=Extractor)` /
`spec=LLMClient` wherever `udg-catalogue` composes a pipeline. Tests for
`GalaxyKeyNormalizer`, `SkyCoordNeighborMatcher`, and
`RaDecDistanceFeatureExtractor` stay in `udg-catalogue`, since that's
where the astronomy math lives. `sci-etl-core` ships its own offline,
mock-based test suite (`tests/`) so the generic mechanics are verified
independently of any downstream project.
