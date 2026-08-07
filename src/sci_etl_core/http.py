from __future__ import annotations

import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry


def build_retrying_session(
    total_retries: int = 5,
    backoff_factor: float = 2.0,
    status_forcelist: tuple[int, ...] = (429, 500, 502, 503, 504),
) -> requests.Session:
    session = requests.Session()
    retries = Retry(total=total_retries, backoff_factor=backoff_factor, status_forcelist=list(status_forcelist))
    session.mount("https://", HTTPAdapter(max_retries=retries))
    session.mount("http://", HTTPAdapter(max_retries=retries))
    return session
