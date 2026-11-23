# tests/test_yuanta_client.py
"""
test_yuanta_client.py — parsing, timestamps, anti-bot bounce and retries.

No network is used: every response is faked, so these tests describe exactly how
the client behaves against the payload shapes observed in production.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone

import pytest

HOST = "https://ysradar.yuanta.com.vn"


class FakeResponse:
    def __init__(self, status=200, payload=None, text="", content_type="application/json"):
        self.status_code = status
        self._payload = payload
        self.content_type = content_type
        self.text = text if payload is None else json.dumps(payload)
        self.headers = {"Content-Type": content_type}

    def json(self):
        if self._payload is None:
            raise ValueError("No JSON object could be decoded")
        return self._payload


class FakeSession:
    """Returns queued responses in order and records every call."""

    def __init__(self, responses):
        self.headers = {}
        self._responses = list(responses)
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append({"url": url, "params": params})
        if not self._responses:
            raise AssertionError(f"unexpected extra request to {url}")
        return self._responses.pop(0)


def make_client(yuanta, responses, **kwargs):
    session = FakeSession(responses)
    client = yuanta.YuantaClient(session=session, sleep=lambda _s: None, **kwargs)
    return client, session


CHALLENGE_HTML = (
    "<html><head><title>Attention Required! | Cloudflare</title></head>"
    '<body><script>window.location.href="/v2/tradingview/history?jskey=abc123"</script>'
    "</body></html>"
)

BARS_PAYLOAD = {
    "s": "ok",
    "bars": [
        {"t": 1577923200, "o": 51.06, "h": 52.0, "l": 50.5, "c": 51.8, "v": 1000},
        {"t": 1578009600, "o": 51.8, "h": 52.4, "l": 51.2, "c": 52.1, "v": 1200},
    ],
}


# ── timestamps & parsing ────────────────────────────────────────────
def test_bar_timestamp_is_utc_midnight(yuanta):
    bars = yuanta.parse_history_payload(BARS_PAYLOAD, "VNINDEX")
    assert bars[0]["date"] == date(2020, 1, 2)
    assert bars[1]["date"] == date(2020, 1, 3)


def test_millisecond_timestamps_are_understood(yuanta):
    payload = {"s": "ok", "bars": [{"t": 1577923200000, "o": 1, "h": 1, "l": 1, "c": 1}]}
    bars = yuanta.parse_history_payload(payload, "X")
    assert bars[0]["date"] == date(2020, 1, 2)


def test_no_data_returns_empty_list(yuanta):
    assert yuanta.parse_history_payload({"s": "no_data", "nextTime": None}, "X") == []


def test_unexpected_status_raises(yuanta):
    with pytest.raises(yuanta.YuantaError):
        yuanta.parse_history_payload({"s": "error"}, "X")


def test_payload_without_status_raises(yuanta):
    with pytest.raises(yuanta.YuantaError):
        yuanta.parse_history_payload({"bars": []}, "X")


def test_malformed_bars_are_skipped_not_fatal(yuanta):
    payload = {
        "s": "ok",
        "bars": [
            {"t": 1577923200, "o": 1, "h": 2, "l": 0.5, "c": 1.5},
            {"t": None, "o": 1, "h": 2, "l": 0.5, "c": 1.5},
            {"o": 1, "h": 2, "l": 0.5, "c": 1.5},
            "not-a-dict",
        ],
    }
    bars = yuanta.parse_history_payload(payload, "X")
    assert len(bars) == 1
    assert bars[0]["volume"] == 0.0


def test_bars_are_sorted_ascending(yuanta):
    payload = {
        "s": "ok",
        "bars": [
            {"t": 1578009600, "o": 1, "h": 1, "l": 1, "c": 1},
            {"t": 1577923200, "o": 1, "h": 1, "l": 1, "c": 1},
        ],
    }
    bars = yuanta.parse_history_payload(payload, "X")
    assert [b["date"] for b in bars] == [date(2020, 1, 2), date(2020, 1, 3)]


def test_start_epoch_is_inclusive_of_the_first_day(yuanta):
    start = date(2020, 1, 2)
    first_bar = int(datetime(2020, 1, 2, tzinfo=timezone.utc).timestamp())
    assert yuanta.start_to_epoch(start) < first_bar


def test_history_requests_a_future_end_date(yuanta):
    """`to=<now>` hides the current session, so the client must overshoot."""
    client, session = make_client(yuanta, [FakeResponse(payload=BARS_PAYLOAD)])
    client.history("VNINDEX", date(2020, 1, 1))
    sent = session.calls[0]
    assert sent["params"]["symbol"] == "VNINDEX"
    assert sent["params"]["resolution"] == "1D"
    assert sent["params"]["to"] > int(datetime.now(timezone.utc).timestamp())


# ── anti-bot interstitial ───────────────────────────────────────────
def test_challenge_bounce_is_followed_on_the_same_host(yuanta):
    client, session = make_client(
        yuanta,
        [
            FakeResponse(status=200, text=CHALLENGE_HTML, content_type="text/html"),
            FakeResponse(status=200, payload=BARS_PAYLOAD),
        ],
    )
    bars = client.history("VNINDEX", date(2020, 1, 1))
    assert len(bars) == 2
    assert session.calls[1]["url"] == f"{HOST}/v2/tradingview/history?jskey=abc123"
    assert client.stats["challenges"] == 1


def test_foreign_redirect_is_refused(yuanta):
    html = '<html>Attention Required<script>window.location.href="https://evil.example/x"</script></html>'
    client, session = make_client(
        yuanta, [FakeResponse(status=200, text=html, content_type="text/html")], retries=1
    )
    with pytest.raises(yuanta.YuantaError):
        client.history("VNINDEX", date(2020, 1, 1))
    assert all("evil.example" not in call["url"] for call in session.calls)


def test_challenge_hops_are_bounded(yuanta):
    responses = [
        FakeResponse(status=200, text=CHALLENGE_HTML, content_type="text/html")
        for _ in range(6)
    ]
    client, session = make_client(yuanta, responses, retries=1)
    with pytest.raises(yuanta.YuantaError):
        client.history("VNINDEX", date(2020, 1, 1))
    # one original request + MAX_CHALLENGE_HOPS bounces
    assert len(session.calls) == 1 + yuanta.MAX_CHALLENGE_HOPS


# ── retries & errors ────────────────────────────────────────────────
def test_server_error_is_retried_then_succeeds(yuanta):
    client, session = make_client(
        yuanta,
        [
            FakeResponse(status=500, text="upstream boom", content_type="text/plain"),
            FakeResponse(status=200, payload=BARS_PAYLOAD),
        ],
        retries=2,
    )
    bars = client.history("VNINDEX", date(2020, 1, 1))
    assert len(bars) == 2
    assert client.stats["retries"] == 1
    assert len(session.calls) == 2


def test_client_error_is_not_retried(yuanta):
    client, session = make_client(
        yuanta, [FakeResponse(status=404, text="nope", content_type="text/plain")], retries=3
    )
    with pytest.raises(yuanta.YuantaError):
        client.history("VNINDEX", date(2020, 1, 1))
    assert len(session.calls) == 1


def test_gives_up_after_all_retries(yuanta):
    responses = [
        FakeResponse(status=503, text="busy", content_type="text/plain") for _ in range(3)
    ]
    client, session = make_client(yuanta, responses, retries=3)
    with pytest.raises(yuanta.YuantaError) as excinfo:
        client.history("VNINDEX", date(2020, 1, 1))
    assert "giving up" in str(excinfo.value)
    assert len(session.calls) == 3


def test_index_board_reads_the_response_envelope(yuanta):
    payload = {"success": True, "response": [{"IndexCode": "VNINDEX", "RefIndex": 1700.0}]}
    client, _ = make_client(yuanta, [FakeResponse(payload=payload)])
    rows = client.index_board()
    assert rows == [{"IndexCode": "VNINDEX", "RefIndex": 1700.0}]


def test_index_board_tolerates_an_unexpected_shape(yuanta):
    client, _ = make_client(yuanta, [FakeResponse(payload={"weird": 1})])
    assert client.index_board() == []
