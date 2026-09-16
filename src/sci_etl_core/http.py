from __future__ import annotations

import warnings

import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry


def build_retrying_session(
    total_retries: int = 5,
    backoff_factor: float = 2.0,
    status_forcelist: tuple[int, ...] = (429, 500, 502, 503, 504),
) -> requests.Session:
    """Build a synchronous ``requests`` session that retries transient faults.

    .. deprecated:: 0.4.0
        No component uses this helper. It will be removed in 0.5.0, together
        with ``requests`` in the ``full`` extra. Use
        :func:`sci_etl_core.http_async.build_async_client` with the async
        components instead.
    """
    warnings.warn(
        "build_retrying_session is deprecated and will be removed in sci-etl-core 0.5.0; "
        "use sci_etl_core.http_async.build_async_client instead",
        DeprecationWarning,
        stacklevel=2,
    )
    session = requests.Session()
    retries = Retry(total=total_retries, backoff_factor=backoff_factor, status_forcelist=list(status_forcelist))
    session.mount("https://", HTTPAdapter(max_retries=retries))
    session.mount("http://", HTTPAdapter(max_retries=retries))
    return session
