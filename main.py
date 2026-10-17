import os
import re
import time
import logging
from typing import Optional, Set

import requests
import pytchat

# Required GitHub Actions secrets:
# YOUTUBE_API_KEY, YOUTUBE_CHANNEL_ID or YOUTUBE_CHANNEL_HANDLE,
# TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "").strip()
YOUTUBE_CHANNEL_ID = os.getenv("YOUTUBE_CHANNEL_ID", "").strip()
YOUTUBE_CHANNEL_HANDLE = os.getenv("YOUTUBE_CHANNEL_HANDLE", "").strip()
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
YOUTUBE_COOKIES = os.getenv("YOUTUBE_COOKIES", "").strip()  # Reserved; pytchat does not use this value.

CHECK_INTERVAL_SECONDS = int(os.getenv("CHECK_INTERVAL_SECONDS", "120"))
MAX_RUNTIME_SECONDS = int(os.getenv("MAX_RUNTIME_SECONDS", str(4 * 3600 + 50 * 60)))
REQUEST_TIMEOUT = 15

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ar,en-US;q=0.9,en;q=0.8",
}
SESSION = requests.Session()
SESSION.headers.update(HEADERS)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


def validate_settings() -> bool:
    missing = []
    if not YOUTUBE_API_KEY:
        missing.append("YOUTUBE_API_KEY")
    if not (YOUTUBE_CHANNEL_ID or YOUTUBE_CHANNEL_HANDLE):
        missing.append("YOUTUBE_CHANNEL_ID أو YOUTUBE_CHANNEL_HANDLE")
    if not TELEGRAM_BOT_TOKEN:
        missing.append("TELEGRAM_BOT_TOKEN")
    if not TELEGRAM_CHAT_ID:
        missing.append("TELEGRAM_CHAT_ID")
    if missing:
        logging.error("إعدادات ناقصة: %s", ", ".join(missing))
        return False
    return True


