from __future__ import annotations

import httpx

from sci_etl_core._user_agent import DEFAULT_USER_AGENT


def build_async_client(
    total_retries: int = 5,
    timeout: float = 25.0,
    user_agent: str = DEFAULT_USER_AGENT,
) -> httpx.AsyncClient:
    """Build an ``httpx.AsyncClient`` for the bundled extractors.

    ``total_retries`` applies to connection failures only, at the transport
    level; the extractors retry HTTP status failures themselves. Redirects are
    followed, and ``timeout`` is in seconds. ``user_agent`` defaults to
    ``sci-etl-core/<installed version>``. The caller owns the client and
    closes it with ``aclose``.
    """
    transport = httpx.AsyncHTTPTransport(retries=total_retries)
    return httpx.AsyncClient(
        transport=transport,
        timeout=httpx.Timeout(timeout),
        headers={"User-Agent": user_agent},
        follow_redirects=True,
    )
