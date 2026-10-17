
import os
import re
import time
import logging
from typing import Optional

import requests
import pytchat


# ==================== SETTINGS ====================

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "").strip()
YOUTUBE_CHANNEL_ID = os.getenv("YOUTUBE_CHANNEL_ID", "").strip()
YOUTUBE_CHANNEL_HANDLE = os.getenv("YOUTUBE_CHANNEL_HANDLE", "").strip()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

# موجود في Secrets، لكن pytchat لا يستخدمه في هذا الكود.
YOUTUBE_COOKIES = os.getenv("YOUTUBE_COOKIES", "").strip()

CHECK_INTERVAL_SECONDS = max(
    60, int(os.getenv("CHECK_INTERVAL_SECONDS", "120"))
)

MAX_RUNTIME_SECONDS = max(
    60, int(os.getenv("MAX_RUNTIME_SECONDS", "17400"))
)

REQUEST_TIMEOUT = 20

# ===================================================


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
        logging.error("إعدادات ناقصة: %s", ", ".join(missing))
        return False

    return True


def resolve_channel_id() -> Optional[str]:
    """تحديد Channel ID من الـ Secret أو من اسم القناة."""

    if YOUTUBE_CHANNEL_ID.startswith("UC") and len(YOUTUBE_CHANNEL_ID) == 24:
        logging.info("تم استخدام YOUTUBE_CHANNEL_ID المحدد في Secrets.")
        return YOUTUBE_CHANNEL_ID

    if not YOUTUBE_CHANNEL_HANDLE:
        logging.error("معرّف القناة غير صالح ولم يتم توفير Handle.")
        return None

    handle = YOUTUBE_CHANNEL_HANDLE.strip()

    if not handle.startswith("@"):
        handle = "@" + handle

    url = "https://www.googleapis.com/youtube/v3/channels"

    try:
        response = SESSION.get(
            url,
            params={
                "part": "id",
                "forHandle": handle,
                "key": YOUTUBE_API_KEY,
            },
            timeout=REQUEST_TIMEOUT,
        )

        response.raise_for_status()
        items = response.json().get("items", [])

        if items:
            channel_id = items[0].get("id")

            if channel_id:
                logging.info("تم تحديد معرّف القناة بنجاح.")
                return channel_id

        logging.error("لم يتم العثور على القناة باستخدام الـ Handle.")

    except requests.HTTPError as exc:
        logging.error("YouTube API رفض تحديد القناة: %s", exc)
        log_api_error(response)
    except (requests.RequestException, ValueError) as exc:
        logging.error("تعذر تحديد معرّف القناة: %s", exc)

    return None


def log_api_error(response) -> None:
    """طباعة تفاصيل الخطأ دون إظهار مفتاح API."""

    try:
        data = response.json()
        error = data.get("error", {})
        logging.error(
            "تفاصيل YouTube API: %s",
            error.get("message", response.text[:300]),
        )
    except Exception:
        logging.error("تفاصيل الرد: %s", response.text[:300])


def extract_video_id_from_channel_page(
    channel_id: str,
) -> Optional[str]:
    """
    البحث عن بث مباشر باستخدام YouTube Data API.
    لا نعتمد على أول فيديو يظهر في صفحة /live،
    لأنه قد يكون فيديو مقترحًا لا يتبع القناة.
    """

    url = "https://www.googleapis.com/youtube/v3/search"

    try:
        response = SESSION.get(
            url,
            params={
                "part": "snippet",
                "channelId": channel_id,
                "type": "video",
                "eventType": "live",
                "maxResults": 10,
                "key": YOUTUBE_API_KEY,
            },
            timeout=REQUEST_TIMEOUT,
        )

        response.raise_for_status()
        data = response.json()

        for item in data.get("items", []):
            video_id = item.get("id", {}).get("videoId")
            owner_channel_id = item.get("snippet", {}).get("channelId")

            # التأكد من أن البث يتبع القناة المطلوبة.
            if video_id and owner_channel_id == channel_id:
                logging.info(
                    "تم العثور على بث تابع للقناة: %s",
                    video_id,
                )
                return video_id

        logging.info("لم يعثر YouTube API على بث مباشر للقناة.")

    except requests.HTTPError as exc:
        logging.error("خطأ HTTP أثناء البحث عن البث: %s", exc)
        log_api_error(response)
    except (requests.RequestException, ValueError) as exc:
        logging.warning("تعذر البحث عن البث المباشر: %s", exc)

    return None


