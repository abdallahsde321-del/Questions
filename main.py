import os
import re
import time
from collections import deque
import requests

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
YOUTUBE_CHANNEL_HANDLE = os.getenv("YOUTUBE_CHANNEL_HANDLE") or os.getenv("YOUTUBE_CHANNEL_ID")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "ar,en-US;q=0.9,en;q=0.8"
}

def fetch_video_id(target):
    """استخراج معرف الفيديو للبث المباشر"""
    if target.startswith("UC") and len(target) == 24:
        url = f"https://www.youtube.com/channel/{target}/live"
    else:
        handle = target if target.startswith("@") else f"@{target}"
        url = f"https://www.youtube.com/{handle}/live"

    try:
        res = requests.get(url, headers=HEADERS, timeout=10, allow_redirects=True)
        if "watch?v=" in res.url:
            return res.url.split("watch?v=")[1].split("&")[0]
        match = re.search(r'"videoId":"([^"]+)"', res.text)
        if match:
            return match.group(1)
    except Exception as e:
        print(f"⚠️ خطأ أثناء استخراج Video ID: {e}")
    return None

def get_innertube_continuation(video_id):
    """استخراج رمز التتبع للشات المباشر عبر InnerTube"""
    url = f"https://www.youtube.com/live_chat?v={video_id}"
    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
        if res.status_code == 200:
            text = res.text
            key_match = re.search(r'"INNERTUBE_API_KEY":"([^"]+)"', text)
            api_key = key_match.group(1) if key_match else ""
            ver_match = re.search(r'"clientVersion":"([^"]+)"', text)
            client_ver = ver_match.group(1) if ver_match else "2.20240301.00.00"
            conts = re.findall(r'"continuation":"([^"]+)"', text)
            continuation = None
            for c in conts:
                if len(c) > 20:
                    continuation = c
                    break
            return continuation, api_key, client_ver
    except Exception as e:
        print(f"⚠️ خطأ جلب بيانات InnerTube: {e}")
    return None, "", "2.20240301.00.00"

def get_google_api_chat_id(video_id):
    """التحقق وجلب Chat ID عبر Google API الرسمية"""
    if not YOUTUBE_API_KEY:
        return None
    api_url = f"https://www.googleapis.com/youtube/v3/videos?part=snippet,liveStreamingDetails&id={video_id}&key={YOUTUBE_API_KEY}"
    try:
        res = requests.get(api_url, timeout=10)
        if res.status_code == 200:
            data = res.json()
            items = data.get("items", [])
            if items:
                live_details = items[0].get("liveStreamingDetails", {})
                return live_details.get("activeLiveChatId")
    except Exception as e:
        print(f"⚠️ خطأ Google API: {e}")
    return None

def send_to_telegram(message):
    """إرسال النص المكتشف إلى التلجرام مجرداً"""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message}
    try:
        res = requests.post(url, json=payload, timeout=10)
        if res.status_code == 200:
            print(f"🚀 تم الإرسال للتلجرام بنجاح: [{message}]")
        else:
            print(f"❌ خطأ من تلجرام ({res.status_code}): {res.text}")
    except Exception as e:
        print(f"❌ خطأ اتصال بتلجرام: {e}")

def monitor_innertube(video_id, max_end_time, processed_ids, initial_continuation, api_key, client_ver):
    """مراقبة الشات عبر نظام InnerTube الاحتياطي"""
    print(f"🟢 تم الربط بشات البث عبر InnerTube ({video_id})! جاري التقاط الرقم 100...")
    innertube_url = f"https://www.youtube.com/youtubei/v1/live_chat/get_live_chat?key={api_key}" if api_key else "https://www.youtube.com/youtubei/v1/live_chat/get_live_chat"
    chat_headers = HEADERS.copy()
    chat_headers.update({
        "Content-Type": "application/json",
        "X-YouTube-Client-Name": "1",
        "X-YouTube-Client-Version": client_ver
    })
    session = requests.Session()
    continuation = initial_continuation
    last_heartbeat = time.time()

    while time.time() < max_end_time and continuation:
        payload = {
            "context": {"client": {"clientName": "WEB", "clientVersion": client_ver}},
            "continuation": continuation
        }
        try:
            res = session.post(innertube_url, json=payload, headers=chat_headers, timeout=10)
            if res.status_code != 200:
                time.sleep(3)
                continue
            data = res.json()
            live_chat = data.get("continuationContents", {}).get("liveChatContinuation", {})
            actions = live_chat.get("actions", [])
            for action in actions:
                item = action.get("addChatItemAction", {}).get("item", {})
                renderer = item.get("liveChatMessageRenderer") or item.get("liveChatTextMessageRenderer") or item.get("liveChatPaidMessageRenderer")
                if renderer:
                    msg_id = renderer.get("id", "")
                    if msg_id and msg_id in processed_ids:
                        continue
                    if msg_id:
                        processed_ids.append(msg_id)
                    author = renderer.get("authorName", {}).get("simpleText", "مستخدم")
                    runs = renderer.get("message", {}).get("runs", [])
                    msg_text = "".join([r.get("text", "") for r in runs]).strip()
                    if msg_text:
                        print(f"💬 [شات حي]: {author}: {msg_text}")
                        if "100" in msg_text or "١٠٠" in msg_text:
                            print(f"🎯 تم التقاط رسالة (100): {msg_text}")
                            send_to_telegram(msg_text)

            continuations = live_chat.get("continuations", [])
            continuation = None
            if continuations:
                cont_data = continuations[0]
                for key in ["timedContinuationData", "invalidationContinuationData", "liveChatReplayContinuationData", "reloadContinuationData"]:
                    if key in cont_data and "continuation" in cont_data[key]:
                        continuation = cont_data[key]["continuation"]
                        break
            if time.time() - last_heartbeat > 30:
                print("📡 البوت متصل ويستمع لشات البث المباشر الآن...")
                last_heartbeat = time.time()
        except Exception as e:
            print(f"❌ خطأ أثناء قراءة الشات: {e}")
            time.sleep(3)
        time.sleep(2)

