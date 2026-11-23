# tests/test_telegram_check.py
"""
test_telegram_check.py — chẩn đoán cấu hình Telegram.

Đây là bước quyết định "vì sao không nhận được tin nhắn": token sai định dạng,
token bị thu hồi, chat_id sai, bot chưa vào nhóm, bot bị chặn. Mỗi lỗi phải trả
về một gợi ý cụ thể, không phải "HTTP 400".
"""

from __future__ import annotations

import json
import sys

import pytest

GOOD_TOKEN = "123456789:AAF-abcDEF_12345678901234567890"
CHAT_ID = "-1001234567890"


def fake_api(responses, calls):
    """Trả về hàm `call` giả: responses là dict method → (ok, payload)."""

    def call(method, token, payload=None, timeout=15):
        calls.append((method, payload))
        return responses.get(method, (False, {"description": "unknown method"}))

    return call


# ── kiểm tra định dạng token ──────────────────────────────────────
def test_valid_token_shape(telegram_check):
    assert telegram_check.validate_token(GOOD_TOKEN) is None


@pytest.mark.parametrize(
    "token, expected",
    [
        ("", "thiếu secret TELEGRAM_TOKEN"),
        ("abcdef", "thiếu dấu ':'"),
        ("123456789", "thiếu dấu ':'"),
        ("123456789:short", "sai định dạng"),
        ("abc:AAF-abcDEF_12345678901234567890", "sai định dạng"),
    ],
)
def test_invalid_tokens(telegram_check, token, expected):
    error = telegram_check.validate_token(token)
    assert error and expected in error


# ── gợi ý sửa lỗi ────────────────────────────────────────────────
@pytest.mark.parametrize(
    "error, needle",
    [
        ("Bad Request: chat not found", "chat_id"),
        ("Forbidden: bot was blocked by the user", "bỏ chặn"),
        ("Forbidden: bot is not a member of the channel chat", "thêm bot"),
        ("Bad Request: not enough rights to send text messages", "quyền"),
        ("Unauthorized", "BotFather"),
    ],
)
def test_hints_are_actionable(telegram_check, error, needle):
    assert needle.lower() in telegram_check.hint_for(error).lower()


def test_unknown_error_has_no_hint(telegram_check):
    assert telegram_check.hint_for("some unexpected thing") == ""


# ── luồng kiểm tra ───────────────────────────────────────────────
def test_all_good(telegram_check, monkeypatch):
    calls = []
    monkeypatch.setattr(
        telegram_check,
        "call",
        fake_api(
            {
                "getMe": (True, {"username": "vn_sector_bot", "id": 42}),
                "getChat": (True, {"title": "VN Market", "type": "channel"}),
                "sendMessage": (True, {"message_id": 7}),
            },
            calls,
        ),
    )
    result = telegram_check.check(GOOD_TOKEN, CHAT_ID, send_text="xin chào")

    assert result["token_ok"] is True
    assert result["bot"] == "vn_sector_bot"
    assert result["chat_ok"] is True
    assert result["chat_title"] == "VN Market"
    assert result["send_ok"] is True
    assert result["message_id"] == 7
    assert [c[0] for c in calls] == ["getMe", "getChat", "sendMessage"]


def test_chat_not_found_is_explained(telegram_check, monkeypatch):
    monkeypatch.setattr(
        telegram_check,
        "call",
        fake_api(
            {
                "getMe": (True, {"username": "bot"}),
                "getChat": (False, {"description": "Bad Request: chat not found"}),
            },
            [],
        ),
    )
    result = telegram_check.check(GOOD_TOKEN, CHAT_ID)

    assert result["token_ok"] is True
    assert result["chat_ok"] is False
    assert "chat_id" in result["chat_error"]
    assert result["send_ok"] is None


def test_missing_chat_id_skips_the_api(telegram_check, monkeypatch):
    calls = []
    monkeypatch.setattr(
        telegram_check, "call", fake_api({"getMe": (True, {"username": "bot"})}, calls)
    )
    result = telegram_check.check(GOOD_TOKEN, "")

    assert result["chat_ok"] is False
    assert "TELEGRAM_CHAT_ID" in result["chat_error"]
    assert [c[0] for c in calls] == ["getMe"]


