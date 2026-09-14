from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest
from openai import RateLimitError

from sci_etl_core._retry_after import (
    parse_retry_after,
    retry_after_from_error,
    retry_after_from_headers,
    retry_delay,
)

NOW = datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("7", 7.0),
        (" 2.5 ", 2.5),
        ("0", 0.0),
        ("Mon, 14 Sep 2026 12:00:30 GMT", 30.0),
        ("Mon, 14 Sep 2026 12:01:00", 60.0),
        ("Mon, 14 Sep 2026 11:00:00 GMT", 0.0),
        ("-5", None),
        ("inf", None),
        ("soon", None),
        ("", None),
        (None, None),
        (7, None),
    ],
)
def test_retry_after_accepts_seconds_and_http_dates(value, expected):
    assert parse_retry_after(value, now=NOW) == expected


def test_retry_after_dates_default_to_the_current_time():
    assert parse_retry_after("Wed, 21 Oct 2015 07:28:00 GMT") == 0.0


def test_milliseconds_header_is_preferred():
    assert retry_after_from_headers(httpx.Headers({"retry-after-ms": "250", "Retry-After": "9"})) == 0.25


def test_standard_header_is_used_without_milliseconds():
    assert retry_after_from_headers(httpx.Headers({"Retry-After": "9"})) == 9.0


def test_missing_headers_ask_for_no_particular_wait():
    assert retry_after_from_headers(None) is None


def test_wait_is_read_from_the_response_attached_to_an_error():
    response = httpx.Response(
        429, headers={"retry-after": "3"}, request=httpx.Request("POST", "https://api.example/v1/chat/completions")
    )
    assert retry_after_from_error(RateLimitError("slow down", response=response, body=None)) == 3.0
    assert retry_after_from_error(TimeoutError("no response")) is None


@pytest.mark.parametrize(
    ("attempt", "retry_after", "expected"),
    [
        (0, None, 1.0),
        (2, None, 4.0),
        (0, 7.0, 7.0),
        (2, 1.0, 4.0),
        (0, 3600.0, 60.0),
    ],
)
def test_retry_delay_is_the_longer_of_backoff_and_the_capped_server_wait(attempt, retry_after, expected):
    assert retry_delay(attempt, 2.0, retry_after, 60.0) == expected
