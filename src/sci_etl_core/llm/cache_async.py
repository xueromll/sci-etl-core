from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
from abc import ABC, abstractmethod
from collections import OrderedDict
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sci_etl_core._deprecation import warn_logger_argument
from sci_etl_core._migrations import Migration, migrate, newer_schema_message
from sci_etl_core._sqlite_async import AsyncSqliteRunner
from sci_etl_core.exceptions import LLMCacheError
from sci_etl_core.llm.async_base import AsyncLLMClient
from sci_etl_core.models import TokenUsage

_MIGRATIONS: tuple[Migration, ...] = (
    (
        1,
        (
            "CREATE TABLE IF NOT EXISTS llm_responses ("
            " key TEXT PRIMARY KEY,"
            " response TEXT NOT NULL,"
            " created_at TEXT NOT NULL)",
        ),
    ),
)


def response_cache_key(
    model: str,
    system_prompt: str,
    user_content: str,
    *,
    base_url: str | None = None,
    temperature: float | None = None,
    response_format: Mapping[str, Any] | None = None,
) -> str:
    """Return the cache key for a completion.

    The key is a SHA-256 hex digest of the model, the endpoint's ``base_url``,
    the sampling ``temperature``, the requested ``response_format``, and both
    prompts, so an answer cached for one provider, temperature, or format is
    never served for another.
    """
    sampling = None if temperature is None else float(temperature)
    requested = None if response_format is None else dict(response_format)
    payload = json.dumps(
        [model, base_url, sampling, requested, system_prompt, user_content],
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _optional_attribute(client: AsyncLLMClient, name: str, kind: type | tuple[type, ...]) -> Any:
    value = getattr(client, name, None)
    return value if isinstance(value, kind) and not isinstance(value, bool) else None


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

    async def delete(self, key: str) -> None:
        """Remove the response cached under ``key``, if there is one.

        :class:`CachingLLMClient` calls this for a response a component
        rejected, so the next request reaches the LLM again. Both bundled
        backends implement it; a custom backend should too.

        Raises:
            NotImplementedError: The backend does not implement it.
                :class:`CachingLLMClient` logs this as a cache fault, and the
                rejected response stays cached.
        """
        raise NotImplementedError(f"{type(self).__name__} does not implement delete")


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

    async def delete(self, key: str) -> None:
        self._entries.pop(key, None)

    async def clear(self) -> None:
        self._entries.clear()


class AsyncSqliteLLMResponseCache(AsyncLLMResponseCache):
    """A cache kept in a SQLite file, so responses survive between runs.

    The file and its parent folder are created on first use, and responses are
    stored as JSON. Every SQLite failure, including a file that is not a
    database or a file written by a newer sci-etl-core, raises
    :class:`~sci_etl_core.exceptions.LLMCacheError`. The file records its schema
    version in ``PRAGMA user_version``. Close it with :meth:`aclose`, for example by listing it in the pipeline's
    ``closeables``. Use each instance from one event loop.
    """

    def __init__(self, path: str | Path, now: Callable[[], datetime] | None = None) -> None:
        self._path = Path(path)
        self._now = now or (lambda: datetime.now(UTC))
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

    async def delete(self, key: str) -> None:
        await self._runner.run(
            lambda connection: connection.execute("DELETE FROM llm_responses WHERE key = ?", (key,)),
            "delete a cached LLM response",
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
            migrate(
                connection,
                _MIGRATIONS,
                lambda found, supported: LLMCacheError(newer_schema_message("LLM response cache", found, supported)),
            )
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

    A request is keyed on ``model``, ``base_url``, ``temperature``,
    ``response_format``, and both prompts (:func:`response_cache_key`).
    ``base_url``, ``temperature``, and ``response_format`` are read from the
    wrapped client's attributes of those names, as
    :class:`~sci_etl_core.llm.openai_compatible_async.AsyncOpenAICompatibleClient`
    exposes them, and are left out of the key for a client without them. The
    timeout is not part of the key.

    Only responses a component accepts stay cached. A failed call is never
    cached, and a response that
    :class:`~sci_etl_core.llm.extraction_async.AsyncLLMEntityExtractor` or
    :class:`~sci_etl_core.llm.relevance_async.AsyncLLMRelevanceFilter` rejects
    is removed through :meth:`invalidate`, so the next request reaches the LLM
    again instead of replaying the rejected answer.

    The cache never fails a completion: an exception from the cache is logged
    as ``LLM cache <get|set|delete> failed: <error>``, counted in :attr:`stats`,
    and the call goes to the LLM as on a miss. :attr:`usage` is the wrapped
    client's, so cache hits cost no tokens.
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
        self._base_url: str | None = _optional_attribute(client, "base_url", str)
        self._temperature: float | None = _optional_attribute(client, "temperature", (int, float))
        self._response_format: dict[str, Any] | None = _optional_attribute(client, "response_format", dict)
        warn_logger_argument("CachingLLMClient", logger)
        self._log = logger or (lambda _msg: None)
        self._stats = CacheStats()

    @property
    def model(self) -> str:
        """The model name responses are cached under."""
        return self._model

    @property
    def base_url(self) -> str | None:
        """The endpoint responses are cached under, or ``None`` when the wrapped client has none."""
        return self._base_url

    @property
    def temperature(self) -> float | None:
        """The sampling temperature responses are cached under, or ``None`` when the wrapped client has none."""
        return self._temperature

    @property
    def response_format(self) -> dict[str, Any]:
        """The wrapped client's ``response_format``, which responses are cached under."""
        return self._client.response_format

    @property
    def stats(self) -> CacheStats:
        """Cache hits, misses, and faults so far, as a snapshot."""
        return replace(self._stats)

    @property
    def usage(self) -> TokenUsage | None:
        return self._client.usage

    async def complete_json(self, system_prompt: str, user_content: str, timeout: int | None = None) -> dict[str, Any]:  # noqa: ASYNC109
        """Return the cached response, or ask the wrapped client and cache its answer.

        Raises:
            LLMError: The wrapped client failed; nothing is cached.
        """
        key = self._key(system_prompt, user_content)
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

    async def invalidate(self, system_prompt: str, user_content: str) -> None:
        """Remove the cached response to this request and tell the wrapped client.

        A cache failure is logged as ``LLM cache delete failed: <error>`` and
        counted in :attr:`stats`; it never raises.
        """
        try:
            await self._cache.delete(self._key(system_prompt, user_content))
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self._stats.faults += 1
            self._log(f"LLM cache delete failed: {error!r}")
        await self._client.invalidate(system_prompt, user_content)

    def _key(self, system_prompt: str, user_content: str) -> str:
        return response_cache_key(
            self._model,
            system_prompt,
            user_content,
            base_url=self._base_url,
            temperature=self._temperature,
            response_format=self._response_format,
        )

    async def _cached(self, key: str) -> dict[str, Any] | None:
        try:
            return await self._cache.get(key)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self._stats.faults += 1
            self._log(f"LLM cache get failed: {error!r}")
            return None
