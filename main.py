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
    "tone": "formal",           # "formal" یا "casual"
    "polls": {},                 # {poll_id: {...}}
    "auto_chat_groups": {},      # {group_guid: {"enabled": bool, "last_reply": ts}}
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
pending_math = {}    # {chat_guid: answer}  -> بازی ریاضی سریع
pending_dooz = {}    # {chat_guid: [9 خانه]} -> بازی دوز
group_message_count = {}  # {group_guid: count} -> برای «آمار گروه»
pending_reminders = []  # [{"chat":..., "text":..., "at": ts}]


def render_dooz(board):
    symbols = {" ": "▫️", "X": "❌", "O": "⭕"}
    rows = []
    for r in range(3):
        rows.append("".join(symbols[board[r * 3 + c]] for c in range(3)))
    return "\n".join(rows)


def dooz_winner(board):
    lines = [(0, 1, 2), (3, 4, 5), (6, 7, 8), (0, 3, 6), (1, 4, 7), (2, 5, 8), (0, 4, 8), (2, 4, 6)]
    for a, b, c in lines:
        if board[a] != " " and board[a] == board[b] == board[c]:
            return board[a]
    if " " not in board:
        return "draw"
    return None

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

RIDDLES = [
    {"q": "چه چیزی هر چه بیشتر از آن برداری، بزرگ‌تر می‌شود؟", "a": "گودال/چاله"},
    {"q": "چه چیزی دندان دارد ولی نمی‌جود؟", "a": "شانه"},
    {"q": "چه چیزی همیشه جلوی شماست ولی هرگز نمی‌بینیدش؟", "a": "آینده"},
    {"q": "چه چیزی وقتی می‌شکند، بهتر کار می‌کند؟", "a": "تخم‌مرغ (برای پخت)"},
]

PROVERBS = [
    "آب رفته به جوی بازنمی‌گردد.",
    "تا نباشد چیزکی، مردم نگویند چیزها.",
    "کار نیکو کردن از پر کردن است.",
    "هر که بامش بیش، برفش بیشتر.",
    "دوست آن است که بگیرد دست دوست، در پریشان‌حالی و درماندگی.",
]

FACTS = [
    "قلب یک میگو در سرش قرار دارد 🦐",
    "عسل هرگز فاسد نمی‌شود؛ عسل هزاران‌ساله هنوز قابل خوردن است 🍯",
    "اختاپوس سه تا قلب دارد 🐙",
    "یک روز روی سیاره‌ی زهره از یک سال آن طولانی‌تر است 🪐",
]

MOTIVATIONS = [
    "امروز یه قدم کوچیک بردار، فردا نتیجه‌شو می‌بینی 💪",
    "بهترین زمان برای شروع، همینه که هست ⏳",
    "هر روز یه فرصت تازه‌ست برای بهتر شدن 🌱",
]

RANDOM_NAMES = [
    "آرمان", "پارمیس", "کیانا", "بردیا", "ترانه", "سامان", "نگین", "آرش",
]

TRUTHS = [
    "بزرگ‌ترین ترست چیه؟",
    "یه رازی که تا حالا به کسی نگفتی چیه؟",
    "اگه می‌تونستی یه روز رو دوباره زندگی کنی، کدوم روز رو انتخاب می‌کردی؟",
]

DARES = [
    "یه ایموجی رندوم به‌جای هر حرف پیامت بذار.",
    "یه صدای خنده‌دار ضبط کن و بفرست.",
    "به یکی پیام بده و بگو امروز چقدر باحاله.",
]

MORSE_TABLE = {
    'a': '.-', 'b': '-...', 'c': '-.-.', 'd': '-..', 'e': '.', 'f': '..-.',
    'g': '--.', 'h': '....', 'i': '..', 'j': '.---', 'k': '-.-', 'l': '.-..',
    'm': '--', 'n': '-.', 'o': '---', 'p': '.--.', 'q': '--.-', 'r': '.-.',
    's': '...', 't': '-', 'u': '..-', 'v': '...-', 'w': '.--', 'x': '-..-',
    'y': '-.--', 'z': '--..', '0': '-----', '1': '.----', '2': '..---',
    '3': '...--', '4': '....-', '5': '.....', '6': '-....', '7': '--...',
    '8': '---..', '9': '----.',
}
MORSE_REVERSE = {v: k for k, v in MORSE_TABLE.items()}

