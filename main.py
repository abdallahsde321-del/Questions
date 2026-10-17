import os
import re
import time
import http.cookiejar
from collections import deque
import requests
import yt_dlp

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
YOUTUBE_CHANNEL_HANDLE = os.getenv("YOUTUBE_CHANNEL_HANDLE")
YOUTUBE_COOKIES = os.getenv("YOUTUBE_COOKIES")

COOKIE_FILE = "cookies.txt"

# 1. تهيئة الكوكيز إذا كانت متوفرة
if YOUTUBE_COOKIES:
    with open(COOKIE_FILE, "w", encoding="utf-8") as f:
        f.write(YOUTUBE_COOKIES)

session = requests.Session()
if os.path.exists(COOKIE_FILE):
    try:
        cj = http.cookiejar.MozillaCookieJar(COOKIE_FILE)
        cj.load(ignore_discard=True, ignore_expires=True)
        session.cookies = cj
        print("🍪 تم تحميل الكوكيز وتفعيل الجلسة بنجاح!")
    except Exception as e:
        print(f"⚠️ تعذر تحميل الكوكيز: {e}")

# 2. إعداد هيدرز متصفح حقيقي وعميل يوتيوب
BASE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "ar,en-US;q=0.9,en;q=0.8"
}

def get_live_video_id(channel_handle):
    """استخراج معرف البث المباشر بدقة مع دعم الكوكيز والهيدرز"""
    handle = channel_handle if channel_handle.startswith("@") else f"@{channel_handle}"
    urls = [
        f"https://www.youtube.com/{handle}/live",
        f"https://m.youtube.com/{handle}/live"
    ]
    
    for url in urls:
        try:
            res = session.get(url, headers=BASE_HEADERS, timeout=12, allow_redirects=True)
            text = res.text
            
            if "watch?v=" in res.url:
                return res.url.split("watch?v=")[1].split("&")[0]
            
            match = re.search(r'"videoId":"([^"]+)"', text)
            if match:
                is_live = ('"isLive":true' in text or '"isLiveNow":true' in text or 'LIVE' in text)
                is_upcoming = ('"isUpcoming":true' in text or '"status":"UNPLAYABLE"' in text)
                if is_live and not is_upcoming:
                    return match.group(1)
        except Exception as e:
            print(f"⚠️ خطأ أثناء جلب الرابط ({url}): {e}")

    # محاولة احتياطية بأداة yt-dlp مع ملف الكوكيز
    ydl_opts = {'quiet': True, 'no_warnings': True, 'skip_download': True}
    if os.path.exists(COOKIE_FILE):
        ydl_opts['cookiefile'] = COOKIE_FILE

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(f"https://www.youtube.com/{handle}/live", download=False)
            if info and info.get('id'):
                return info.get('id')
    except Exception as e:
        print(f"⚠️ خطأ yt-dlp: {e}")
        
    return None

def get_chat_init_data(video_id):
    """استخراج مفتاح API ورمز التتبع للشات مع الكوكيز"""
    url = f"https://www.youtube.com/live_chat?v={video_id}"
    try:
        res = session.get(url, headers=BASE_HEADERS, timeout=10)
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
        print(f"⚠️ خطأ جلب بيانات الشات: {e}")
        
    return None, "", "2.20240301.00.00"

def send_to_telegram(message):
    """إرسال نص الرسالة فقط لتلجرام مجرداً من أي أسماء أو إضافات"""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message
    }
    try:
        res = requests.post(url, json=payload, timeout=10)
        if res.status_code == 200:
            print(f"🚀 تم الإرسال للتلجرام بنجاح: [{message}]")
        else:
            print(f"❌ خطأ من تلجرام ({res.status_code}): {res.text}")
    except Exception as e:
        print(f"❌ خطأ اتصال بتلجرام: {e}")

def parse_message_renderer(renderer):
    if not renderer:
        return "", ""
    
    author = "مستخدم"
    if "authorName" in renderer:
        author = renderer["authorName"].get("simpleText", "مستخدم")
        
    msg_text = ""
    message_obj = renderer.get("message", {})
    if "runs" in message_obj:
        msg_text = "".join([r.get("text", "") for r in message_obj["runs"]]).strip()
    elif "simpleText" in message_obj:
        msg_text = message_obj["simpleText"].strip()
        
    return author, msg_text