def get_live_video_id(channel_id: str) -> Optional[str]:
    """التحقق من أن الفيديو بث مباشر نشط ويتبع القناة."""

    video_id = extract_video_id_from_channel_page(channel_id)

    if not video_id:
        return None

    url = "https://www.googleapis.com/youtube/v3/videos"

    try:
        response = SESSION.get(
            url,
            params={
                "part": "snippet",
                "id": video_id,
                "key": YOUTUBE_API_KEY,
            },
            timeout=REQUEST_TIMEOUT,
        )

        response.raise_for_status()
        items = response.json().get("items", [])

        if not items:
            logging.warning(
                "لم يتم العثور على بيانات الفيديو: %s",
                video_id,
            )
            return None

        snippet = items[0].get("snippet", {})
        owner_channel_id = snippet.get("channelId")
        broadcast_status = snippet.get("liveBroadcastContent")

        if owner_channel_id != channel_id:
            logging.warning("تم تجاهل فيديو لا يتبع القناة المحددة.")
            return None

        if broadcast_status != "live":
            logging.info(
                "الفيديو ليس بثًا نشطًا حاليًا. الحالة: %s",
                broadcast_status,
            )
            return None

        return video_id

    except requests.HTTPError as exc:
        logging.error("خطأ HTTP أثناء التحقق من البث: %s", exc)
        log_api_error(response)
    except (requests.RequestException, ValueError) as exc:
        logging.warning("تعذر التحقق من الفيديو: %s", exc)

    return None


def contains_target_number(message: str) -> bool:
    """
    مطابقة الرقم 100 أو ١٠٠.
    لا تطابق 1000 باعتباره 100.
    """

    western_match = re.search(r"(?<!\d)100(?!\d)", message)
    arabic_match = re.search(r"(?<![٠-٩])١٠٠(?![٠-٩])", message)

    return western_match is not None or arabic_match is not None


def send_to_telegram(
    message: str,
    author: str,
    video_id: str,
) -> bool:
    """إرسال الرسالة المطابقة إلى Telegram."""

    url = (
        f"https://api.telegram.org/bot"
        f"{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

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

        data = response.json()

        if response.ok and data.get("ok"):
            logging.info("تم إرسال الرسالة إلى Telegram.")
            return True

        logging.error(
            "فشل Telegram: HTTP %s — %s",
            response.status_code,
            data.get("description", "خطأ غير معروف"),
        )

    except (requests.RequestException, ValueError) as exc:
        logging.error("تعذر إرسال الرسالة إلى Telegram: %s", exc)

    return False


def monitor_chat(video_id: str, deadline: float) -> None:
    """مراقبة الشات حتى ينتهي البث أو تنتهي مدة تشغيل البوت."""

    chat = None

    logging.info("محاولة الاتصال بشات البث: %s", video_id)

    try:
        chat = pytchat.create(video_id=video_id)

        if not chat.is_alive():
            logging.warning(
                "تعذر فتح الشات. قد يكون الشات مغلقًا أو غير متاح."
            )
            return

        logging.info(
            "تم الاتصال بالشات؛ تتم مراقبة الرسائل التي تحتوي على 100 أو ١٠٠."
        )

        while time.monotonic() < deadline and chat.is_alive():
            try:
                chat_data = chat.get()

                for item in chat_data.sync_items():
                    message = (item.message or "").strip()

                    if not message:
                        continue

                    author_obj = getattr(item, "author", None)
                    author = getattr(author_obj, "name", "مستخدم")

                    logging.info("شات | %s: %s", author, message)

                    if contains_target_number(message):
                        logging.info("تم العثور على رسالة مطابقة.")
                        send_to_telegram(message, author, video_id)

                time.sleep(2)

            except Exception as exc:
                logging.warning("خطأ مؤقت أثناء قراءة الشات: %s", exc)
                time.sleep(5)

    except Exception as exc:
        logging.warning(
            "فشل الاتصال بشات الفيديو %s: %s",
            video_id,
            exc,
        )

    finally:
        if chat is not None:
            try:
                chat.terminate()
            except Exception:
                pass

        logging.info("انتهت مراقبة الشات لهذا الفيديو.")


def main() -> int:
    logging.info(
        "بدء مراقبة بثوث يوتيوب وإرسال الرسائل المطابقة إلى Telegram."
    )

    if not validate_settings():
        return 1

    channel_id = resolve_channel_id()

    if not channel_id:
        logging.error(
            "تعذر تحديد القناة. راجع YOUTUBE_CHANNEL_ID أو "
            "YOUTUBE_CHANNEL_HANDLE."
        )
        return 1

    logging.info("تم تجهيز القناة للمراقبة.")

    deadline = time.monotonic() + MAX_RUNTIME_SECONDS
    last_video_id = None

    while time.monotonic() < deadline:
        try:
            video_id = get_live_video_id(channel_id)

            if video_id:
                if video_id != last_video_id:
                    logging.info("تم اكتشاف بث مباشر: %s", video_id)
                    last_video_id = video_id

                monitor_chat(video_id, deadline)

            else:
                logging.info(
                    "لا يوجد بث نشط تم اكتشافه؛ ستتم إعادة المحاولة."
                )

        except Exception:
            logging.exception("حدث خطأ غير متوقع أثناء دورة المراقبة.")

        remaining = deadline - time.monotonic()

        if remaining > 0:
            time.sleep(min(CHECK_INTERVAL_SECONDS, remaining))

    logging.info(
        "انتهت مدة تشغيل البوت. سيبدأ التشغيل التالي حسب جدول GitHub Actions."
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
