# src/notify_failure.py
"""
notify_failure.py — Telegram alert for a failed workflow run.

Uses only the standard library (urllib), because the most likely failure is
`pip install` itself: the alert must still go out when no third-party package
imports. This is what turns "red for ten days and nobody noticed" into a
message on your phone the same evening.

Chạy: python src/notify_failure.py "lý do"   (thường gọi từ bước `if: failure()`)
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request


def _context() -> str:
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    branch = os.environ.get("GITHUB_REF_NAME", "")
    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    parts = []
    if repo:
        parts.append(repo)
    if branch:
        parts.append(f"branch {branch}")
    if run_id and repo:
        parts.append(f"{server}/{repo}/actions/runs/{run_id}")
    return " · ".join(parts)


def send(text: str, token: str, chat_id: str, timeout: int = 15) -> bool:
    payload = json.dumps(
        {"chat_id": chat_id, "text": text, "disable_web_page_preview": True}
    ).encode("utf-8")
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return 200 <= response.status < 300
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
        print(f"Không gửi được cảnh báo Telegram: {exc}")
        return False


def main() -> int:
    reason = " ".join(sys.argv[1:]).strip() or "không rõ nguyên nhân"
    token = os.environ.get("TELEGRAM_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        print("Thiếu TELEGRAM_TOKEN/TELEGRAM_CHAT_ID — bỏ qua cảnh báo.")
        return 0

    text = f"🚨 *VN Sector Bot thất bại*\n{reason}"
    context = _context()
    if context:
        text += f"\n{context}"
    text = text.replace("*", "")  # plain text only, no formatting surprises
    ok = send(text, token, chat_id)
    print("Đã gửi cảnh báo Telegram." if ok else "Cảnh báo Telegram không gửi được.")
    # Never fail this step: the job is already red for the real reason.
    return 0


if __name__ == "__main__":
    sys.exit(main())
