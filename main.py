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
    """جلب ID البث المباشر الحقيقي والتأكد أنه حي ومباشر الآن"""
    handle = channel_handle if channel_handle.startswith("@") else f"@{channel_handle}"
    url = f"https://www.youtube.com/{handle}/live"
    
    try:
        res = requests.get(url, headers=HEADERS, timeout=12, allow_redirects=True)
        text = res.text
        
        video_id = None
        if "watch?v=" in res.url:
            video_id = res.url.split("watch?v=")[1].split("&")[0]
        else:
            match = re.search(r'"videoId":"([^"]+)"', text)
            if match:
                video_id = match.group(1)
                
        if not video_id:
            return None

        is_live_now = ('"isLive":true' in text or '"isLiveNow":true' in text or 'LIVE' in text)
        is_upcoming = ('"isUpcoming":true' in text or '"status":"UNPLAYABLE"' in text)

        if is_live_now and not is_upcoming:
            return video_id
            
    except Exception as e:
        print(f"⚠️ خطأ أثناء الفحص عن البث: {e}")
        
    return None

def get_chat_init_data(video_id):
    """استخراج مفتاح الـ API ورمز الشات المباشر"""
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
        print(f"⚠️ خطأ أثناء جلب صفحة الشات: {e}")

    return None, "", "2.20240301.00.00"

def send_to_telegram(message):
    """إرسال نص السؤال/الرسالة مجرداً إلى التلجرام"""
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

def monitor_live_chat(video_id, max_end_time, processed_ids, initial_continuation, api_key, client_ver):
    print(f"🟢 تم الربط بشات البث الحي ({video_id}) بنجاح! جاري مراقبة الرقم 100...")
    
    # ربط مفتاح API بالطلب لتجنب خطأ 400 Bad Request
    if api_key:
        innertube_url = f"https://www.youtube.com/youtubei/v1/live_chat/get_live_chat?key={api_key}"
    else:
        innertube_url = "https://www.youtube.com/youtubei/v1/live_chat/get_live_chat"
        
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

                    author = "مستخدم"
                    if "authorName" in renderer:
                        author = renderer["authorName"].get("simpleText", "مستخدم")

                    msg_text = ""
                    message_obj = renderer.get("message", {})
                    if "runs" in message_obj:
                        msg_text = "".join([r.get("text", "") for r in message_obj["runs"]]).strip()
                    elif "simpleText" in message_obj:
                        msg_text = message_obj["simpleText"].strip()

                    if msg_text:
                        print(f"💬 [شات حي]: {author}: {msg_text}")
                        
                        # التقاط أي رسالة تحتوي على 100 أو ١٠٠
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
        print("🔍 جاري فحص وجود بث مباشر حقيقي...")
        video_id = get_real_live_video_id(YOUTUBE_CHANNEL_HANDLE)
        
        if video_id:
            continuation, api_key, client_ver = get_chat_init_data(video_id)
            if continuation:
                print(f"🔴 تم العثور على بث مباشر حقيقي ونشط الآن! Video ID: {video_id}")
                monitor_live_chat(video_id, start_time + max_duration, processed_ids, continuation, api_key, client_ver)
            else:
                print(f"⏳ الفيديو المكتشف ({video_id}) ليس بثاً حياً أو الشات معطل. إعادة الفحص...")
        else:
            print("⏳ لا يوجد بث مباشر حقيقي حالياً. إعادة الفحص بعد دقيقتين...")
        
        time.sleep(120)

if __name__ == "__main__":
    main()