def monitor_google_api(video_id, live_chat_id, max_end_time, processed_ids):
    """مراقبة الشات عبر Google API الرسمية"""
    print(f"🟢 تم الربط بشات البث عبر Google API ({video_id})! جاري التقاط الرقم 100...")
    next_page_token = None
    last_heartbeat = time.time()
    while time.time() < max_end_time:
        chat_url = f"https://www.googleapis.com/youtube/v3/liveChat/messages?liveChatId={live_chat_id}&part=snippet,authorDetails&key={YOUTUBE_API_KEY}"
        if next_page_token:
            chat_url += f"&pageToken={next_page_token}"
        try:
            res = requests.get(chat_url, timeout=10)
            if res.status_code != 200:
                time.sleep(5)
                continue
            data = res.json()
            next_page_token = data.get("nextPageToken")
            polling_interval = data.get("pollingIntervalMillis", 2000) / 1000.0
            items = data.get("items", [])
            for item in items:
                msg_id = item.get("id")
                if msg_id in processed_ids:
                    continue
                processed_ids.append(msg_id)
                snippet = item.get("snippet", {})
                author_details = item.get("authorDetails", {})
                author = author_details.get("displayName", "مستخدم")
                msg_text = snippet.get("displayMessage", "").strip()
                if msg_text:
                    print(f"💬 [شات حي]: {author}: {msg_text}")
                    if "100" in msg_text or "١٠٠" in msg_text:
                        print(f"🎯 تم التقاط رسالة (100): {msg_text}")
                        send_to_telegram(msg_text)
            if time.time() - last_heartbeat > 30:
                print("📡 البوت متصل ومستمر في قراءة الشات...")
                last_heartbeat = time.time()
            time.sleep(max(polling_interval, 2.0))
        except Exception as e:
            print(f"❌ خطأ أثناء قراءة الشات عبر API: {e}")
            time.sleep(5)

def main():
    print("👀 بدء تشغيل نظام المراقبة الهجين...")
    start_time = time.time()
    max_duration = 5.5 * 3600
    processed_ids = deque(maxlen=5000)

    while (time.time() - start_time) < max_duration:
        target = YOUTUBE_CHANNEL_HANDLE
        if not target:
            print("❌ لم يتم العثور على YOUTUBE_CHANNEL_HANDLE أو YOUTUBE_CHANNEL_ID!")
            time.sleep(120)
            continue

        video_id = fetch_video_id(target)
        if video_id:
            print(f"🎯 تم التقاط Video ID: {video_id}")
            # 1. المحاولة الأولى عبر Google API
            live_chat_id = get_google_api_chat_id(video_id)
            if live_chat_id:
                monitor_google_api(video_id, live_chat_id, start_time + max_duration, processed_ids)
            else:
                # 2. التبديل التلقائي لـ InnerTube في حال تعذر الحصول على Chat ID من Google API
                print("🔄 لم نتمكن من الحصول على Chat ID من Google API، جاري الانتقال التلقائي إلى نظام InnerTube...")
                continuation, api_key, client_ver = get_innertube_continuation(video_id)
                if continuation:
                    monitor_innertube(video_id, start_time + max_duration, processed_ids, continuation, api_key, client_ver)
                else:
                    print(f"⏳ تعذر الحصول على رمز الشات للفيديو ({video_id}). إعادة الفحص...")
        else:
            print("⏳ لا يوجد بث مباشر حقيقي حالياً. إعادة الفحص بعد دقيقتين...")

        time.sleep(120)

if __name__ == "__main__":
    main()
