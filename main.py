import os
import re
import time
from collections import deque
import requests
import yt_dlp

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
YOUTUBE_CHANNEL_HANDLE = os.getenv("YOUTUBE_CHANNEL_HANDLE")

BASE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "ar,en-US;q=0.9,en;q=0.8"
}

def get_live_video_id(channel_handle):
    """استخراج معرف البث المباشر الحالي"""
    handle = channel_handle if channel_handle.startswith("@") else f"@{channel_handle}"
    mobile_url = f"https://m.youtube.com/{handle}/live"
    
    try:
        res = requests.get(mobile_url, headers=BASE_HEADERS, timeout=12, allow_redirects=True)
        if "watch?v=" in res.url:
            return res.url.split("watch?v=")[1].split("&")[0]
        
        match = re.search(r'"videoId":"([^"]+)"', res.text)
        if match and ('"isLive":true' in res.text or '"isLiveNow":true' in res.text or 'LIVE' in res.text):
            return match.group(1)
    except Exception as e:
        print(f"⚠️ خطأ أثناء الفحص المباشر: {e}")

    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'skip_download': True,
        'extractor_args': {'youtube': {'player_client': ['ios', 'mweb']}}
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(f"https://www.youtube.com/{handle}/live", download=False)
            if info and (info.get('is_live') or info.get('live_status') == 'is_live'):
                return info.get('id')
    except Exception as e:
        print(f"⚠️ خطأ أثناء الفحص بـ yt-dlp: {e}")
        
    return None

def get_chat_init_data(video_id):
    """جلب رمز الشات ومفتاح API مباشرة من صفحة شات البث"""
    url = f"https://www.youtube.com/live_chat?v={video_id}"
    try:
        res = requests.get(url, headers=BASE_HEADERS, timeout=10)
        if res.status_code == 200:
            key_match = re.search(r'"INNERTUBE_API_KEY":"([^"]+)"', res.text)
            api_key = key_match.group(1) if key_match else ""

            ver_match = re.search(r'"clientVersion":"([^"]+)"', res.text)
            client_ver = ver_match.group(1) if ver_match else "2.20240301.00.00"

            cont_match = re.search(r'"continuation":"([^"]+)"', res.text)
            continuation = cont_match.group(1) if cont_match else None

            return continuation, api_key, client_ver
    except Exception as e:
        print(f"⚠️ خطأ أثناء جلب صفحة live_chat: {e}")
    
    return None, "", "2.20240301.00.00"

def send_to_telegram(message):
    """إرسال نص السؤال فقط إلى التلجرام"""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message
    }
    try:
        res = requests.post(url, json=payload, timeout=10)
        if res.status_code == 200:
            print(f"🚀 تم إرسال السؤال بنجاح إلى تلجرام: [{message}]")
        else:
            print(f"❌ خطأ من تلجرام ({res.status_code}): {res.text}")
    except Exception as e:
        print(f"❌ خطأ في الاتصال بتلجرام: {e}")

def monitor_live_chat(video_id, max_end_time, processed_ids):
    """قراءة الشات المباشر باستمرار مع إضافة هيدرز يوتيوب المطلوبة"""
    continuation, api_key, client_ver = get_chat_init_data(video_id)
    
    if not continuation:
        print("⚠️ لم نتمكن من الحصول على رمز الشات الحي (قد يكون الشات معطلاً أو مغلقاً في هذا البث).")
        return

    print("🟢 تم الاتصال بشات البث المباشر بنجاح! جاري المراقبة واستقبال الأسئلة...")
    
    innertube_url = f"https://www.youtube.com/youtubei/v1/live_chat/get_live_chat?key={api_key}" if api_key else "https://www.youtube.com/youtubei/v1/live_chat/get_live_chat"
    
    # الهيدرز الإضافية المطلوبة لقراءات InnerTube API
    chat_headers = BASE_HEADERS.copy()
    chat_headers.update({
        "Content-Type": "application/json",
        "X-YouTube-Client-Name": "1",
        "X-YouTube-Client-Version": client_ver
    })

    session = requests.Session()
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
                print(f"⚠️ استجابة غير متوقعة من يوتيوب: {res.status_code}")
                time.sleep(3)
                continue
                
            data = res.json()
            live_chat = data.get("continuationContents", {}).get("liveChatContinuation", {})
            actions = live_chat.get("actions", [])

            for action in actions:
                item = action.get("addChatItemAction", {}).get("item", {})
                renderer = item.get("liveChatMessageRenderer") or item.get("liveChatPaidMessageRenderer")
                
                if renderer:
                    msg_id = renderer.get("id", "")
                    if msg_id and msg_id in processed_ids:
                        continue
                    if msg_id:
                        processed_ids.append(msg_id)

                    runs = renderer.get("message", {}).get("runs", [])
                    msg_text = "".join([r.get("text", "") for r in runs]).strip()
                    author = renderer.get("authorName", {}).get("simpleText", "مستخدم")

                    if msg_text:
                        print(f"💬 [شات]: {author}: {msg_text}")
                        
                        if "?" in msg_text or "؟" in msg_text:
                            print(f"🎯 تم التقاط سؤال جديد: {msg_text}")
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
            print(f"🔴 تم العثور على بث مباشر! Video ID: {video_id}")
            monitor_live_chat(video_id, start_time + max_duration, processed_ids)
        else:
            print("⏳ لا يوجد بث مباشر حالياً. إعادة الفحص بعد دقيقتين...")
            time.sleep(120)

if __name__ == "__main__":
    main()
