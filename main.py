import os
import re
import time
from collections import deque
import requests

# لم نعد بحاجة لمفتاح Google API، الاعتماد كلياً على اسم القناة
YOUTUBE_CHANNEL_HANDLE = os.getenv("YOUTUBE_CHANNEL_HANDLE") or os.getenv("YOUTUBE_CHANNEL_ID")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "ar,en-US;q=0.9,en;q=0.8"
}

def fetch_video_id(target):
    """التقاط البث المباشر (هذه الخطوة تعمل لديك بنجاح)"""
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
    except Exception:
        pass
    return None

def find_chat_continuation(data):
    """خوارزمية البحث الذكية: تبحث عن رمز الشات في أي مكان داخل بيانات يوتيوب لتجنب تغييرات المسارات"""
    if isinstance(data, dict):
        for key in ["reloadContinuationData", "timedContinuationData", "liveChatReplayContinuationData"]:
            if key in data and "continuation" in data[key]:
                return data[key]["continuation"]
        for value in data.values():
            res = find_chat_continuation(value)
            if res:
                return res
    elif isinstance(data, list):
        for item in data:
            res = find_chat_continuation(item)
            if res:
                return res
    return None

def get_innertube_continuation(video_id):
    """جلب رمز الشات المباشر باستخدام الخوارزمية الذكية"""
    url = "https://www.youtube.com/youtubei/v1/next"
    payload = {
        "context": {
            "client": {
                "clientName": "WEB",
                "clientVersion": "2.20240301.01.00"
            }
        },
        "videoId": video_id
    }
    
    try:
        res = requests.post(url, json=payload, headers=HEADERS, timeout=10)
        if res.status_code == 200:
            continuation = find_chat_continuation(res.json())
            if continuation:
                return continuation
    except Exception as e:
        print(f"⚠️ خطأ أثناء طلب InnerTube: {e}")

    # محاولة احتياطية
    try:
        res = requests.get(f"https://www.youtube.com/live_chat?v={video_id}", headers=HEADERS, timeout=10)
        conts = re.findall(r'"continuation":"([^"]+)"', res.text)
        for c in conts:
            if len(c) > 20:
                return c
    except Exception:
        pass

    return None

def send_to_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message}
    try:
        res = requests.post(url, json=payload, timeout=10)
        if res.status_code == 200:
            print(f"🚀 تم الإرسال للتلجرام بنجاح: [{message}]")
    except Exception:
        pass

def monitor_live_chat(video_id, max_end_time, processed_ids, initial_continuation):
    print(f"🟢 تم فك تشفير الشات بنجاح ({video_id})! جاري التقاط الرقم 100...")
    innertube_url = "https://www.youtube.com/youtubei/v1/live_chat/get_live_chat"
    
    chat_headers = HEADERS.copy()
    chat_headers.update({
        "Content-Type": "application/json",
        "X-YouTube-Client-Name": "1",
        "X-YouTube-Client-Version": "2.20240301.01.00"
    })
    
    session = requests.Session()
    continuation = initial_continuation
    last_heartbeat = time.time()

    while time.time() < max_end_time and continuation:
        payload = {
            "context": {"client": {"clientName": "WEB", "clientVersion": "2.20240301.01.00"}},
            "continuation": continuation
        }
        try:
            res = session.post(innertube_url, json=payload, headers=chat_headers, timeout=10)
            if res.status_code != 200:
                time.sleep(3)
                continue
            
            data = res.json()
            actions = data.get("continuationContents", {}).get("liveChatContinuation", {}).get("actions", [])
            
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

            # استخدام الخوارزمية الذكية لتحديث الكود والاستمرار
            new_continuation = find_chat_continuation(data)
            if new_continuation:
                continuation = new_continuation
            else:
                break # الشات توقف

            if time.time() - last_heartbeat > 30:
                print("📡 البوت متصل ويستمع لشات البث المباشر الآن...")
                last_heartbeat = time.time()
                
        except Exception as e:
            print(f"❌ خطأ أثناء قراءة الشات: {e}")
            time.sleep(3)
        time.sleep(2)

def main():
    print("👀 بدء تشغيل نظام المراقبة النهائي (بالخوارزمية الذكية)...")
    start_time = time.time()
    max_duration = 5.5 * 3600
    processed_ids = deque(maxlen=5000)

    while (time.time() - start_time) < max_duration:
        target = YOUTUBE_CHANNEL_HANDLE
        if not target:
            print("❌ لم يتم العثور على اسم القناة (YOUTUBE_CHANNEL_HANDLE)!")
            time.sleep(120)
            continue

        video_id = fetch_video_id(target)
        if video_id:
            print(f"🎯 تم التقاط Video ID: {video_id}")
            continuation = get_innertube_continuation(video_id)
            
            if continuation:
                monitor_live_chat(video_id, start_time + max_duration, processed_ids, continuation)
                print("🔄 توقف البث أو الشات، سنعيد الفحص...")
            else:
                print(f"⚠️ لا يمكن قراءة الشات للفيديو ({video_id}). (قد يكون الشات مغلقاً بالكامل، أو الفيديو ليس بثاً مباشراً يعمل الآن).")
        else:
            print("⏳ لا يوجد بث مباشر حقيقي حالياً. إعادة الفحص بعد دقيقتين...")

        time.sleep(120)

if __name__ == "__main__":
    main()
