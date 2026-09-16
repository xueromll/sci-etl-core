from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
from abc import ABC, abstractmethod
from collections import OrderedDict
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from sci_etl_core._sqlite_async import AsyncSqliteRunner
from sci_etl_core.exceptions import LLMCacheError
from sci_etl_core.llm.async_base import AsyncLLMClient
from sci_etl_core.models import TokenUsage

_CACHE_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS llm_responses ("
    " key TEXT PRIMARY KEY,"
    " response TEXT NOT NULL,"
    " created_at TEXT NOT NULL)"
)


def response_cache_key(model: str, system_prompt: str, user_content: str) -> str:
    """Return the cache key for a completion: a SHA-256 hex digest of its model and both prompts."""
    payload = json.dumps([model, system_prompt, user_content], ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class AsyncLLMResponseCache(ABC):
    """Storage for parsed completions, keyed by :func:`response_cache_key`."""

    @abstractmethod
    async def get(self, key: str) -> dict[str, Any] | None:
        """Return the cached response for ``key``, or ``None`` when there is none."""

    @abstractmethod
    async def set(self, key: str, response: dict[str, Any]) -> None:
        """Store ``response`` under ``key``, replacing any earlier one."""

    @abstractmethod
    async def clear(self) -> None:
        """Remove every cached response."""


class InMemoryLLMResponseCache(AsyncLLMResponseCache):
    """A cache that lives as long as the process, optionally bounded.

    With ``max_entries``, the least recently used response is evicted once the
    cache is full. Responses are copied in and out, so a caller that changes a
    returned dict cannot change what is cached.
    """

    def __init__(self, max_entries: int | None = None) -> None:
        """Create an empty cache.

        Raises:
            ValueError: ``max_entries`` is less than 1.
        """
        if max_entries is not None and max_entries < 1:
            raise ValueError("max_entries must be a positive integer")
        self._max_entries = max_entries
        self._entries: OrderedDict[str, str] = OrderedDict()

    def __len__(self) -> int:
        return len(self._entries)

    async def get(self, key: str) -> dict[str, Any] | None:
        stored = self._entries.get(key)
        if stored is None:
            return None
        self._entries.move_to_end(key)
        loaded: dict[str, Any] = json.loads(stored)
        return loaded

    async def set(self, key: str, response: dict[str, Any]) -> None:
        self._entries[key] = json.dumps(response)
        self._entries.move_to_end(key)
        if self._max_entries is not None and len(self._entries) > self._max_entries:
            self._entries.popitem(last=False)

    async def clear(self) -> None:
        self._entries.clear()


class AsyncSqliteLLMResponseCache(AsyncLLMResponseCache):
    """A cache kept in a SQLite file, so responses survive between runs.

    The file and its parent folder are created on first use, and responses are
    stored as JSON. Every SQLite failure, including a file that is not a
    database, raises :class:`~sci_etl_core.exceptions.LLMCacheError`. Close it
    with :meth:`aclose`, for example by listing it in the pipeline's
    ``closeables``. Use each instance from one event loop.
    """

    def __init__(self, path: str | Path, now: Callable[[], datetime] | None = None) -> None:
        self._path = Path(path)
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._runner = AsyncSqliteRunner(self._open_connection, error_factory=LLMCacheError)

    async def get(self, key: str) -> dict[str, Any] | None:
        row = await self._runner.run(
            lambda connection: connection.execute(
                "SELECT response FROM llm_responses WHERE key = ?", (key,)
            ).fetchone(),
            "read a cached LLM response",
        )
        if row is None:
            return None
        try:
            loaded = json.loads(row[0])
        except ValueError as exc:
            raise LLMCacheError(f"Cached LLM response for {key} is not valid JSON") from exc
        if not isinstance(loaded, dict):
            raise LLMCacheError(f"Cached LLM response for {key} is not a JSON object")
        return loaded

    async def set(self, key: str, response: dict[str, Any]) -> None:
        payload = json.dumps(response)
        stamp = self._now().isoformat()
        await self._runner.run(
            lambda connection: connection.execute(
                "INSERT OR REPLACE INTO llm_responses (key, response, created_at) VALUES (?, ?, ?)",
                (key, payload, stamp),
            ),
            "store an LLM response",
        )

    async def clear(self) -> None:
        await self._runner.run(
            lambda connection: connection.execute("DELETE FROM llm_responses"), "clear the LLM response cache"
        )

    async def count(self) -> int:
        """Return how many responses are cached."""
        row = await self._runner.run(
            lambda connection: connection.execute("SELECT COUNT(*) FROM llm_responses").fetchone(),
            "count cached LLM responses",
        )
        return int(row[0])

    async def aclose(self) -> None:
        """Close the connection; a later call reopens it."""
        await self._runner.aclose()

    def _open_connection(self) -> sqlite3.Connection:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self._path, check_same_thread=False, isolation_level=None)
        try:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute(_CACHE_SCHEMA)
        except BaseException:
            connection.close()
            raise
        return connection