def monitor_live_chat(video_id, max_end_time, processed_ids, initial_continuation, api_key, client_ver):
    print(f"🟢 تم الربط بشات البث الحي ({video_id}) بالدمج الكامل (الكوكيز + الجلسة)! جاري المراقبة...")
    
    # استخدام مفتاح API لمنع أخطاء 400 Bad Request
    if api_key:
        innertube_url = f"https://www.youtube.com/youtubei/v1/live_chat/get_live_chat?key={api_key}"
    else:
        innertube_url = "https://www.youtube.com/youtubei/v1/live_chat/get_live_chat"
        
    chat_headers = BASE_HEADERS.copy()
    chat_headers.update({
        "Content-Type": "application/json",
        "X-YouTube-Client-Name": "1",
        "X-YouTube-Client-Version": client_ver
    })

    continuation = initial_continuation
    last_heartbeat = time.time()

    while time.time() < max_end_time and continuation:
        payload = {
            "context": {
                "client": {
                    "clientName": "WEB",
                    "clientVersion": client_ver
                }
            },
            "continuation": continuation
        }
        
        try:
            res = session.post(innertube_url, json=payload, headers=chat_headers, timeout=10)
            if res.status_code != 200:
                print(f"⚠️ استجابة غير متوقعة من يوتيوب ({res.status_code})")
                time.sleep(3)
                continue
                
            data = res.json()
            live_chat = data.get("continuationContents", {}).get("liveChatContinuation", {})
            actions = live_chat.get("actions", [])

            for action in actions:
                item = action.get("addChatItemAction", {}).get("item", {})
                
                renderer = (
                    item.get("liveChatMessageRenderer") or
                    item.get("liveChatTextMessageRenderer") or
                    item.get("liveChatPaidMessageRenderer")
                )
                
                if renderer:
                    msg_id = renderer.get("id", "")
                    if msg_id and msg_id in processed_ids:
                        continue
                    if msg_id:
                        processed_ids.append(msg_id)

                    author, msg_text = parse_message_renderer(renderer)

                    if msg_text:
                        print(f"💬 [شات حي]: {author}: {msg_text}")
                        
                        # التقاط أي رسالة تتضمن الرقم 100 بالإنجليزية أو ١٠٠ بالعربية
                        if "100" in msg_text or "١٠٠" in msg_text:
                            print(f"🎯 تم التقاط رسالة تحتوي على (100): {msg_text}")
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
                print("📡 البوت متصل ومستمر في الاستماع لشات البث المباشر...")
                last_heartbeat = time.time()

        except Exception as e:
            print(f"❌ خطأ أثناء قراءة الشات: {e}")
            time.sleep(3)
            
        time.sleep(2)

def main():
    print(f"👀 بدء مراقبة القناة: {YOUTUBE_CHANNEL_HANDLE}")
    start_time = time.time()
    max_duration = 5.5 * 3600
    processed_ids = deque(maxlen=5000)

    while (time.time() - start_time) < max_duration:
        print("🔍 جاري فحص وجود بث مباشر حقيقي...")
        video_id = get_live_video_id(YOUTUBE_CHANNEL_HANDLE)
        
        if video_id:
            continuation, api_key, client_ver = get_chat_init_data(video_id)
            if continuation:
                print(f"🔴 تم العثور على بث مباشر حقيقي وشغال! Video ID: {video_id}")
                monitor_live_chat(video_id, start_time + max_duration, processed_ids, continuation, api_key, client_ver)
            else:
                print(f"⏳ الفيديو المكتشف ({video_id}) ليس بثاً حياً أو الشات غير متاح حالياً. إعادة الفحص بعد دقيقتين...")
        else:
            print("⏳ لا يوجد بث مباشر حالياً. إعادة الفحص بعد دقيقتين...")
        
        time.sleep(120)

if __name__ == "__main__":
    main()