def resolve_channel_id() -> Optional[str]:
    """Use the supplied channel ID, or resolve a @handle with YouTube Data API."""
    if YOUTUBE_CHANNEL_ID.startswith("UC") and len(YOUTUBE_CHANNEL_ID) == 24:
        return YOUTUBE_CHANNEL_ID

    if not YOUTUBE_CHANNEL_HANDLE:
        logging.error("YOUTUBE_CHANNEL_ID غير صالح ولم يتم توفير YOUTUBE_CHANNEL_HANDLE.")
        return None

    handle = YOUTUBE_CHANNEL_HANDLE.strip()
    if not handle.startswith("@"):
        handle = "@" + handle

    url = "https://www.googleapis.com/youtube/v3/channels"
    try:
        response = SESSION.get(
            url,
            params={"part": "id", "forHandle": handle, "key": YOUTUBE_API_KEY},
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        items = response.json().get("items", [])
        if items:
            channel_id = items[0].get("id")
            logging.info("تم تحديد Channel ID من الـ handle.")
            return channel_id
        logging.error("لم يتم العثور على القناة باستخدام YOUTUBE_CHANNEL_HANDLE=%s", handle)
    except requests.RequestException as exc:
        logging.warning("تعذر تحديد معرّف القناة عبر API: %s", exc)
    except ValueError:
        logging.warning("رد غير مفهوم من YouTube API أثناء تحديد القناة.")
    return None


def extract_video_id_from_channel_page(channel_id: str) -> Optional[str]:
    """Read the channel's /live redirect/page; returns a candidate video ID only."""
    url = f"https://www.youtube.com/channel/{channel_id}/live"
    try:
        response = SESSION.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
        response.raise_for_status()

        match = re.search(r"(?:youtube\.com/watch\?v=|/watch\?v=)([A-Za-z0-9_-]{11})", response.url)
        if match:
            return match.group(1)

        # The page may embed the currently selected live video more than once.
        patterns = (
            r'"videoId":"([A-Za-z0-9_-]{11})"',
            r'"video_id":"([A-Za-z0-9_-]{11})"',
        )
        for pattern in patterns:
            match = re.search(pattern, response.text)
            if match:
                return match.group(1)
    except requests.RequestException as exc:
        logging.warning("تعذر فحص صفحة البث في يوتيوب: %s", exc)
    return None


def get_live_video_id(channel_id: str) -> Optional[str]:
    """Find a candidate from the channel page and verify it through YouTube API."""
    video_id = extract_video_id_from_channel_page(channel_id)
    if not video_id:
        return None

    url = "https://www.googleapis.com/youtube/v3/videos"
    try:
        response = SESSION.get(
            url,
            params={
                "part": "snippet,liveStreamingDetails",
                "id": video_id,
                "key": YOUTUBE_API_KEY,
            },
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        items = response.json().get("items", [])
        if not items:
            logging.info("الفيديو المرشح %s غير ظاهر في YouTube API.", video_id)
            return None

        item = items[0]
        snippet = item.get("snippet", {})
        status = snippet.get("liveBroadcastContent")
        owner_channel_id = snippet.get("channelId")

        if owner_channel_id != channel_id:
            logging.warning("تم تجاهل فيديو لا يتبع القناة المحددة.")
            return None
        if status != "live":
            logging.info("الفيديو %s ليس بثًا حيًا نشطًا (الحالة: %s).", video_id, status)
            return None

        return video_id
    except requests.RequestException as exc:
        logging.warning("تعذر التحقق من حالة البث عبر YouTube API: %s", exc)
    except ValueError:
        logging.warning("رد غير مفهوم من YouTube API أثناء التحقق من البث.")
    return None


def send_to_telegram(message: str, author: str, video_id: str) -> bool:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logging.error("بيانات Telegram غير موجودة.")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    text = (
        "🔴 رسالة مطابقة من شات يوتيوب\n"
        f"القناة: {author}\n"
        f"الرسالة: {message}\n"
        f"https://www.youtube.com/watch?v={video_id}"
    )
    try:
        response = SESSION.post(
            url,
            json={"chat_id": TELEGRAM_CHAT_ID, "text": text, "disable_web_page_preview": True},
            timeout=REQUEST_TIMEOUT,
        )
        data = response.json()
        if response.ok and data.get("ok"):
            logging.info("تم إرسال الرسالة المطابقة إلى Telegram.")
            return True
        logging.error("Telegram رفض الرسالة: HTTP %s — %s", response.status_code, data.get("description", "unknown error"))
    except (requests.RequestException, ValueError) as exc:
        logging.error("فشل إرسال الرسالة إلى Telegram: %s", exc)
    return False


def contains_target_number(message: str) -> bool:
    # Match the exact number 100 (Arabic or Western digits), not 1000.
    return re.search(r"(?<!\d)100(?!\d)", message) is not None or \
           re.search(r"(?<![٠-٩])١٠٠(?![٠-٩])", message) is not None


def monitor_chat(video_id: str, deadline: float) -> None:
    logging.info("محاولة الاتصال بشات البث: %s", video_id)
    chat = None
    try:
        chat = pytchat.create(video_id=video_id)
        if not chat.is_alive():
            logging.warning("pytchat لم يتمكن من فتح الشات لهذا البث.")
            return

        logging.info("تم الاتصال بالشات. البحث عن الرسائل التي تحتوي على 100 أو ١٠٠.")
        while time.monotonic() < deadline and chat.is_alive():
            try:
                for item in chat.get().sync_items():
                    message = (item.message or "").strip()
                    author = getattr(getattr(item, "author", None), "name", "مستخدم")
                    logging.info("شات | %s: %s", author, message)
                    if contains_target_number(message):
                        logging.info("تم العثور على رسالة مطابقة.")
                        send_to_telegram(message, author, video_id)
                time.sleep(2)
            except Exception as exc:
                logging.warning("تعذر جلب رسائل الشات مؤقتًا: %s", exc)
                time.sleep(5)
    except Exception as exc:
        logging.warning("فشل pytchat مع الفيديو %s: %s", video_id, exc)
    finally:
        if chat is not None:
            try:
                chat.terminate()
            except Exception:
                pass


def main() -> int:
    logging.info("بدء مراقبة بثوث القناة وإرسال الرسائل المطابقة إلى Telegram.")
    if not validate_settings():
        return 1

    channel_id = resolve_channel_id()
    if not channel_id:
        logging.error("تعذر تحديد Channel ID. راجع YOUTUBE_CHANNEL_ID وYOUTUBE_CHANNEL_HANDLE.")
        return 1

    logging.info("بدأت مراقبة القناة. ستُعاد محاولة اكتشاف البث كل %s ثانية.", CHECK_INTERVAL_SECONDS)
    deadline = time.monotonic() + MAX_RUNTIME_SECONDS
    last_video_id = None

    while time.monotonic() < deadline:
        video_id = get_live_video_id(channel_id)
        if video_id:
            if video_id != last_video_id:
                logging.info("تم اكتشاف بث مباشر نشط: %s", video_id)
                last_video_id = video_id
            monitor_chat(video_id, deadline)
        else:
            logging.info("لا يوجد بث مباشر نشط أو تعذر اكتشافه؛ ستتم إعادة المحاولة.")

        remaining = deadline - time.monotonic()
        if remaining > 0:
            time.sleep(min(CHECK_INTERVAL_SECONDS, remaining))

    logging.info("انتهت مدة التشغيل المحددة؛ سيبدأ التشغيل التالي حسب جدول GitHub Actions.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
