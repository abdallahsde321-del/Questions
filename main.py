import os
import re
import time
import logging
from typing import Optional, List
from urllib.parse import urlparse, parse_qs

import requests
import pytchat
import pytchat.util as pytchat_util


# ==================== SETTINGS ====================

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "").strip()
YOUTUBE_CHANNEL_ID = os.getenv("YOUTUBE_CHANNEL_ID", "").strip()
YOUTUBE_CHANNEL_HANDLE = os.getenv("YOUTUBE_CHANNEL_HANDLE", "").strip()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

CHECK_INTERVAL_SECONDS = max(
    60, int(os.getenv("CHECK_INTERVAL_SECONDS", "120"))
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
        missing.append(
            "YOUTUBE_CHANNEL_ID أو YOUTUBE_CHANNEL_HANDLE"
        )

    if not TELEGRAM_BOT_TOKEN:
        missing.append("TELEGRAM_BOT_TOKEN")

    if not TELEGRAM_CHAT_ID:
        missing.append("TELEGRAM_CHAT_ID")

    if missing:
        logging.error(
            "Secrets ناقصة: %s",
            ", ".join(missing),
        )
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
                message = data.get(
                    "error", {}
                ).get("message", response.text[:300])
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
        logging.warning(
            "تعذر طلب YouTube API: %s",
            exc,
        )
        return None


def resolve_channel_id() -> Optional[str]:
    """تحديد معرّف القناة."""

    channel_id = YOUTUBE_CHANNEL_ID

    if channel_id.startswith("UC") and len(channel_id) == 24:
        logging.info("تم تحميل Channel ID من Secrets.")
        return channel_id

    handle = YOUTUBE_CHANNEL_HANDLE.strip()

    if not handle:
        logging.error(
            "Channel ID غير صالح ولم يتم توفير Handle."
        )
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
        logging.error(
            "لم يتم العثور على القناة: %s",
            handle,
        )
        return None

    channel_id = items[0].get("id")

    if channel_id:
        logging.info(
            "تم تحديد معرّف القناة من Handle."
        )

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


def get_candidate_ids_from_live_page(
    channel_id: str,
) -> List[str]:
    """قراءة صفحة البث وجمع الفيديوهات المحتملة."""

    url = (
        f"https://www.youtube.com/channel/"
        f"{channel_id}/live"
    )

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
            parsed = urlparse(response.url)
            query = parse_qs(parsed.query)

            # قد تتحول صفحة /live مباشرة إلى صفحة الفيديو.
            if parsed.path == "/watch" and query.get("v"):
                video_id = query["v"][0]

                if re.fullmatch(
                    r"[a-zA-Z0-9_-]{11}",
                    video_id,
                ):
                    candidates.append(video_id)

            # جمع معرّفات الفيديو المحتملة من الصفحة.
            for video_id in extract_video_ids_from_html(
                response.text
            ):
                if video_id not in candidates:
                    candidates.append(video_id)

    except requests.RequestException as exc:
        logging.warning(
            "تعذر قراءة صفحة البث: %s",
            exc,
        )

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


def search_live_video(
    channel_id: str,
) -> Optional[str]:
    """بحث احتياطي عن بث مباشر تابع للقناة."""

    data = api_get(
