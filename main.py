import os
import re
import time
import logging
from typing import Optional, List
from urllib.parse import urlparse, parse_qs

import requests
import pytchat


# ==================== SETTINGS ====================

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "").strip()
YOUTUBE_CHANNEL_ID = os.getenv("YOUTUBE_CHANNEL_ID", "").strip()
YOUTUBE_CHANNEL_HANDLE = os.getenv("YOUTUBE_CHANNEL_HANDLE", "").strip()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

CHECK_INTERVAL_SECONDS = max(
    60, int(os.getenv("CHECK_INTERVAL_SECONDS", "300"))
)
MAX_RUNTIME_SECONDS = max(
    60, int(os.getenv("MAX_RUNTIME_SECONDS", "17400"))
)

REQUEST_TIMEOUT = 25

# ==================================================


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/130.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ar,en-US;q=0.9,en;q=0.8",
})


def validate_settings() -> bool:
    missing = []

    if not YOUTUBE_API_KEY:
        missing.append("YOUTUBE_API_KEY")

    if not YOUTUBE_CHANNEL_ID and not YOUTUBE_CHANNEL_HANDLE:
        missing.append("YOUTUBE_CHANNEL_ID أو YOUTUBE_CHANNEL_HANDLE")

    if not TELEGRAM_BOT_TOKEN:
        missing.append("TELEGRAM_BOT_TOKEN")

    if not TELEGRAM_CHAT_ID:
        missing.append("TELEGRAM_CHAT_ID")

    if missing:
        logging.error("Secrets ناقصة: %s", ", ".join(missing))
        return False

    return True


def api_get(endpoint: str, params: dict) -> Optional[dict]:
    """إرسال طلب إلى YouTube Data API مع تسجيل الخطأ."""

    url = f"https://www.googleapis.com/youtube/v3/{endpoint}"
    request_params = dict(params)
    request_params["key"] = YOUTUBE_API_KEY

    try:
        response = SESSION.get(
            url,
            params=request_params,
            timeout=REQUEST_TIMEOUT,
        )

        if not response.ok:
            try:
                data = response.json()
                message = data.get("error", {}).get(
                    "message", response.text[:300]
                )
            except ValueError:
                message = response.text[:300]

            logging.error(
                "YouTube API %s: HTTP %s — %s",
                endpoint,
                response.status_code,
                message,
            )
            return None

        return response.json()

    except (requests.RequestException, ValueError) as exc:
        logging.warning("تعذر طلب YouTube API: %s", exc)
        return None


def resolve_channel_id() -> Optional[str]:
    """تحديد معرّف القناة."""

    channel_id = YOUTUBE_CHANNEL_ID

    if channel_id.startswith("UC") and len(channel_id) == 24:
        logging.info("تم تحميل Channel ID من Secrets.")
        return channel_id

    handle = YOUTUBE_CHANNEL_HANDLE.strip()

    if not handle:
        logging.error("Channel ID غير صالح ولم يتم توفير Handle.")
        return None

    if not handle.startswith("@"):
        handle = "@" + handle

    data = api_get(
        "channels",
        {
            "part": "id",
            "forHandle": handle,
        },
    )

    if not data:
        return None

    items = data.get("items", [])

    if not items:
        logging.error("لم يتم العثور على القناة: %s", handle)
        return None

    channel_id = items[0].get("id")

    if channel_id:
        logging.info("تم تحديد معرّف القناة من Handle.")

    return channel_id


def extract_video_ids_from_html(html: str) -> List[str]:
    """استخراج معرّفات الفيديو المحتملة من صفحة يوتيوب."""

    found = []

    patterns = [
        r'"videoId"\s*:\s*"([a-zA-Z0-9_-]{11})"',
        r'"video_id"\s*:\s*"([a-zA-Z0-9_-]{11})"',
        r'youtube\.com/watch\?v=([a-zA-Z0-9_-]{11})',
        r'youtu\.be/([a-zA-Z0-9_-]{11})',
    ]

    for pattern in patterns:
        for video_id in re.findall(pattern, html):
            if video_id not in found:
                found.append(video_id)

    return found


