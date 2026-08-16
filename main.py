#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ربات مدیریتی + سلف روبیکا — نسخه‌ی Railway
ساخته‌شده با rubpy (https://github.com/shayanheidari01/rubika)

این اسکریپت یک کلاینت اجرا می‌کند: کلاینت سلف (user_client) که با سشن
از پیش ساخته‌شده (توسط login_local.py، اجراشده روی سیستم شخصی شما) وارد
اکانت روبیکای شما می‌شود و دستورات فارسی را در «Saved Messages» (چت
با خودتان / 'me') و در گروه‌ها می‌خواند.

هیچ ارسال خودکار و تکرارشونده‌ی تبلیغاتی به گروه‌ها در این کد وجود ندارد؛
بخش «بنر» فقط با دستور دستی شما ارسال می‌شود، یا صرفاً یک یادآوری به
خودتان می‌فرستد تا خودتان تصمیم به ارسال بگیرید. دلیل: ارسال خودکار و
مکرر پیام یکسان به گروه‌های متعدد در هر پلتفرم پیام‌رسانی به‌عنوان اسپم
شناسایی می‌شود و می‌تواند به محدود یا بن‌شدن اکانت شخصی شما منجر شود.

توضیحات کامل نصب/دیپلوی در README.md
"""

import asyncio
import base64
import json
import logging
import operator
import os
import random
import re
import time
from pathlib import Path

from rubpy import Client, filters

# ---------------------------------------------------------------------------
# تنظیمات پایه
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
log = logging.getLogger("rubika-selfbot")

SESSION_NAME = "rubika_session"
SESSION_FILE = Path(__file__).parent / f"{SESSION_NAME}.rp"
SESSION_B64 = os.environ.get("SESSION_B64", "").strip()

OWNER_GUID = os.environ.get("OWNER_GUID", "").strip() or None

DATA_FILE = Path(__file__).parent / "bot_data.json"

# اگر فایل سشن روی دیسک نیست ولی SESSION_B64 ست شده، همین ابتدا آن را
# می‌سازیم (همان چیزی که session_to_env.py روی سیستم شما تولید کرده بود).
if SESSION_B64 and not SESSION_FILE.exists():
    try:
        SESSION_FILE.write_bytes(base64.b64decode(SESSION_B64))
        log.info("فایل سشن از SESSION_B64 بازسازی شد.")
    except Exception:
        log.exception("خطا در بازسازی فایل سشن از SESSION_B64")

if not SESSION_FILE.exists():
    raise SystemExit(
        "فایل سشن پیدا نشد. اول login_local.py را روی سیستم خودتان اجرا کنید، "
        "بعد با session_to_env.py مقدار SESSION_B64 را بگیرید و در Railway → "
        "Variables قرار دهید. راهنمای کامل در README.md."
    )

# ---------------------------------------------------------------------------
# ذخیره‌سازی ساده روی فایل JSON
# ---------------------------------------------------------------------------

DEFAULT_DATA = {
    "admins": [],              # گویدهای ادمین اضافه بر مالک
    "groups": [],              # [{"guid": ..., "title": ...}, ...]
    "banner": None,            # {"text": ..., "set_by": ...}
    "banner_reminder": {"enabled": False, "minutes": 0, "last_run": 0},
    "auto_reply": {"enabled": False, "text": ""},
    "qa": {},                  # {"سوال": "جواب"}
    "muted": False,
    "notes": [],                # ["متن یادداشت", ...]
    "saved": {},                 # {"برچسب": "متن پیام"}
    "countdowns": [],           # [{"title":..., "date":"YYYY-MM-DD"}]
}


def load_data():
    if DATA_FILE.exists():
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                d = json.load(f)
            for k, v in DEFAULT_DATA.items():
                d.setdefault(k, v)
            return d
        except Exception:
            log.exception("خطا در خواندن bot_data.json - از تنظیمات پیش‌فرض استفاده می‌شود")
    return json.loads(json.dumps(DEFAULT_DATA))


def save_data(d):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)


data = load_data()
if OWNER_GUID and OWNER_GUID not in data["admins"]:
    data["admins"].append(OWNER_GUID)
    save_data(data)

# ---------------------------------------------------------------------------
# کلاینت سلف
# ---------------------------------------------------------------------------

client = Client(name=SESSION_NAME)

pending_guess = {}   # {chat_guid: number}  -> بازی حدس عدد
pending_reminders = []  # [{"chat":..., "text":..., "at": ts}]

QUIZ_BANK = [
    {"q": "پایتخت فرانسه کدام است؟", "options": ["لندن", "پاریس", "رم", "برلین"], "answer": "ب"},
    {"q": "دو به‌توان ده چند می‌شود؟", "options": ["512", "1024", "2048", "256"], "answer": "ب"},
    {"q": "بزرگ‌ترین اقیانوس جهان؟", "options": ["اطلس", "هند", "آرام", "منجمد"], "answer": "ج"},
]

JOKES = [
    "به کامپیوتر گفتم شوخی کن، گفت من از حافظه‌ام هیچی حذف نمی‌کنم 😄",
    "چرا برنامه‌نویس‌ها عاشق طبیعت‌ان؟ چون بدون باگ آرومن 🌳",
    "دیباگ کردن مثل بازی کارآگاه‌بازیه؛ خودت هم قاتلی 🕵️",
]

FORTUNES = [
    "امروز روز خوبیه برای شروع یه کار جدید ✨",
    "یه خبر خوب تو راهه، فقط صبور باش 🌟",
    "امروز با یکی از دوستای قدیمیت حرف بزن 📞",
]


def is_admin(guid: str) -> bool:
    return OWNER_GUID is None or guid == OWNER_GUID or guid in data["admins"]


def find_group_index(idx_text: str):
    try:
        idx = int(idx_text)
        if 1 <= idx <= len(data["groups"]):
            return idx - 1
    except ValueError:
        pass
    return None


SAFE_CALC_OPERATORS = {
    "+": operator.add, "-": operator.sub, "*": operator.mul,
    "/": operator.truediv, "%": operator.mod, "^": operator.pow,
}


def safe_calc(expr: str):
    """ماشین‌حساب امن: فقط اعداد و عملگرهای پایه، بدون eval خام."""
    cleaned = expr.replace("^", "**")
    if not re.fullmatch(r"[0-9\.\+\-\*\/\%\(\)\s]+", cleaned):
        raise ValueError("عبارت نامعتبر است.")
    return eval(cleaned, {"__builtins__": {}}, {})  # noqa: S307 - ورودی از قبل فیلتر شده


HELP_TEXT = """📖 راهنمای ربات (نسخه‌ی روبیکا)

اکثر دستورات را در «Saved Messages» (چت با خودتان) بفرستید.
دستور «ثبت بنر» را می‌توانید مستقیم داخل خود گروه هم بفرستید.

🔹 عمومی
راهنما / پینگ / آیدی

🔹 گروه‌ها
افزودن گروه <guid> | لیست گروه‌ها | حذف گروه <شماره>

🔹 بنر (فقط دستی — بدون ارسال خودکار تکرارشونده)
ثبت بنر (با ریپلای) | بنر (پیش‌نمایش) | ارسال بنر <شماره یا all>
یادآوری بنر روشن <دقیقه> | یادآوری بنر خاموش | یادآوری بنر وضعیت
تایید ارسال — بعد از دریافت یادآوری، همان بنر را به تمام گروه‌ها می‌فرستد

🔹 منشی
منشی روشن / منشی خاموش / منشی متن <پیام>
پرسش پاسخ افزودن <سوال> | <جواب> / پرسش پاسخ حذف <سوال> / لیست پرسش پاسخ

🔹 امنیت
سکوت روشن / سکوت خاموش
افزودن ادمین <guid> / حذف ادمین <guid> / لیست ادمین‌ها

🔹 بازی و سرگرمی
تاس / سکه / سنگ کاغذ قیچی <سنگ|کاغذ|قیچی> / حدس عدد / چالش / جوک / فال

🔹 ساعت، تاریخ و ابزار
ساعت / تاریخ / حساب <عبارت>

🔹 یادداشت و یادآوری
یادداشت افزودن <متن> / لیست یادداشت‌ها / حذف یادداشت <شماره>
یادآوری <دقیقه> <متن>
سیو <برچسب> (با ریپلای) / لیست سیو / نمایش سیو <برچسب>

⚠️ ارسال خودکار و زمان‌بندی‌شده‌ی تکراری به گروه‌ها در این ربات وجود ندارد؛
این کار در روبیکا هم مثل هر پلتفرم دیگری اسپم محسوب می‌شود و ریسک بن دارد.
"""


# ---------------------------------------------------------------------------
# حلقه‌ی پس‌زمینه: یادآوری بنر + یادآوری‌های عمومی
# ---------------------------------------------------------------------------

async def background_loop():
    while True:
        try:
            await asyncio.sleep(15)
            now = time.time()

            # یادآوری بنر (فقط پیام یادآوری، هیچ ارسالی خودکار به گروه انجام نمی‌شود)
            br = data["banner_reminder"]
            if br.get("enabled") and br.get("minutes", 0) > 0:
                interval = br["minutes"] * 60
                if now - br.get("last_run", 0) >= interval:
                    br["last_run"] = now
                    save_data(data)
                    if data.get("banner"):
                        await client.send_message(
                            "me",
                            "⏰ یادآوری: وقت بررسی/ارسال بنره.\n"
                            "برای ارسال واقعی به همه‌ی گروه‌ها بنویسید: تایید ارسال",
                        )
                    else:
                        await client.send_message(
                            "me", "⏰ یادآوری بنر فعاله ولی هنوز بنری با «ثبت بنر» ذخیره نکردید."
                        )

            # یادآوری‌های عمومی (یادآوری <دقیقه> <متن>)
            due = [r for r in pending_reminders if r["at"] <= now]
            for r in due:
                pending_reminders.remove(r)
                try:
                    await client.send_message(r["chat"], f"🔔 یادآوری: {r['text']}")
                except Exception:
                    log.exception("خطا در ارسال یادآوری")

        except asyncio.CancelledError:
            break
        except Exception:
            log.exception("خطا در حلقه‌ی پس‌زمینه")


# ---------------------------------------------------------------------------
# هندلر اصلی پیام‌ها
# ---------------------------------------------------------------------------

@client.on_message_updates(filters.text)
async def on_message(update):
    text = (update.text or "").strip()
    sender = getattr(update, "author_guid", None) or getattr(update, "sender_guid", None)
    chat = getattr(update, "object_guid", None) or getattr(update, "chat_id", None)
    is_group_chat = bool(getattr(update, "is_group", False))

    if not text:
        return

    # ---------- بازی حدس عدد: اگر منتظر عدد هستیم ----------
    if chat in pending_guess and text.isdigit():
        target = pending_guess[chat]
        guess = int(text)
        if guess == target:
            await update.reply(f"🎉 آفرین! عدد {target} بود.")
            del pending_guess[chat]
        elif guess < target:
            await update.reply("بزرگ‌تر بگو ⬆️")
        else:
            await update.reply("کوچک‌تر بگو ⬇️")
        return

    # ---------- ثبت بنر (هم در گروه، هم در پیوی؛ نیاز به ریپلای) ----------
    if text == "ثبت بنر":
        if not is_admin(sender):
            return
        reply_msg = getattr(update, "reply_message", None) or getattr(update, "reply_to", None)
        if not reply_msg:
            await update.reply("این دستور را باید روی یک پیام ریپلای کنید.")
            return
        banner_text = getattr(reply_msg, "text", None) or ""
        data["banner"] = {"text": banner_text, "set_by": sender}
        save_data(data)
        await update.reply("✅ بنر ذخیره شد.")
        return

    # از اینجا به بعد: در گروه فقط ادمین دستور می‌دهد؛ در پیوی، غیرادمین فقط
    # منشی/پرسش‌وپاسخ می‌گیرد و ادمین به منوی کامل دستورات می‌رسد.
    if is_group_chat:
        if not is_admin(sender):
            return
    else:
        if not is_admin(sender):
            if data["muted"]:
                return
            for q, a in data["qa"].items():
                if q in text:
                    await update.reply(a)
                    return
            if data["auto_reply"]["enabled"] and data["auto_reply"]["text"]:
                await update.reply(data["auto_reply"]["text"])
            return

    # ---------- عمومی ----------
    if text == "راهنما":
        await update.reply(HELP_TEXT)
        return
    if text == "پینگ":
        t0 = time.time()
        await update.reply(f"🏓 پونگ! ({(time.time()-t0)*1000:.0f}ms)")
        return
    if text == "آیدی":
        await update.reply(f"آیدی شما: `{sender}`")
        return

    # ---------- گروه‌ها ----------
    if text.startswith("افزودن گروه"):
        guid = text.replace("افزودن گروه", "", 1).strip()
        if not guid:
            await update.reply("مثال: افزودن گروه <guid گروه>")
            return
        title = guid
        try:
            info = await client.get_chat(guid)
            title = getattr(info, "title", guid)
        except Exception:
            pass
        data["groups"].append({"guid": guid, "title": title})
        save_data(data)
        await update.reply(f"✅ گروه «{title}» اضافه شد.")
        return

    if text == "لیست گروه‌ها":
        if not data["groups"]:
            await update.reply("هنوز گروهی اضافه نشده.")
            return
        lines = ["📋 لیست گروه‌ها:"]
        for i, g in enumerate(data["groups"], 1):
            lines.append(f"{i}. {g['title']}")
        await update.reply("\n".join(lines))
        return

    if text.startswith("حذف گروه"):
        idx = find_group_index(text.replace("حذف گروه", "", 1).strip())
        if idx is None:
            await update.reply("شماره گروه نامعتبر است.")
            return
        removed = data["groups"].pop(idx)
        save_data(data)
        await update.reply(f"🗑 گروه «{removed['title']}» حذف شد.")
        return

    # ---------- بنر (دستی) ----------
    if text == "بنر":
        b = data.get("banner")
        if not b:
            await update.reply("هنوز بنری ثبت نشده. با ریپلای بنویسید: ثبت بنر")
            return
        await update.reply(f"🖼 پیش‌نمایش بنر:\n\n{b['text']}")
        return

    if text.startswith("ارسال بنر"):
        b = data.get("banner")
        if not b:
            await update.reply("هنوز بنری ثبت نشده.")
            return
        arg = text.replace("ارسال بنر", "", 1).strip()
        targets = []
        if arg == "all":
            targets = data["groups"]
        else:
            idx = find_group_index(arg)
            if idx is None:
                await update.reply("مثال: ارسال بنر all یا ارسال بنر 2")
                return
            targets = [data["groups"][idx]]
        ok, fail = 0, 0
        for g in targets:
            try:
                await client.send_message(g["guid"], b["text"])
                ok += 1
                await asyncio.sleep(2)  # فاصله‌ی امن بین ارسال‌ها
            except Exception:
                fail += 1
                log.exception("خطا در ارسال بنر به %s", g.get("title"))
        await update.reply(f"✅ ارسال شد به {ok} گروه." + (f" ({fail} ناموفق)" if fail else ""))
        return

    if text == "تایید ارسال":
        b = data.get("banner")
        if not b or not data["groups"]:
            await update.reply("بنر یا لیست گروه خالی است.")
            return
        ok = 0
        for g in data["groups"]:
            try:
                await client.send_message(g["guid"], b["text"])
                ok += 1
                await asyncio.sleep(2)
            except Exception:
                log.exception("خطا در ارسال بنر به %s", g.get("title"))
        await update.reply(f"✅ بنر به {ok} گروه ارسال شد.")
        return

    if text.startswith("یادآوری بنر روشن"):
        minutes_text = text.replace("یادآوری بنر روشن", "", 1).strip()
        if not minutes_text.isdigit() or int(minutes_text) < 1:
            await update.reply("مثال: یادآوری بنر روشن 30")
            return
        data["banner_reminder"] = {
            "enabled": True, "minutes": int(minutes_text), "last_run": 0,
        }
        save_data(data)
        await update.reply(f"✅ یادآوری بنر هر {minutes_text} دقیقه فعال شد (فقط یادآوری، نه ارسال خودکار).")
        return

    if text == "یادآوری بنر خاموش":
        data["banner_reminder"]["enabled"] = False
        save_data(data)
        await update.reply("🔴 یادآوری بنر خاموش شد.")
        return

    if text == "یادآوری بنر وضعیت":
        br = data["banner_reminder"]
        status = "فعال ✅" if br.get("enabled") else "غیرفعال 🔴"
        await update.reply(f"وضعیت: {status}\nفاصله: هر {br.get('minutes', 0)} دقیقه")
        return

    # ---------- منشی ----------
    if text == "منشی روشن":
        data["auto_reply"]["enabled"] = True
        save_data(data)
        await update.reply("✅ منشی روشن شد.")
        return
    if text == "منشی خاموش":
        data["auto_reply"]["enabled"] = False
        save_data(data)
        await update.reply("🔴 منشی خاموش شد.")
        return
    if text.startswith("منشی متن"):
        msg = text.replace("منشی متن", "", 1).strip()
        data["auto_reply"]["text"] = msg
        save_data(data)
        await update.reply("✅ متن منشی ذخیره شد.")
        return
    if text.startswith("پرسش پاسخ افزودن"):
        rest = text.replace("پرسش پاسخ افزودن", "", 1).strip()
        if "|" not in rest:
            await update.reply("فرمت: پرسش پاسخ افزودن <سوال> | <جواب>")
            return
        q, a = [p.strip() for p in rest.split("|", 1)]
        data["qa"][q] = a
        save_data(data)
        await update.reply("✅ ثبت شد.")
        return
    if text.startswith("پرسش پاسخ حذف"):
        q = text.replace("پرسش پاسخ حذف", "", 1).strip()
        data["qa"].pop(q, None)
        save_data(data)
        await update.reply("🗑 حذف شد.")
        return
    if text == "لیست پرسش پاسخ":
        if not data["qa"]:
            await update.reply("خالی است.")
            return
        lines = [f"«{q}» → «{a}»" for q, a in data["qa"].items()]
        await update.reply("\n".join(lines))
        return

    # ---------- امنیت ----------
    if text == "سکوت روشن":
        data["muted"] = True
        save_data(data)
        await update.reply("🔇 سکوت روشن شد.")
        return
    if text == "سکوت خاموش":
        data["muted"] = False
        save_data(data)
        await update.reply("🔊 سکوت خاموش شد.")
        return
    if text.startswith("افزودن ادمین"):
        guid = text.replace("افزودن ادمین", "", 1).strip()
        if guid and guid not in data["admins"]:
            data["admins"].append(guid)
            save_data(data)
        await update.reply("✅ ادمین اضافه شد.")
        return
    if text.startswith("حذف ادمین"):
        guid = text.replace("حذف ادمین", "", 1).strip()
        if guid in data["admins"]:
            data["admins"].remove(guid)
            save_data(data)
            await update.reply("🗑 ادمین حذف شد.")
        else:
            await update.reply("پیدا نشد.")
        return
    if text == "لیست ادمین‌ها":
        lines = ["👮 ادمین‌ها:"] + [f"- `{a}`" for a in data["admins"]]
        await update.reply("\n".join(lines))
        return

    # ---------- بازی و سرگرمی ----------
    if text == "تاس":
        await update.reply(f"🎲 عدد آمد: {random.randint(1, 6)}")
        return
    if text == "سکه":
        await update.reply(f"🪙 {random.choice(['شیر', 'خط'])}")
        return
    if text.startswith("سنگ کاغذ قیچی"):
        choice = text.replace("سنگ کاغذ قیچی", "", 1).strip()
        options = ["سنگ", "کاغذ", "قیچی"]
        if choice not in options:
            await update.reply("مثال: سنگ کاغذ قیچی سنگ")
            return
        bot_choice = random.choice(options)
        if choice == bot_choice:
            result = "مساوی شد 🤝"
        elif (choice, bot_choice) in [("سنگ", "قیچی"), ("کاغذ", "سنگ"), ("قیچی", "کاغذ")]:
            result = "شما بردید 🎉"
        else:
            result = "من بردم 😄"
        await update.reply(f"شما: {choice} | من: {bot_choice}\n{result}")
        return
    if text == "حدس عدد":
        pending_guess[chat] = random.randint(1, 100)
        await update.reply("عددی بین ۱ تا ۱۰۰ در ذهن دارم؛ فقط عدد حدستان را بفرستید.")
        return
    if text == "چالش":
        quiz = random.choice(QUIZ_BANK)
        opts = "\n".join(f"{L}) {o}" for L, o in zip("ابجد", quiz["options"]))
        await update.reply(f"❓ {quiz['q']}\n{opts}\n\nپاسخ با: پاسخ <الف/ب/ج/د>")
        return
    if text == "جوک":
        await update.reply(random.choice(JOKES))
        return
    if text == "فال":
        await update.reply(random.choice(FORTUNES))
        return

    # ---------- ساعت و تاریخ ----------
    if text == "ساعت":
        try:
            from zoneinfo import ZoneInfo
            import datetime
            now = datetime.datetime.now(ZoneInfo("Asia/Tehran"))
            await update.reply(f"🕒 ساعت: {now.strftime('%H:%M:%S')}")
        except Exception:
            await update.reply("خطا در تعیین ساعت — بسته‌ی tzdata نصب است؟")
        return
    if text == "تاریخ":
        try:
            import jdatetime
            today = jdatetime.date.today()
            await update.reply(f"📅 تاریخ شمسی: {today.strftime('%Y/%m/%d')}")
        except Exception:
            await update.reply("خطا در تعیین تاریخ — بسته‌ی jdatetime نصب است؟")
        return

    # ---------- ابزار ----------
    if text.startswith("حساب"):
        expr = text.replace("حساب", "", 1).strip()
        try:
            result = safe_calc(expr)
            await update.reply(f"= {result}")
        except Exception:
            await update.reply("عبارت نامعتبر است.")
        return

    # ---------- یادداشت ----------
    if text.startswith("یادداشت افزودن"):
        note = text.replace("یادداشت افزودن", "", 1).strip()
        data["notes"].append(note)
        save_data(data)
        await update.reply("✅ یادداشت اضافه شد.")
        return
    if text == "لیست یادداشت‌ها":
        if not data["notes"]:
            await update.reply("خالی است.")
            return
        lines = [f"{i}. {n}" for i, n in enumerate(data["notes"], 1)]
        await update.reply("\n".join(lines))
        return
    if text.startswith("حذف یادداشت"):
        arg = text.replace("حذف یادداشت", "", 1).strip()
        if arg.isdigit() and 1 <= int(arg) <= len(data["notes"]):
            data["notes"].pop(int(arg) - 1)
            save_data(data)
            await update.reply("🗑 حذف شد.")
        else:
            await update.reply("شماره نامعتبر است.")
        return

    # ---------- یادآوری عمومی ----------
    if text.startswith("یادآوری"):
        rest = text.replace("یادآوری", "", 1).strip()
        parts = rest.split(" ", 1)
        if len(parts) < 2 or not parts[0].isdigit():
            await update.reply("مثال: یادآوری 10 زنگ بزن به علی")
            return
        minutes, msg = int(parts[0]), parts[1]
        pending_reminders.append({"chat": chat, "text": msg, "at": time.time() + minutes * 60})
        await update.reply(f"✅ بعد از {minutes} دقیقه یادآوری می‌کنم.")
        return

    # ---------- سیو با برچسب ----------
    if text.startswith("سیو"):
        tag = text.replace("سیو", "", 1).strip()
        reply_msg = getattr(update, "reply_message", None) or getattr(update, "reply_to", None)
        if not tag or not reply_msg:
            await update.reply("این دستور را با ریپلای روی یک پیام و یک برچسب بفرستید: سیو <برچسب>")
            return
        data["saved"][tag] = getattr(reply_msg, "text", "") or ""
        save_data(data)
        await update.reply(f"✅ با برچسب «{tag}» ذخیره شد.")
        return
    if text == "لیست سیو":
        if not data["saved"]:
            await update.reply("خالی است.")
            return
        await update.reply("\n".join(f"- {t}" for t in data["saved"]))
        return
    if text.startswith("نمایش سیو"):
        tag = text.replace("نمایش سیو", "", 1).strip()
        if tag not in data["saved"]:
            await update.reply("پیدا نشد.")
            return
        await update.reply(data["saved"][tag])
        return

    # ---------- پاسخ به چالش ----------
    if text.startswith("پاسخ"):
        await update.reply("اگر برای چالش بود، امیدوارم درست گفته باشید! 🙂")
        return



# ---------------------------------------------------------------------------
# اجرا
# ---------------------------------------------------------------------------

async def main():
    async with client:
        log.info("کلاینت سلف روبیکا متصل شد.")
        asyncio.create_task(background_loop())
        await client.run()


if __name__ == "__main__":
    asyncio.run(main())
