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

# إنشاء ملف الكوكيز عند التشغيل
if YOUTUBE_COOKIES:
    with open(COOKIE_FILE, "w", encoding="utf-8") as f:
        f.write(YOUTUBE_COOKIES)

session = requests.Session()
if os.path.exists(COOKIE_FILE):
    try:
        cj = http.cookiejar.MozillaCookieJar(COOKIE_FILE)
        cj.load(ignore_discard=True, ignore_expires=True)
        session.cookies = cj
    except Exception as e:
        print(f"⚠️ تعذر تحميل الكوكيز: {e}")

BASE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "ar,en-US;q=0.9,en;q=0.8"
}

def get_live_video_id(channel_handle):
    handle = channel_handle if channel_handle.startswith("@") else f"@{channel_handle}"
    url = f"https://www.youtube.com/{handle}/live"
    
    try:
        res = session.get(url, headers=BASE_HEADERS, timeout=12, allow_redirects=True)
        if "watch?v=" in res.url:
            return res.url.split("watch?v=")[1].split("&")[0]
        match = re.search(r'"videoId":"([^"]+)"', res.text)
        if match:
            return match.group(1)
    except Exception as e:
        print(f"⚠️ خطأ أثناء جلب رابط البث: {e}")

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
    url = f"https://www.youtube.com/live_chat?v={video_id}"
    try:
        res = session.get(url, headers=BASE_HEADERS, timeout=10)
        if res.status_code == 200:
            key_match = re.search(r'"INNERTUBE_API_KEY":"([^"]+)"', res.text)
            api_key = key_match.group(1) if key_match else ""

            ver_match = re.search(r'"clientVersion":"([^"]+)"', res.text)
            client_ver = ver_match.group(1) if ver_match else "2.20240301.00.00"

            conts = re.findall(r'"continuation":"([^"]+)"', res.text)
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
    print(f"🟢 تم الاتصال بشات البث الحقيقي ({video_id}) بنجاح! جاري التقاط الرسائل التي تحتوي على 100...")
    
    innertube_url = f"https://www.youtube.com/youtubei/v1/live_chat/get_live_chat?key={api_key}" if api_key else "https://www.youtube.com/youtubei/v1/live_chat/get_live_chat"
    
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
                print(f"⚠️ استجابة غير متوقعة: {res.status_code}")
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
                        
                        # التقاط أي رسالة تتضمن الرقم 100 بالإنجليزي أو ١٠٠ بالعربي
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

def main():
    print(f"👀 بدء مراقبة القناة: {YOUTUBE_CHANNEL_HANDLE}")
    start_time = time.time()
    max_duration = 5.5 * 3600
    processed_ids = deque(maxlen=5000)

    while (time.time() - start_time) < max_duration:
        print("🔍 جاري فحص وجود بث مباشر...")
        video_id = get_live_video_id(YOUTUBE_CHANNEL_HANDLE)
        
        if video_id:
            continuation, api_key, client_ver = get_chat_init_data(video_id)
            if continuation:
                print(f"🔴 تم العثور على بث مباشر حقيقي وشغال! Video ID: {video_id}")
                monitor_live_chat(video_id, start_time + max_duration, processed_ids, continuation, api_key, client_ver)
            else:
                print(f"⏳ الفيديو المكتشف ({video_id}) ليس بثاً حياً أو الشات غير متاح حالياً. إعادة الفحص...")
        else:
            print("⏳ لا يوجد بث مباشر حالياً. إعادة الفحص بعد دقيقتين...")
        
        time.sleep(120)

if __name__ == "__main__":
    main()
