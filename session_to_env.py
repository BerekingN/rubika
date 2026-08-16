#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
فایل session ساخته‌شده توسط login_local.py را به یک رشته‌ی base64 تبدیل
می‌کند تا بتوانید آن را در Railway → Variables با نام SESSION_B64 قرار دهید.

اجرا (روی همان سیستمی که login_local.py را اجرا کردید):
    python session_to_env.py
"""

import base64
from pathlib import Path

SESSION_FILE = Path("rubika_session.rp")

if __name__ == "__main__":
    if not SESSION_FILE.exists():
        raise SystemExit(
            "فایل rubika_session.rp پیدا نشد. اول login_local.py را اجرا کنید."
        )
    raw = SESSION_FILE.read_bytes()
    encoded = base64.b64encode(raw).decode("utf-8")
    print("\nمقدار زیر را در Railway → Variables با نام SESSION_B64 قرار دهید:\n")
    print(encoded)
    print(
        "\n⚠️ این رشته معادل کامل دسترسی به اکانت شماست — آن را جایی عمومی "
        "(چت، گیت‌هاب عمومی و ...) قرار ندهید."
    )