# چت خودکار در گروه: برای طبیعی‌ماندن رفتار، فقط با شانس کم و فاصله‌ی زمانی
# جواب می‌دهد، نه به هر پیام — رفتار خیلی سریع/به همه‌چیز، مشکوک و اسپم‌مانند
# به‌نظر می‌رسد و ریسک محدودشدن اکانت را بالا می‌برد.
AUTO_CHAT_REPLY_CHANCE = 0.12
AUTO_CHAT_COOLDOWN_SECONDS = 180

AUTO_CHAT_LINES = [
    "😄 دقیقا!",
    "جالبه، بیشتر بگو",
    "🔥🔥🔥",
    "من که موافقم",
    "هه هه، خوب بود",
    "واقعا؟ باورم نمیشه 😅",
    "این حرفتو قبول دارم",
    "😂😂",
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
چت خودکار روشن <شماره> — بعضی‌وقت‌ها با شانس کم به پیام بچه‌های گروه جواب می‌دهد
چت خودکار خاموش <شماره>

🔹 بنر (فقط دستی — بدون ارسال خودکار تکرارشونده)
ثبت بنر (با ریپلای) | بنر (پیش‌نمایش) | ارسال بنر <شماره یا all>
یادآوری بنر روشن <دقیقه> | یادآوری بنر خاموش | یادآوری بنر وضعیت
تایید ارسال — بعد از دریافت یادآوری، همان بنر را به تمام گروه‌ها می‌فرستد

🔹 منشی
منشی روشن / منشی خاموش / منشی متن <پیام>
تست منشی — پیش‌نمایش پاسخ خودکار (چون خودتان نمی‌توانید برای خودتان تریگرش کنید)
پرسش پاسخ افزودن <سوال> | <جواب> / پرسش پاسخ حذف <سوال> / لیست پرسش پاسخ

🔹 امنیت
سکوت روشن / سکوت خاموش
افزودن ادمین <guid> / حذف ادمین <guid> / لیست ادمین‌ها

🔹 بازی و سرگرمی
تاس / سکه / سنگ کاغذ قیچی <سنگ|کاغذ|قیچی> / حدس عدد / چالش / جوک / فال
چیستان / ضرب المثل / میدونستی / انگیزه / اسم تصادفی / حقیقت / جرات

🔹 ابزار جدید
آمار متن <متن> — تعداد کاراکتر و کلمه
برعکس <متن>
مورس <متن> / رمزگشایی مورس <کد مورس>
رمزعبور بساز <طول عدد، پیش‌فرض ۱۲>
قرعه کشی <گزینه۱> | <گزینه۲> | ...
تبدیل دما <عدد سلسیوس> / تبدیل کیلومتر <عدد> / تبدیل کیلوگرم <عدد>
تبدیل متر <عدد> / تبدیل لیتر <عدد>
محاسبه سن <YYYY-MM-DD>
ساعت شهرها — تهران/لندن/نیویورک/توکیو

🔹 سرگرمی بیشتر
جدول ضرب <عدد>
ریاضی سریع — بعد فقط جواب رو بفرست
دوز — بازی با ربات؛ با عدد ۱ تا ۹ خانه انتخاب کن

🔹 شخصی‌سازی
لحن شوخی / لحن رسمی

🔹 مدیریت گروه (بخشی، بقیه بعداً)
آمار گروه <شماره> — تعداد پیام (از لحظه‌ی روشن‌شدن ربات) + تعداد اعضا (best-effort)
نظرسنجی <شماره گروه> <سؤال> | <گزینه۱> | <گزینه۲> | ...
رای <کد نظرسنجی> <شماره گزینه> — در خود گروه
نتیجه نظرسنجی <کد نظرسنجی>

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

    if is_group_chat and chat:
        group_message_count[chat] = group_message_count.get(chat, 0) + 1

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

    # ---------- بازی ریاضی سریع: اگر منتظر جواب هستیم ----------
    if chat in pending_math and text.lstrip("-").isdigit():
        if int(text) == pending_math[chat]:
            await update.reply("🎉 درست بود!")
        else:
            await update.reply(f"❌ نه، جواب درست {pending_math[chat]} بود.")
        del pending_math[chat]
        return

    # ---------- بازی دوز: اگر منتظر حرکت هستیم ----------
    if chat in pending_dooz and text.isdigit() and 1 <= int(text) <= 9:
        board = pending_dooz[chat]
        pos = int(text) - 1
        if board[pos] != " ":
            await update.reply("این خانه پر است، یکی دیگه انتخاب کن.")
            return
        board[pos] = "X"
        w = dooz_winner(board)
        if w:
            await update.reply(render_dooz(board) + ("\n\n🎉 شما بردید!" if w == "X" else "\n\n🤝 مساوی شد!"))
            del pending_dooz[chat]
            return
        empty = [i for i, v in enumerate(board) if v == " "]
        if empty:
            board[random.choice(empty)] = "O"
        w = dooz_winner(board)
        msg = render_dooz(board)
        if w:
            msg += "\n\n😄 من بردم!" if w == "O" else "\n\n🤝 مساوی شد!"
            del pending_dooz[chat]
        await update.reply(msg)
        return

    # ---------- دیباگ موقت: نشان‌دادن فیلدهای واقعی آبجکت update ----------
    # (بعد از حل شدن مشکل «ثبت بنر»، این بلوک را می‌توانید حذف کنید)
    if text == "دیباگ" and is_admin(sender):
        try:
            all_attrs = [a for a in dir(update) if not a.startswith("_")]
            info = [f"chat={chat}", f"sender={sender}", f"is_group={is_group_chat}"]
            info.append("فیلدهای موجود: " + ", ".join(all_attrs))
            for cand in ("reply_message", "reply_to", "reply_to_message", "message_reply",
                          "replied_message", "reply", "reply_message_id"):
                val = getattr(update, cand, "—ندارد—")
                info.append(f"{cand} = {val!r}")
            await update.reply("\n".join(info)[:3900])
        except Exception as e:
            await update.reply(f"خطا در دیباگ: {e}")
        return

    # ---------- ثبت بنر (هم در گروه، هم در پیوی؛ نیاز به ریپلای) ----------
    if text == "ثبت بنر":
        if not is_admin(sender):
            return
        reply_msg = None
        for cand in ("reply_message", "reply_to", "reply_to_message",
                      "message_reply", "replied_message", "reply"):
            reply_msg = getattr(update, cand, None)
            if reply_msg:
                break
        if not reply_msg:
            await update.reply(
                "این دستور را باید روی یک پیام ریپلای کنید.\n"
                "(اگر مطمئنید ریپلای کرده‌اید ولی باز این پیام را می‌بینید، "
                "روی همان پیام ریپلای کنید و بفرستید «دیباگ» تا مشکل را دقیق پیدا کنیم.)"
            )
            return
        banner_text = (
            getattr(reply_msg, "text", None)
            or getattr(reply_msg, "message", None)
            or ""
        )
        data["banner"] = {"text": banner_text, "set_by": sender}
        save_data(data)
        await update.reply("✅ بنر ذخیره شد.")
        return

    # از اینجا به بعد: در گروه فقط ادمین دستور می‌دهد؛ در پیوی، غیرادمین فقط
    # منشی/پرسش‌وپاسخ می‌گیرد و ادمین به منوی کامل دستورات می‌رسد.
    if is_group_chat:
        if not is_admin(sender):
            ac = data.get("auto_chat_groups", {}).get(chat)
            if ac and ac.get("enabled"):
                now = time.time()
                cooldown_ok = now - ac.get("last_reply", 0) >= AUTO_CHAT_COOLDOWN_SECONDS
                if cooldown_ok and random.random() < AUTO_CHAT_REPLY_CHANCE:
                    ac["last_reply"] = now
                    save_data(data)
                    await update.reply(random.choice(AUTO_CHAT_LINES))
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

    if text.startswith("چت خودکار روشن"):
        idx = find_group_index(text.replace("چت خودکار روشن", "", 1).strip())
        if idx is None:
            await update.reply("مثال: چت خودکار روشن 1")
            return
        g = data["groups"][idx]
        data["auto_chat_groups"][g["guid"]] = {"enabled": True, "last_reply": 0}
        save_data(data)
        await update.reply(
            f"✅ چت خودکار برای «{g['title']}» روشن شد.\n"
            "توجه: فقط گاهی و با فاصله جواب می‌دهد تا طبیعی بماند، نه به هر پیام."
        )
        return

    if text.startswith("چت خودکار خاموش"):
        idx = find_group_index(text.replace("چت خودکار خاموش", "", 1).strip())
        if idx is None:
            await update.reply("مثال: چت خودکار خاموش 1")
            return
        g = data["groups"][idx]
        data["auto_chat_groups"].pop(g["guid"], None)
        save_data(data)
        await update.reply(f"🔴 چت خودکار برای «{g['title']}» خاموش شد.")
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
    if text == "تست منشی":
        ar = data["auto_reply"]
        if data["muted"]:
            await update.reply("منشی غیرفعال است چون «سکوت» روشن است.")
            return
        if not ar["enabled"]:
            await update.reply("منشی خاموش است. اول بزنید: منشی روشن")
            return
        if not ar["text"]:
            await update.reply("متنی برای منشی ثبت نشده. بزنید: منشی متن <پیام>")
            return
        await update.reply(
            "این پیش‌نمایش پاسخ خودکار است (منشی فقط وقتی *شخص دیگری* به "
            "پیوی شما پیام بدهد فعال می‌شود، نه وقتی خودتان به خودتان بنویسید):\n\n"
            + ar["text"]
        )
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

    # ---------- قابلیت‌های جدید (محلی، بدون وابستگی به کتابخانه) ----------
    if text == "چیستان":
        r = random.choice(RIDDLES)
        await update.reply(f"🧩 {r['q']}\n\n(جواب: {r['a']})")
        return
    if text == "ضرب المثل":
        await update.reply(f"📜 {random.choice(PROVERBS)}")
        return
    if text == "میدونستی":
        await update.reply(f"💡 آیا می‌دانستید: {random.choice(FACTS)}")
        return
    if text == "انگیزه":
        await update.reply(f"🔥 {random.choice(MOTIVATIONS)}")
        return
    if text == "اسم تصادفی":
        await update.reply(f"🎭 {random.choice(RANDOM_NAMES)}")
        return
    if text == "حقیقت":
        await update.reply(f"🤫 {random.choice(TRUTHS)}")
        return
    if text == "جرات":
        await update.reply(f"😈 {random.choice(DARES)}")
        return

    if text.startswith("آمار متن"):
        s = text.replace("آمار متن", "", 1).strip()
        if not s:
            await update.reply("مثال: آمار متن سلام دنیا")
            return
        chars = len(s)
        words = len(s.split())
        await update.reply(f"🔤 تعداد کاراکتر: {chars}\n🔠 تعداد کلمه: {words}")
        return

    if text.startswith("برعکس"):
        s = text.replace("برعکس", "", 1).strip()
        if not s:
            await update.reply("مثال: برعکس سلام")
            return
        await update.reply(s[::-1])
        return

    if text.startswith("مورس "):
        s = text.replace("مورس", "", 1).strip().lower()
        try:
            out = " ".join(MORSE_TABLE.get(ch, "?") for ch in s if ch != " ")
            await update.reply(out)
        except Exception:
            await update.reply("فقط حروف/اعداد انگلیسی پشتیبانی می‌شود.")
        return

    if text.startswith("رمزگشایی مورس"):
        s = text.replace("رمزگشایی مورس", "", 1).strip()
        try:
            out = "".join(MORSE_REVERSE.get(code, "?") for code in s.split(" "))
            await update.reply(out)
        except Exception:
            await update.reply("فرمت مورس نامعتبر است.")
        return

    if text.startswith("رمزعبور بساز"):
        arg = text.replace("رمزعبور بساز", "", 1).strip()
        length = int(arg) if arg.isdigit() and 4 <= int(arg) <= 64 else 12
        chars = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789!@#$%"
        pwd = "".join(random.choice(chars) for _ in range(length))
        await update.reply(f"🔐 {pwd}")
        return

    if text.startswith("قرعه کشی"):
        rest = text.replace("قرعه کشی", "", 1).strip()
        options = [o.strip() for o in rest.split("|") if o.strip()]
        if len(options) < 2:
            await update.reply("مثال: قرعه کشی علی | رضا | سارا")
            return
        await update.reply(f"🎯 برنده: {random.choice(options)}")
        return

    if text.startswith("تبدیل دما"):
        arg = text.replace("تبدیل دما", "", 1).strip()
        try:
            c = float(arg)
            f = c * 9 / 5 + 32
            await update.reply(f"{c}°C = {f:.1f}°F")
        except Exception:
            await update.reply("مثال: تبدیل دما 25")
        return

    if text.startswith("تبدیل کیلومتر"):
        arg = text.replace("تبدیل کیلومتر", "", 1).strip()
        try:
            km = float(arg)
            miles = km * 0.621371
            await update.reply(f"{km} کیلومتر = {miles:.2f} مایل")
        except Exception:
            await update.reply("مثال: تبدیل کیلومتر 10")
        return

    if text.startswith("تبدیل کیلوگرم"):
        arg = text.replace("تبدیل کیلوگرم", "", 1).strip()
        try:
            kg = float(arg)
            lbs = kg * 2.20462
            await update.reply(f"{kg} کیلوگرم = {lbs:.2f} پوند")
        except Exception:
            await update.reply("مثال: تبدیل کیلوگرم 70")
        return

    # ---------- سرگرمی بیشتر ----------
    if text.startswith("جدول ضرب"):
        arg = text.replace("جدول ضرب", "", 1).strip()
        if not arg.isdigit():
            await update.reply("مثال: جدول ضرب 7")
            return
        n = int(arg)
        lines = [f"{n} × {i} = {n*i}" for i in range(1, 11)]
        await update.reply("\n".join(lines))
        return

    if text == "ریاضی سریع":
        a, b = random.randint(2, 50), random.randint(2, 50)
        op = random.choice(["+", "-", "*"])
        answer = {"+": a + b, "-": a - b, "*": a * b}[op]
        pending_math[chat] = answer
        await update.reply(f"🧮 {a} {op} {b} = ؟\n(فقط جواب رو بفرست)")
        return

    if text == "دوز":
        pending_dooz[chat] = [" "] * 9
        await update.reply(render_dooz(pending_dooz[chat]) + "\n\nخانه‌ی موردنظر رو با عدد ۱ تا ۹ بفرست.")
        return

    # ---------- ابزار بیشتر ----------
    if text.startswith("محاسبه سن"):
        arg = text.replace("محاسبه سن", "", 1).strip()
        try:
            import datetime
            y, m, d = [int(p) for p in arg.split("-")]
            born = datetime.date(y, m, d)
            today = datetime.date.today()
            age = today.year - born.year - ((today.month, today.day) < (born.month, born.day))
            await update.reply(f"🎂 سن: {age} سال")
        except Exception:
            await update.reply("مثال: محاسبه سن 2000-05-20")
        return

    if text == "ساعت شهرها":
        try:
            from zoneinfo import ZoneInfo
            import datetime
            cities = [
                ("تهران", "Asia/Tehran"), ("لندن", "Europe/London"),
                ("نیویورک", "America/New_York"), ("توکیو", "Asia/Tokyo"),
            ]
            lines = []
            for name, tz in cities:
                now = datetime.datetime.now(ZoneInfo(tz))
                lines.append(f"{name}: {now.strftime('%H:%M')}")
            await update.reply("🌍 " + "\n".join(lines))
        except Exception:
            await update.reply("خطا در تعیین ساعت شهرها.")
        return

    if text.startswith("تبدیل متر"):
        arg = text.replace("تبدیل متر", "", 1).strip()
        try:
            m = float(arg)
            await update.reply(f"{m} متر = {m*3.28084:.2f} فوت")
        except Exception:
            await update.reply("مثال: تبدیل متر 5")
        return

    if text.startswith("تبدیل لیتر"):
        arg = text.replace("تبدیل لیتر", "", 1).strip()
        try:
            l = float(arg)
            await update.reply(f"{l} لیتر = {l*0.264172:.2f} گالن")
        except Exception:
            await update.reply("مثال: تبدیل لیتر 10")
        return

    # ---------- شخصی‌سازی ----------
    if text == "لحن شوخی":
        data["tone"] = "casual"
        save_data(data)
        await update.reply("باشه رفیق، از این به بعد راحت‌تر حرف می‌زنم 😄")
        return
    if text == "لحن رسمی":
        data["tone"] = "formal"
        save_data(data)
        await update.reply("بله، از این پس با لحن رسمی پاسخ می‌دهم.")
        return

    # ---------- مدیریت گروه (best-effort) ----------
    if text.startswith("آمار گروه"):
        idx = find_group_index(text.replace("آمار گروه", "", 1).strip())
        if idx is None:
            await update.reply("مثال: آمار گروه 1")
            return
        g = data["groups"][idx]
        msg_count = group_message_count.get(g["guid"], 0)
        member_info = "نامشخص"
        try:
            info = await client.get_chat(g["guid"])
            member_info = getattr(info, "count_members", None) or getattr(info, "members_count", None) or "نامشخص"
        except Exception:
            pass
        await update.reply(
            f"📊 آمار «{g['title']}»\nپیام‌ها (از لحظه‌ی روشن‌شدن ربات): {msg_count}\nتعداد اعضا: {member_info}"
        )
        return

    if text.startswith("نظرسنجی"):
        rest = text.replace("نظرسنجی", "", 1).strip()
        parts = rest.split(" ", 1)
        if len(parts) < 2 or not parts[0].isdigit():
            await update.reply("مثال: نظرسنجی 1 رنگ مورد علاقه؟ | قرمز | آبی | سبز")
            return
        idx = find_group_index(parts[0])
        if idx is None:
            await update.reply("شماره گروه نامعتبر است.")
            return
        if "|" not in parts[1]:
            await update.reply("مثال: نظرسنجی 1 رنگ مورد علاقه؟ | قرمز | آبی | سبز")
            return
        q_and_opts = [p.strip() for p in parts[1].split("|")]
        question, options = q_and_opts[0], q_and_opts[1:]
        if len(options) < 2:
            await update.reply("حداقل ۲ گزینه لازم است.")
            return
        g = data["groups"][idx]
        poll_id = str(int(time.time()))
        data.setdefault("polls", {})[poll_id] = {
            "guid": g["guid"], "question": question, "options": options,
            "votes": {o: 0 for o in options}, "voted_users": [],
        }
        save_data(data)
        opts_text = "\n".join(f"{i+1}. {o}" for i, o in enumerate(options))
        await client.send_message(
            g["guid"],
            f"📊 نظرسنجی: {question}\n{opts_text}\n\nرای بده با: رای {poll_id} <شماره گزینه>",
        )
        await update.reply(f"✅ نظرسنجی ارسال شد. کد نظرسنجی: {poll_id}")
        return

    if text.startswith("رای "):
        parts = text.split(" ")
        if len(parts) != 3 or parts[1] not in data.get("polls", {}) or not parts[2].isdigit():
            return
        poll = data["polls"][parts[1]]
        if sender in poll["voted_users"]:
            await update.reply("شما قبلاً رای داده‌اید.")
            return
        opt_idx = int(parts[2]) - 1
        if not (0 <= opt_idx < len(poll["options"])):
            await update.reply("شماره گزینه نامعتبر است.")
            return
        poll["votes"][poll["options"][opt_idx]] += 1
        poll["voted_users"].append(sender)
        save_data(data)
        await update.reply("✅ رای شما ثبت شد.")
        return

    if text.startswith("نتیجه نظرسنجی"):
        poll_id = text.replace("نتیجه نظرسنجی", "", 1).strip()
        poll = data.get("polls", {}).get(poll_id)
        if not poll:
            await update.reply("نظرسنجی پیدا نشد.")
            return
        lines = [f"📊 {poll['question']}"] + [f"{o}: {c} رای" for o, c in poll["votes"].items()]
        await update.reply("\n".join(lines))
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
