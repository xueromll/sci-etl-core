"""Contract suites that check a component's behavior against its base class.

Subclass a suite in a test module, give it the fixture that builds your
implementation, and pytest runs every test of the suite against it. The
bundled implementations run the same suites. This package needs the
``testing`` extra, which installs pytest; no other module imports it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sci_etl_core._lazy import lazy_exports

_EXPORTS: dict[str, str] = {
    "EmbeddingStoreContract": "sci_etl_core.testing.embeddings",
    "ExporterContract": "sci_etl_core.testing.exporters",
    "ExtractorContract": "sci_etl_core.testing.extractors",
    "StateManagerContract": "sci_etl_core.testing.state",
}

__all__ = list(_EXPORTS)
__getattr__, __dir__ = lazy_exports(__name__, globals(), _EXPORTS)

if TYPE_CHECKING:
    from sci_etl_core.testing.embeddings import EmbeddingStoreContract
    from sci_etl_core.testing.exporters import ExporterContract
    from sci_etl_core.testing.extractors import ExtractorContract
    from sci_etl_core.testing.state import StateManagerContract