def get_candidate_ids_from_live_page(channel_id: str) -> List[str]:
    """قراءة صفحة البث وجمع الفيديوهات المحتملة."""

    url = f"https://www.youtube.com/channel/{channel_id}/live"
    candidates = []

    try:
        response = SESSION.get(
            url,
            timeout=REQUEST_TIMEOUT,
            allow_redirects=True,
        )

        logging.info(
            "صفحة البث استجابت بكود HTTP %s.",
            response.status_code,
        )

        if response.ok:
            # أحيانًا تتحول صفحة /live مباشرة إلى صفحة الفيديو.
            parsed = urlparse(response.url)
            query = parse_qs(parsed.query)

            if parsed.path == "/watch" and query.get("v"):
                video_id = query["v"][0]
                if re.fullmatch(r"[a-zA-Z0-9_-]{11}", video_id):
                    candidates.append(video_id)

            # اجمع المعرّفات من HTML، لكن لا تثق بها قبل التحقق.
            for video_id in extract_video_ids_from_html(response.text):
                if video_id not in candidates:
                    candidates.append(video_id)

    except requests.RequestException as exc:
        logging.warning("تعذر قراءة صفحة البث: %s", exc)

    logging.info(
        "عدد معرّفات الفيديو المحتملة من الصفحة: %d",
        len(candidates),
    )

    return candidates[:30]


def validate_live_video(
    video_id: str,
    channel_id: str,
) -> bool:
    """التحقق من تبعية الفيديو للقناة وأنه بث مباشر نشط."""

    data = api_get(
        "videos",
        {
            "part": "snippet",
            "id": video_id,
        },
    )

    if not data:
        return False

    items = data.get("items", [])

    if not items:
        return False

    snippet = items[0].get("snippet", {})

    if snippet.get("channelId") != channel_id:
        return False

    if snippet.get("liveBroadcastContent") != "live":
        return False

    return True


def search_live_video(channel_id: str) -> Optional[str]:
    """بحث احتياطي عن بث مباشر تابع للقناة."""

    data = api_get(
        "search",
        {
            "part": "snippet",
            "channelId": channel_id,
            "type": "video",
            "eventType": "live",
            "maxResults": 10,
        },
    )

    if not data:
        return None

    for item in data.get("items", []):
        video_id = item.get("id", {}).get("videoId")
        owner_id = item.get("snippet", {}).get("channelId")

        if not video_id or owner_id != channel_id:
            continue

        if validate_live_video(video_id, channel_id):
            return video_id

    return None


def get_live_video_id(channel_id: str) -> Optional[str]:
    """اكتشاف بث القناة والتحقق منه."""

    # الطريقة الأولى: صفحة البث.
    candidates = get_candidate_ids_from_live_page(channel_id)

    for video_id in candidates:
        if validate_live_video(video_id, channel_id):
            logging.info(
                "تم العثور على بث نشط من صفحة القناة: %s",
                video_id,
            )
            return video_id

    logging.info(
        "لم يتم تأكيد بث من صفحة القناة؛ تجربة بحث YouTube API."
    )

    # الطريقة الثانية: البحث في YouTube API.
    video_id = search_live_video(channel_id)

    if video_id:
        logging.info("تم العثور على بث نشط باستخدام البحث: %s", video_id)
        return video_id

    logging.warning(
        "لم يتم تأكيد بث نشط تابع للقناة. "
        "قد يكون البث غير ظاهر في الصفحة أو بيانات API."
    )

    return None


def contains_target_number(message: str) -> bool:
    """مطابقة 100 أو ١٠٠ دون مطابقة رقم أطول مثل 1000."""

    return bool(
        re.search(r"(?<!\d)100(?!\d)", message)
        or re.search(r"(?<![٠-٩])١٠٠(?![٠-٩])", message)
    )