@dataclass(slots=True)
class CacheStats:
    """How many completions a :class:`CachingLLMClient` served from its cache."""

    hits: int = 0
    misses: int = 0
    faults: int = 0


class CachingLLMClient(AsyncLLMClient):
    """Serve repeated completions from a cache instead of calling the LLM again.

    A request is keyed on ``model`` and both prompts (:func:`response_cache_key`).
    The timeout is not part of the key. Only successful responses are cached,
    so a failed call is retried the next time it is made. Change ``model`` when
    anything else that shapes the response changes, such as the temperature,
    for example ``"gpt-4o-mini@t0.2"``.

    The cache never fails a completion: an exception from the cache is logged
    as ``LLM cache <get|set> failed: <error>``, counted in :attr:`stats`, and the
    call goes to the LLM as on a miss. :attr:`usage` is the wrapped client's, so
    cache hits cost no tokens.
    """

    def __init__(
        self,
        client: AsyncLLMClient,
        cache: AsyncLLMResponseCache,
        model: str | None = None,
        logger: Callable[[str], None] | None = None,
    ) -> None:
        """Wrap ``client``.

        ``model`` defaults to the wrapped client's ``model`` attribute.

        Raises:
            ValueError: ``model`` is not given and the client has no ``model``
                string to key the cache by.
        """
        resolved = model if model is not None else getattr(client, "model", None)
        if not isinstance(resolved, str) or not resolved:
            raise ValueError("Pass model=, since the wrapped client has no model name to key the cache by")
        self._client = client
        self._cache = cache
        self._model = resolved
        self._log = logger or (lambda _msg: None)
        self._stats = CacheStats()

    @property
    def model(self) -> str:
        """The model name responses are cached under."""
        return self._model

    @property
    def stats(self) -> CacheStats:
        """Cache hits, misses, and faults so far, as a snapshot."""
        return replace(self._stats)

    @property
    def usage(self) -> TokenUsage | None:
        return self._client.usage

    async def complete_json(self, system_prompt: str, user_content: str, timeout: int | None = None) -> dict[str, Any]:
        """Return the cached response, or ask the wrapped client and cache its answer.

        Raises:
            LLMError: The wrapped client failed; nothing is cached.
        """
        key = response_cache_key(self._model, system_prompt, user_content)
        cached = await self._cached(key)
        if cached is not None:
            self._stats.hits += 1
            return cached
        self._stats.misses += 1
        response = await self._client.complete_json(system_prompt, user_content, timeout)
        try:
            await self._cache.set(key, response)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self._stats.faults += 1
            self._log(f"LLM cache set failed: {error!r}")
        return response

    async def _cached(self, key: str) -> dict[str, Any] | None:
        try:
            return await self._cache.get(key)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self._stats.faults += 1
            self._log(f"LLM cache get failed: {error!r}")
            return None
