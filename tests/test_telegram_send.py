# tests/test_telegram_send.py
"""
test_telegram_send.py — đường gửi tin nhắn báo cáo.

Ba kiểu hỏng đã gặp ở Telegram Bot API và cách xử lý mong đợi:
  * lỗi tạm thời (5xx, 429, mất mạng)  → thử lại vài lần;
  * lỗi cấu hình (400 chat không tồn tại, 403 bot bị chặn) → báo ngay, không thử lại;
  * HTML bị từ chối ("can't parse entities") → gửi lại dạng văn bản thuần.
"""

from __future__ import annotations

import pytest


class Resp:
    def __init__(self, status=200, description="", text=None):
        self.status_code = status
        self._description = description
        self.text = text if text is not None else (
            '{"ok": true}' if 200 <= status < 300 else f'{{"ok": false, "description": "{description}"}}'
        )

    @property
    def ok(self):
        return 200 <= self.status_code < 300

    def json(self):
        import json as _json

        if 200 <= self.status_code < 300:
            return {"ok": True, "result": {"message_id": 1}}
        return {"ok": False, "description": self._description}


@pytest.fixture
def tg(telegram, monkeypatch):
    monkeypatch.setattr(telegram, "TELEGRAM_TOKEN", "123456789:AAF-abcDEF_12345678901234567890")
    monkeypatch.setattr(telegram, "TELEGRAM_CHAT_ID", "-1001234567890")
    monkeypatch.setattr(
        telegram,
        "TELEGRAM_URL",
        "https://api.telegram.org/bot123456789:AAF/sendMessage",
    )
    monkeypatch.setattr(telegram, "LAST_ERROR", "", raising=False)
    return telegram


def install_post(tg, monkeypatch, responses):
    """Gắn requests.post giả, trả về danh sách payload đã gửi."""
    sent = []

    def post(url, json=None, timeout=None):
        sent.append(json)
        if not responses:
            raise AssertionError("gửi nhiều lần hơn dự kiến")
        return responses.pop(0)

    monkeypatch.setattr(tg.requests, "post", post)
    return sent


def test_successful_send(tg, monkeypatch):
    sent = install_post(tg, monkeypatch, [Resp()])

    assert tg.send_telegram("<b>x</b>") is True
    assert len(sent) == 1
    assert sent[0]["parse_mode"] == "HTML"
    assert tg.LAST_ERROR == ""


def test_missing_credentials_do_not_call_the_api(tg, monkeypatch):
    monkeypatch.setattr(tg, "TELEGRAM_TOKEN", "")
    sent = install_post(tg, monkeypatch, [])

    assert tg.send_telegram("x") is False
    assert sent == []
    assert "TELEGRAM_TOKEN" in tg.LAST_ERROR


def test_chat_not_found_is_not_retried(tg, monkeypatch):
    sent = install_post(tg, monkeypatch, [Resp(400, "Bad Request: chat not found")])

    assert tg.send_telegram("x") is False
    assert len(sent) == 1  # 400 không thử lại
    assert "chat not found" in tg.LAST_ERROR


def test_transient_error_is_retried(tg, monkeypatch):
    sent = install_post(tg, monkeypatch, [Resp(502, "Bad Gateway"), Resp()])

    ok, error = tg._post_message({"chat_id": "1", "text": "x"}, sleep=lambda _s: None)
    assert ok is True and error == ""
    assert len(sent) == 2


def test_retries_give_up_and_report_the_last_error(tg, monkeypatch):
    install_post(tg, monkeypatch, [Resp(500, "boom"), Resp(500, "boom"), Resp(500, "boom")])

    ok, error = tg._post_message({"chat_id": "1", "text": "x"}, sleep=lambda _s: None)
    assert ok is False
    assert "boom" in error


def test_html_rejection_falls_back_to_plain_text(tg, monkeypatch):
    first = Resp(400, "Bad Request: can't parse entities: Unsupported start tag")
    sent = install_post(tg, monkeypatch, [first, Resp()])

    assert tg.send_telegram("<b>broken</b>") is True
    assert len(sent) == 2
    assert "parse_mode" not in sent[1]  # lần gửi lại là văn bản thuần
    assert "<b>" not in sent[1]["text"]
    assert "broken" in sent[1]["text"]  # nội dung vẫn còn, chỉ bỏ thẻ


def test_long_report_is_split_into_chunks(tg, monkeypatch):
    message = "\n".join(f"Dòng số {i} của báo cáo thử nghiệm" for i in range(400))
    assert len(message) > 3500

    sent = install_post(tg, monkeypatch, [Resp() for _ in range(10)])

    assert tg.send_telegram(message) is True
    assert len(sent) > 1
    assert all(len(part["text"]) <= 4096 for part in sent)


def test_partial_send_failure_stops_and_reports(tg, monkeypatch):
    message = "\n".join(f"Dòng số {i} của báo cáo thử nghiệm" for i in range(400))
    install_post(tg, monkeypatch, [Resp(), Resp(403, "Forbidden: bot was blocked by the user")])

    assert tg.send_telegram(message) is False
    assert "bot was blocked" in tg.LAST_ERROR


def test_send_plain_uses_no_parse_mode(tg, monkeypatch):
    sent = install_post(tg, monkeypatch, [Resp()])

    assert tg.send_plain("cảnh báo") is True
    assert "parse_mode" not in sent[0]