def send_to_telegram(
    message: str,
    author: str,
    video_id: str,
) -> bool:
    """إرسال الرسالة المطابقة إلى تيليجرام."""

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    text = (
        "🔴 رسالة مطابقة من شات يوتيوب\n"
        f"المستخدم: {author}\n"
        f"الرسالة: {message}\n"
        f"https://www.youtube.com/watch?v={video_id}"
    )

    try:
        response = SESSION.post(
            url,
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": text,
                "disable_web_page_preview": True,
            },
            timeout=REQUEST_TIMEOUT,
        )

        try:
            data = response.json()
        except ValueError:
            data = {}

        if response.ok and data.get("ok"):
            logging.info("تم إرسال الرسالة إلى Telegram.")
            return True

        logging.error(
            "فشل إرسال Telegram: HTTP %s — %s",
            response.status_code,
            data.get("description", response.text[:300]),
        )

    except requests.RequestException as exc:
        logging.error("تعذر الاتصال بـ Telegram: %s", exc)

    return False


def monitor_chat(video_id: str, deadline: float) -> None:
    """قراءة رسائل الشات حتى ينتهي البث أو وقت التشغيل."""

    chat = None

    logging.info("جارٍ الاتصال بشات الفيديو: %s", video_id)

    try:
        chat = pytchat.create(video_id=video_id)

        if not chat.is_alive():
            logging.warning(
                "لم يبدأ pytchat؛ قد يكون الشات غير متاح لهذا الفيديو."
            )
            return

        logging.info("اتصل البوت بالشات بنجاح.")

        while time.monotonic() < deadline and chat.is_alive():
            try:
                chat_data = chat.get()

                for item in chat_data.sync_items():
                    message = (item.message or "").strip()

                    if not message:
                        continue

                    author_obj = getattr(item, "author", None)
                    author = getattr(author_obj, "name", "مستخدم")

                    logging.info("الشات | %s: %s", author, message)

                    if contains_target_number(message):
                        logging.info("تم العثور على رسالة تحتوي على 100 أو ١٠٠.")
                        send_to_telegram(message, author, video_id)

                time.sleep(2)

            except Exception as exc:
                logging.warning("خطأ في قراءة الشات: %s", exc)
                time.sleep(5)

        if not chat.is_alive():
            logging.info("انتهى الشات أو أصبح غير متاح.")

    except Exception as exc:
        logging.exception("تعذر الاتصال بالشات: %s", exc)

    finally:
        if chat is not None:
            try:
                chat.terminate()
            except Exception:
                pass


def main() -> int:
    logging.info("بدء بوت مراقبة بث يوتيوب وإرسال الرسائل إلى Telegram.")

    if not validate_settings():
        return 1

    channel_id = resolve_channel_id()

    if not channel_id:
        logging.error("تعذر تحديد القناة. راجع Secrets.")
        return 1

    deadline = time.monotonic() + MAX_RUNTIME_SECONDS
    last_video_id = None

    logging.info("تم تجهيز القناة للمراقبة.")

    while time.monotonic() < deadline:
        try:
            video_id = get_live_video_id(channel_id)

            if video_id:
                if video_id != last_video_id:
                    logging.info("البث الحالي: %s", video_id)
                    last_video_id = video_id

                monitor_chat(video_id, deadline)

            else:
                logging.info(
                    "لم يتم العثور على بث مؤكد؛ إعادة المحاولة بعد %s ثانية.",
                    CHECK_INTERVAL_SECONDS,
                )

        except Exception:
            logging.exception("حدث خطأ غير متوقع في دورة المراقبة.")

        remaining = deadline - time.monotonic()

        if remaining > 0:
            time.sleep(min(CHECK_INTERVAL_SECONDS, remaining))

    logging.info("انتهت مدة تشغيل البوت.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
