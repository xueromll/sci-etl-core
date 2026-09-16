from __future__ import annotations

import pytest
import requests
from urllib3.util.retry import Retry

from sci_etl_core.http import build_retrying_session

pytestmark = pytest.mark.filterwarnings("ignore:build_retrying_session is deprecated:DeprecationWarning")


def test_warns_that_the_helper_is_deprecated():
    with pytest.warns(DeprecationWarning, match="removed in sci-etl-core 0.5.0"):
        build_retrying_session()


class TestBuildRetryingSession:
    def test_returns_a_requests_session(self):
        assert isinstance(build_retrying_session(), requests.Session)

    def test_mounts_retry_adapters_for_both_schemes(self):
        session = build_retrying_session()
        assert session.get_adapter("https://x") is not None
        assert session.get_adapter("http://x") is not None

    def test_retry_config_matches_arguments(self):
        session = build_retrying_session(total_retries=7, backoff_factor=1.5)
        retries = session.get_adapter("https://x").max_retries
        assert isinstance(retries, Retry)
        assert retries.total == 7
        assert retries.backoff_factor == 1.5

    def test_default_status_forcelist_includes_server_and_throttle_codes(self):
        session = build_retrying_session()
        forcelist = session.get_adapter("https://x").max_retries.status_forcelist
        for code in (429, 500, 502, 503, 504):
            assert code in forcelist
