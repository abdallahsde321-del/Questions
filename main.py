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

def get_live_chat_id():
    """جلب ID البث المباشر و activeLiveChatId فوراً وبأقل استهلاك كوتا"""
    target = YOUTUBE_CHANNEL_HANDLE
    if not target:
        print("⚠️ لم يتم تحديد YOUTUBE_CHANNEL_HANDLE أو YOUTUBE_CHANNEL_ID في Secrets")
        return None, None

    if target.startswith("UC") and len(target) == 24:
        url = f"https://www.youtube.com/channel/{target}/live"
    else:
        handle = target if target.startswith("@") else f"@{target}"
        url = f"https://www.youtube.com/{handle}/live"

    video_id = None
    try:
        res = requests.get(url, headers=HEADERS, timeout=10, allow_redirects=True)
        if "watch?v=" in res.url:
            video_id = res.url.split("watch?v=")[1].split("&")[0]
        else:
            match = re.search(r'"videoId":"([^"]+)"', res.text)
            if match:
                video_id = match.group(1)
    except Exception as e:
        print(f"⚠️ خطأ أثناء جلب رابط البث: {e}")
        return None, None

    if not video_id:
        return None, None

    # التأكد من API جوجل الرسمي أن الفيديو بث مباشر شغال فعلياً + جلب activeLiveChatId
    api_url = f"https://www.googleapis.com/youtube/v3/videos?part=snippet,liveStreamingDetails&id={video_id}&key={YOUTUBE_API_KEY}"
    try:
        res = requests.get(api_url, timeout=10)
        if res.status_code == 200:
            data = res.json()
            items = data.get("items", [])
            if items:
                item = items[0]
                live_status = item.get("snippet", {}).get("liveBroadcastContent")
                live_details = item.get("liveStreamingDetails", {})
                chat_id = live_details.get("activeLiveChatId")

                if live_status == "live" and chat_id:
                    return video_id, chat_id
    except Exception as e:
        print(f"⚠️ خطأ أثناء التحقق من API الرسمي: {e}")

    return None, None

def send_to_telegram(message):
    """إرسال نص الرسالة مجرداً إلى التلجرام بدون أي إضافات"""
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

def monitor_live_chat(video_id, live_chat_id, max_end_time, processed_ids):
    print(f"🟢 تم العثور على بث حي ونشط وتأكيده عبر API الرسمية ({video_id})! جاري قراءة الشات...")
    
    next_page_token = None
    last_heartbeat = time.time()

    while time.time() < max_end_time:
        chat_url = f"https://www.googleapis.com/youtube/v3/liveChat/messages?liveChatId={live_chat_id}&part=snippet,authorDetails&key={YOUTUBE_API_KEY}"
        if next_page_token:
            chat_url += f"&pageToken={next_page_token}"

        try:
            res = requests.get(chat_url, timeout=10)
            if res.status_code != 200:
                print(f"⚠️ استجابة غير متوقعة من API: {res.status_code}")
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
                print("📡 البوت متصل ويستمع عبر API جوجل الرسمي...")
                last_heartbeat = time.time()

            time.sleep(max(polling_interval, 2.0))

        except Exception as e:
            print(f"❌ خطأ أثناء قراءة الشات عبر API: {e}")
            time.sleep(5)

def main():
    print("👀 بدء مراقبة القناة عبر نظام الربط الهجين المطور...")
    start_time = time.time()
    max_duration = 5.5 * 3600
    processed_ids = deque(maxlen=5000)

    while (time.time() - start_time) < max_duration:
        print("🔍 جاري فحص وجود بث مباشر...")
        video_id, live_chat_id = get_live_chat_id()
        
        if video_id and live_chat_id:
            print(f"🔴 تم العثور على بث حي شغال! Video ID: {video_id} | Chat ID: {live_chat_id}")
            monitor_live_chat(video_id, live_chat_id, start_time + max_duration, processed_ids)
        else:
            print("⏳ لا يوجد بث مباشر شغال حالياً. إعادة الفحص بعد دقيقتين...")
        
        time.sleep(120)

if __name__ == "__main__":
    main()