def test_invalid_token_never_calls_the_api(telegram_check, monkeypatch):
    calls = []
    monkeypatch.setattr(telegram_check, "call", fake_api({}, calls))
    result = telegram_check.check("nope", CHAT_ID, send_text="hi")

    assert result["token_ok"] is False
    assert result["send_ok"] is None
    assert calls == []


def test_send_is_skipped_when_chat_is_broken(telegram_check, monkeypatch):
    calls = []
    monkeypatch.setattr(
        telegram_check,
        "call",
        fake_api(
            {
                "getMe": (True, {"username": "bot"}),
                "getChat": (False, {"description": "Bad Request: chat not found"}),
                "sendMessage": (True, {"message_id": 1}),
            },
            calls,
        ),
    )
    telegram_check.check(GOOD_TOKEN, CHAT_ID, send_text="hi")
    assert "sendMessage" not in [c[0] for c in calls]


def test_network_failure_is_returned_not_raised(telegram_check, monkeypatch):
    import urllib.error

    def boom(*args, **kwargs):
        raise urllib.error.URLError("network down")

    monkeypatch.setattr(telegram_check.urllib.request, "urlopen", boom)
    ok, info = telegram_check.call("getMe", GOOD_TOKEN, timeout=1)

    assert ok is False
    assert "network down" in info["description"]


def test_http_error_body_is_parsed(telegram_check, monkeypatch):
    import io
    import urllib.error

    body = io.BytesIO(b'{"ok": false, "error_code": 400, "description": "Bad Request: chat not found"}')

    def boom(*args, **kwargs):
        raise urllib.error.HTTPError("url", 400, "Bad Request", {}, body)

    monkeypatch.setattr(telegram_check.urllib.request, "urlopen", boom)
    ok, info = telegram_check.call("getChat", GOOD_TOKEN, {"chat_id": "-1"})

    assert ok is False
    assert "chat not found" in info["description"]
    assert info["error_code"] == 400


# ── CLI ──────────────────────────────────────────────────────────
def _run_cli(telegram_check, monkeypatch, argv, result):
    monkeypatch.setattr(telegram_check, "check", lambda *a, **k: result)
    monkeypatch.setattr(sys, "argv", ["telegram_check.py"] + argv)
    return telegram_check.main()


def test_cli_require_fails_when_chat_is_bad(telegram_check, monkeypatch):
    result = {"token_ok": True, "chat_ok": False, "send_ok": None, "chat_error": "chat not found"}
    assert _run_cli(telegram_check, monkeypatch, ["--require"], result) == 1


def test_cli_without_require_is_informational(telegram_check, monkeypatch):
    result = {"token_ok": True, "chat_ok": False, "send_ok": None, "chat_error": "chat not found"}
    assert _run_cli(telegram_check, monkeypatch, [], result) == 0


def test_cli_fails_on_unsuccessful_send(telegram_check, monkeypatch):
    result = {"token_ok": True, "chat_ok": True, "send_ok": False, "send_error": "Forbidden"}
    assert _run_cli(telegram_check, monkeypatch, ["--require", "--send", "hi"], result) == 1


def test_cli_passes_and_writes_json_and_summary(telegram_check, monkeypatch, tmp_path):
    result = {
        "token_ok": True,
        "chat_ok": True,
        "chat_title": "VN Market",
        "chat_type": "channel",
        "send_ok": True,
        "message_id": 3,
        "bot": "vn_sector_bot",
    }
    out = tmp_path / "check.json"
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))

    code = _run_cli(
        telegram_check,
        monkeypatch,
        ["--require", "--send", "hi", "--json-out", str(out), "--summary"],
        result,
    )

    assert code == 0
    assert json.loads(out.read_text())["message_id"] == 3
    assert "Kiểm tra Telegram" in summary.read_text()
    assert "VN Market" in summary.read_text()
