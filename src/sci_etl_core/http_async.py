from __future__ import annotations

import httpx


def build_async_client(
    total_retries: int = 5,
    timeout: float = 25.0,
    user_agent: str = "sci-etl-core/0.1",
) -> httpx.AsyncClient:
    transport = httpx.AsyncHTTPTransport(retries=total_retries)
    return httpx.AsyncClient(
        transport=transport,
        timeout=httpx.Timeout(timeout),
        headers={"User-Agent": user_agent},
    )
