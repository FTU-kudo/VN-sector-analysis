# src/telegram_check.py
"""
telegram_check.py — Kiểm tra cấu hình Telegram trước khi chạy cả pipeline.

Chỉ dùng thư viện chuẩn (urllib), nên bước này chạy được kể cả khi `pip install`
thất bại — đúng loại sự cố đã làm bot chết 10 ngày mà không ai biết.

Việc nó làm:
  1. kiểm tra TELEGRAM_TOKEN có đúng dạng `123456789:ABC…` không;
  2. gọi `getMe` để xác nhận token còn sống và biết tên bot;
  3. gọi `getChat` để xác nhận chat_id tồn tại và bot đã ở trong đó;
  4. tuỳ chọn gửi một tin nhắn thử (`--send`);
  5. in ra lỗi kèm gợi ý sửa, ghi JSON cho bước summary.

Chạy:
  python src/telegram_check.py                       # chỉ kiểm tra
  python src/telegram_check.py --send "xin chào"      # kiểm tra + gửi thử
  python src/telegram_check.py --require              # lỗi ⇒ exit 1
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from typing import Any, Dict, Optional, Tuple

API = "https://api.telegram.org"
TOKEN_RE = re.compile(r"^\d{5,}:[A-Za-z0-9_-]{20,}$")

# Lỗi thường gặp → việc cần làm. So khớp không phân biệt hoa thường.
HINTS = (
    ("chat not found", "chat_id sai, hoặc bot chưa được thêm vào nhóm/kênh"),
    ("peer_id_invalid", "chat_id không hợp lệ (nhóm thường có dạng -100…)"),
    ("bot was blocked", "bạn đã chặn bot — mở Telegram và bỏ chặn"),
    ("bot is not a member", "thêm bot vào nhóm/kênh trước khi gửi"),
    ("not enough rights", "bot thiếu quyền gửi tin trong kênh/nhóm"),
    ("chat_write_forbidden", "bot không có quyền gửi tin vào chat này"),
    ("unauthorized", "token sai hoặc đã bị thu hồi (BotFather → API token)"),
    ("not found", "token không tồn tại (kiểm tra lại BotFather)"),
)


def hint_for(error: str) -> str:
    lowered = (error or "").lower()
    for needle, advice in HINTS:
        if needle in lowered:
            return advice
    return ""


def validate_token(token: str) -> Optional[str]:
    """Trả về thông báo lỗi, hoặc None nếu token đúng dạng."""
    if not token:
        return "thiếu secret TELEGRAM_TOKEN"
    if not TOKEN_RE.match(token):
        if ":" not in token:
            return "TELEGRAM_TOKEN thiếu dấu ':' — cần dạng 123456789:ABC…"
        return "TELEGRAM_TOKEN sai định dạng — cần dạng 123456789:ABC…"
    return None


def call(
    method: str,
    token: str,
    payload: Optional[dict] = None,
    timeout: int = 15,
) -> Tuple[bool, Dict[str, Any]]:
    """Gọi một method của Bot API. Không bao giờ ném exception."""
    url = f"{API}/bot{token}/{method}"
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST" if data is not None else "GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return False, {"description": f"không kết nối được {API} ({exc})"}

    try:
        parsed = json.loads(body or "{}")
    except ValueError:
        return False, {"description": (body or "")[:200]}

    if parsed.get("ok"):
        return True, parsed.get("result") or {}
    return False, {
        "description": str(parsed.get("description", "")),
        "error_code": parsed.get("error_code"),
    }


def check(
    token: str, chat_id: str, send_text: Optional[str] = None
) -> Dict[str, Any]:
    """Kiểm tra token, chat và (tuỳ chọn) gửi thử. Trả về dict kết quả."""
    result: Dict[str, Any] = {
        "token_ok": False,
        "chat_ok": False,
        "send_ok": None,
        "chat_id": chat_id,
    }

    token_error = validate_token(token)
    if token_error:
        result["token_error"] = token_error
    else:
        ok, info = call("getMe", token)
        if ok:
            result["token_ok"] = True
            result["bot"] = info.get("username")
            result["bot_id"] = info.get("id")
        else:
            description = info.get("description", "")
            result["token_error"] = description + (
                f" — {hint_for(description)}" if hint_for(description) else ""
            )

    if not chat_id:
        result["chat_error"] = "thiếu secret TELEGRAM_CHAT_ID"
    elif result["token_ok"]:
        ok, info = call("getChat", token, {"chat_id": chat_id})
        if ok:
            result["chat_ok"] = True
            result["chat_title"] = info.get("title") or info.get("username") or info.get("first_name")
            result["chat_type"] = info.get("type")
        else:
            description = info.get("description", "")
            result["chat_error"] = description + (
                f" — {hint_for(description)}" if hint_for(description) else ""
            )

    if send_text is not None and result["token_ok"] and result["chat_ok"]:
        ok, info = call(
            "sendMessage",
            token,
            {
                "chat_id": chat_id,
                "text": send_text,
                "disable_web_page_preview": True,
            },
        )
        result["send_ok"] = ok
        if ok:
            result["message_id"] = info.get("message_id")
        else:
            description = info.get("description", "")
            result["send_error"] = description + (
                f" — {hint_for(description)}" if hint_for(description) else ""
            )

    return result


def render(result: Dict[str, Any]) -> str:
    """Bản in cho log Actions."""
    lines = []
    if result.get("token_ok"):
        lines.append(f"✅ Token hợp lệ — bot @{result.get('bot', '?')}")
    else:
        lines.append(f"❌ Token: {result.get('token_error', 'không rõ')}")

    if result.get("chat_ok"):
        lines.append(
            f"✅ Chat tìm thấy — \"{result.get('chat_title', '?')}\""
            f" ({result.get('chat_type', '?')}, id {result.get('chat_id')})"
        )
    else:
        lines.append(f"❌ Chat: {result.get('chat_error', 'chưa kiểm tra (token lỗi)')}")

    if result.get("send_ok") is True:
        lines.append(f"✅ Đã gửi tin nhắn thử (message_id {result.get('message_id')})")
    elif result.get("send_ok") is False:
        lines.append(f"❌ Gửi tin nhắn thử thất bại: {result.get('send_error', '')}")
    return "\n".join(lines)


def as_markdown(result: Dict[str, Any]) -> str:
    def mark(flag) -> str:
        return "✅" if flag else ("—" if flag is None else "❌")

    rows = [
        ("Bot", f"@{result.get('bot')}" if result.get("bot") else (result.get("token_error") or "—")),
        ("Chat", result.get("chat_title") or result.get("chat_error") or "—"),
        ("Gửi thử", mark(result.get("send_ok"))),
    ]
    body = "\n".join(f"| {k} | {v} |" for k, v in rows)
    return f"### Kiểm tra Telegram\n| Mục | Kết quả |\n|---|---|\n{body}\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Kiểm tra cấu hình Telegram")
    parser.add_argument("--send", default=None, help="gửi một tin nhắn thử với nội dung này")
    parser.add_argument("--require", action="store_true", help="lỗi ⇒ exit 1")
    parser.add_argument("--json-out", default=None, help="ghi kết quả ra file JSON")
    parser.add_argument("--summary", action="store_true", help="ghi vào $GITHUB_STEP_SUMMARY")
    args = parser.parse_args()

    token = os.environ.get("TELEGRAM_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    result = check(token, chat_id, send_text=args.send)

    print(render(result))

    if args.json_out:
        os.makedirs(os.path.dirname(args.json_out) or ".", exist_ok=True)
        with open(args.json_out, "w", encoding="utf-8") as handle:
            json.dump(result, handle, ensure_ascii=False, indent=1)
            handle.write("\n")

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if args.summary and summary_path:
        with open(summary_path, "a", encoding="utf-8") as handle:
            handle.write(as_markdown(result) + "\n")

    failed = not result["token_ok"] or not result["chat_ok"] or result.get("send_ok") is False
    return 1 if (failed and args.require) else 0


if __name__ == "__main__":
    sys.exit(main())
