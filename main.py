import os
import re
import time
from collections import deque
import requests

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
YOUTUBE_CHANNEL_HANDLE = os.getenv("YOUTUBE_CHANNEL_HANDLE")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "ar,en-US;q=0.9,en;q=0.8"
}

def get_real_live_video_id(channel_handle):
    """استخراج معرف الفيديو وتأكيد أنه بث مباشر حقيقي جاري الآن"""
    handle = channel_handle if channel_handle.startswith("@") else f"@{channel_handle}"
    url = f"https://www.youtube.com/{handle}/live"
    
    video_id = None
    try:
        res = requests.get(url, headers=HEADERS, timeout=12, allow_redirects=True)
        if "watch?v=" in res.url:
            video_id = res.url.split("watch?v=")[1].split("&")[0]
        else:
            match = re.search(r'<link rel="canonical" href="https://www.youtube.com/watch\?v=([^"]+)"', res.text)
            if match:
                video_id = match.group(1)
            else:
                match_base = re.search(r'"canonicalBaseUrl":"/watch\?v=([^"]+)"', res.text)
                if match_base:
                    video_id = match_base.group(1)
    except Exception as e:
        print(f"⚠️ خطأ أثناء فحص رابط القناة: {e}")
        return None

    if not video_id:
        return None

    # فحص صريح للتأكد من أن الفيديو بث مباشر فعلي شغال حالياً
    player_url = "https://www.youtube.com/youtubei/v1/player"
    payload = {
        "context": {
            "client": {
                "clientName": "WEB",
                "clientVersion": "2.20240301.00.00"
            }
        },
        "videoId": video_id
    }
    
    try:
        check_res = requests.post(player_url, json=payload, headers=HEADERS, timeout=10)
        if check_res.status_code == 200:
            data = check_res.json()
            details = data.get("videoDetails", {})
            is_live = details.get("isLive", False) or details.get("isLiveContent", False)
            
            if is_live:
                return video_id
    except Exception as e:
        print(f"⚠️ خطأ أثناء تأكيد حالة البث: {e}")

    return None

def get_chat_init_data(video_id):
    """جلب رمز التتبع الخاص بالشات ومفتاح API"""
    url = f"https://www.youtube.com/live_chat?v={video_id}"
    try:
        res = requests.get(url, headers=HEADERS, timeout=10)
        if res.status_code == 200:
            key_match = re.search(r'"INNERTUBE_API_KEY":"([^"]+)"', res.text)
            api_key = key_match.group(1) if key_match else ""

            ver_match = re.search(r'"clientVersion":"([^"]+)"', res.text)
            client_ver = ver_match.group(1) if ver_match else "2.20240301.00.00"

            cont_match = re.search(r'"continuation":"([^"]+)"', res.text)
            continuation = cont_match.group(1) if cont_match else None

            return continuation, api_key, client_ver
    except Exception as e:
        print(f"⚠️ خطأ أثناء جلب شات الفيديو: {e}")
    
    return None, "", "2.20240301.00.00"

def send_to_telegram(message):
    """إرسال نص السؤال فقط إلى التلجرام بدون أي إضافات"""
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
        print(f"❌ خطأ في الاتصال بتلجرام: {e}")

def monitor_live_chat(video_id, max_end_time, processed_ids):
    """قراءة ومراقبة الشات المباشر وإرسال الأسئلة"""
    continuation, api_key, client_ver = get_chat_init_data(video_id)
    
    if not continuation:
        print("⚠️ لم نتمكن من الحصول على رمز الشات (قد يكون الشات مغلقاً في هذا البث).")
        return

    print(f"🟢 تم الاتصال بشات البث الحقيقي ({video_id}) بنجاح! جاري الاستماع...")
    
    innertube_url = f"https://www.youtube.com/youtubei/v1/live_chat/get_live_chat?key={api_key}" if api_key else "https://www.youtube.com/youtubei/v1/live_chat/get_live_chat"
    
    chat_headers = HEADERS.copy()
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
                print(f"⚠️ استجابة غير متوقعة: {res.status_code}")
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
        video_id = get_real_live_video_id(YOUTUBE_CHANNEL_HANDLE)
        
        if video_id:
            print(f"🔴 تم العثور على بث مباشر حقيقي! Video ID: {video_id}")
            monitor_live_chat(video_id, start_time + max_duration, processed_ids)
        else:
            print("⏳ لا يوجد بث مباشر حقيقي حالياً. إعادة الفحص بعد دقيقتين...")
            time.sleep(120)

if __name__ == "__main__":
    main()
