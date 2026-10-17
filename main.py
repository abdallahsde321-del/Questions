import os
import re
import time
from collections import deque
import requests
import yt_dlp

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
YOUTUBE_CHANNEL_HANDLE = os.getenv("YOUTUBE_CHANNEL_HANDLE")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "ar,en-US;q=0.9,en;q=0.8"
}

def get_live_video_id(channel_handle):
    """استخراج ID البث المباشر باستخدام yt-dlp والهيدرز المحمولة لتجاوز حظر السيرفرات"""
    handle = channel_handle if channel_handle.startswith("@") else f"@{channel_handle}"
    
    mobile_url = f"https://m.youtube.com/{handle}/live"
    mobile_headers = {
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1",
        "Accept-Language": "ar,en-US;q=0.9,en;q=0.8"
    }
    
    try:
        response = requests.get(mobile_url, headers=mobile_headers, timeout=12, allow_redirects=True)
        if "watch?v=" in response.url:
            return response.url.split("watch?v=")[1].split("&")[0]
            
        match = re.search(r'"videoId":"([^"]+)"', response.text)
        if match and ('"isLive":true' in response.text or '"isLiveNow":true' in response.text or 'LIVE' in response.text):
            return match.group(1)
    except Exception as e:
        print(f"⚠️ خطأ أثناء الفحص المباشر: {e}")

    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'skip_download': True,
        'extractor_args': {
            'youtube': {
                'player_client': ['ios', 'mweb']
            }
        }
    }
    
    url = f"https://www.youtube.com/{handle}/live"
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if info and (info.get('is_live') or info.get('live_status') == 'is_live'):
                return info.get('id')
    except Exception as e:
        print(f"⚠️ خطأ أثناء الفحص بـ yt-dlp: {e}")
        
    return None

def get_initial_continuation(video_id):
    """جلب رمز التتبع (Continuation) للبدء في قراءة شات البث عبر InnerTube API"""
    url = f"https://www.youtube.com/watch?v={video_id}"
    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
        match = re.search(r'"reloadContinuationData":\s*\{\s*"continuation":\s*"([^"]+)"', res.text)
        if match:
            return match.group(1)
        
        match_generic = re.search(r'"continuation":\s*"(D4Sm[^"]+)"', res.text)
        if match_generic:
            return match_generic.group(1)
            
        match_any = re.search(r'"continuation":\s*"([^"]+)"', res.text)
        if match_any:
            return match_any.group(1)
    except Exception as e:
        print(f"⚠️ خطأ أثناء جلب رمز الشات: {e}")
    return None

def send_to_telegram(message):
    """إرسال نص السؤال فقط بدون أي إضافات"""
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
    """قراءة الشات المباشر عبر API المباشر بدون مكتبات خارجية قد تتعطل"""
    continuation = get_initial_continuation(video_id)
    if not continuation:
        print("⚠️ لم يتم العثور على شات حي متاح له؛ قد يكون الشات معطلاً أو متوقفا.")
        return

    print("🟢 تم الاتصال بشات البث المباشر بنجاح! جاري مراقبة الأسئلة...")
    
    innertube_url = "https://www.youtube.com/youtubei/v1/live_chat/get_live_chat"
    session = requests.Session()

    while time.time() < max_end_time and continuation:
        payload = {
            "context": {
                "client": {
                    "clientName": "WEB",
                    "clientVersion": "2.20240301.00.00"
                }
            },
            "continuation": continuation
        }
        
        try:
            res = session.post(innertube_url, json=payload, headers=HEADERS, timeout=10)
            if res.status_code != 200:
                print(f"⚠️ استجابة شات غير متوقعة: {res.status_code}")
                time.sleep(3)
                continue
                
            data = res.json()
            live_chat = data.get("continuationContents", {}).get("liveChatContinuation", {})
            actions = live_chat.get("actions", [])

            for action in actions:
                item = action.get("addChatItemAction", {}).get("item", {})
                renderer = item.get("liveChatMessageRenderer")
                if renderer:
                    msg_id = renderer.get("id", "")
                    if msg_id and msg_id in processed_ids:
                        continue
                    if msg_id:
                        processed_ids.append(msg_id)

                    runs = renderer.get("message", {}).get("runs", [])
                    msg_text = "".join([r.get("text", "") for r in runs]).strip()
                    author = renderer.get("authorName", {}).get("simpleText", "مجهول")

                    if msg_text:
                        print(f"💬 [شات]: {author}: {msg_text}")
                        
                        if "?" in msg_text or "؟" in msg_text:
                            print(f"🎯 تم التقاط سؤال: {msg_text}")
                            send_to_telegram(msg_text)

            # تحديث رمز الجلب القادم
            continuations = live_chat.get("continuations", [])
            continuation = None
            if continuations:
                cont_data = continuations[0]
                for key in ["timedContinuationData", "invalidationContinuationData", "liveChatReplayContinuationData", "reloadContinuationData"]:
                    if key in cont_data and "continuation" in cont_data[key]:
                        continuation = cont_data[key]["continuation"]
                        break
                        
        except Exception as e:
            print(f"❌ خطأ أثناء قراءة الشات: {e}")
            time.sleep(3)
            
        time.sleep(2)

def main():
    print(f"👀 بدء مراقبة القناة: {YOUTUBE_CHANNEL_HANDLE}")
    
    start_time = time.time()
    max_duration = 5.5 * 3600  # 5 ساعات ونصف
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
