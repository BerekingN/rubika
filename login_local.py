#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
اسکریپت ورود یک‌بارِ اکانت سلف روبیکا.

این فایل را فقط یک‌بار، روی سیستم شخصی خودتان (نه روی Railway) اجرا کنید:

    pip install -U rubpy
    python login_local.py

از شما شماره تلفن، کد تایید پیامکی (و در صورت نیاز رمز دو مرحله‌ای) پرسیده
می‌شود. بعد از ورود موفق، یک فایل session به اسم «rubika_session.session»
همین‌جا ساخته می‌شود.

چرا لوکال و نه روی Railway؟
دقیقاً به همان دلیلی که نسخه‌ی تلگرام هم داشت: پلتفرم‌های پیام‌رسان روی
درخواست کد ورود از آی‌پی سرورهای دیتاسنتر (Railway/AWS/...) حساس‌تر عمل
می‌کنند و ممکن است ورود را مسدود کنند. اجرای این مرحله از اینترنت خانگی/
موبایل خودتان مطمئن‌ترین راه است.

بعد از اجرای موفق این اسکریپت:
    python session_to_env.py
را بزنید تا محتوای فایل session به‌صورت یک رشته‌ی base64 چاپ شود؛ همان رشته
را در Railway → Variables با نام SESSION_B64 قرار دهید.
"""

from rubpy import Client

SESSION_NAME = "rubika_session"

if __name__ == "__main__":
    print("در حال اتصال... اگر برای اولین‌بار است، شماره تلفن و کد تایید از شما پرسیده می‌شود.")
    with Client(name=SESSION_NAME) as client:
        me = client.get_me()
        print("✅ ورود موفق بود.")
        print(me)
    print(f"\nفایل سشن ساخته شد: {SESSION_NAME}.rp")
    print("حالا دستور زیر را بزنید تا مقدار SESSION_B64 برای Railway تولید شود:")
    print("    python session_to_env.py")
