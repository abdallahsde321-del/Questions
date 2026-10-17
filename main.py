import os
import time
from collections import deque
import requests

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
YOUTUBE_CHANNEL_ID = os.getenv("YOUTUBE_CHANNEL_ID")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def get_live_video_details():
    """جلب ID البث المباشر النشط حالياً ومعرف الشات المباشر عبر API جوجل الرسمي"""
    search_url = (
        f"https://www.googleapis.com/youtube/v3/search"
        f"?part=snippet&channelId={YOUTUBE_CHANNEL_ID}&eventType=live&type=video&key={YOUTUBE_API_KEY}"
    )
    try:
        res = requests.get(search_url, timeout=10)
        if res.status_code == 200:
            data = res.json()
            items = data.get("items", [])
            if items:
                video_id = items[0]["id"]["videoId"]
                
                # جلب activeLiveChatId الخاص بالبث المباشر
                video_url = (
                    f"https://www.googleapis.com/youtube/v3/videos"
                    f"?part=liveStreamingDetails&id={video_id}&key={YOUTUBE_API_KEY}"
                )
                v_res = requests.get(video_url, timeout=10)
                if v_res.status_code == 200:
                    v_data = v_res.json()
                    v_items = v_data.get("items", [])
                    if v_items:
                        live_chat_id = v_items[0].get("liveStreamingDetails", {}).get("activeLiveChatId")
                        return video_id, live_chat_id
    except Exception as e:
        print(f"⚠️ خطأ أثناء الاتصال بـ YouTube API: {e}")
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

def monitor_live_chat(live_chat_id, max_end_time, processed_ids):
    print(f"🟢 تم الربط بشات البث المباشر عبر API الرسمي! جاري الاستماع للرقم 100...")
    
    next_page_token = None
    last_heartbeat = time.time()

    while time.time() < max_end_time:
        chat_url = (
            f"https://www.googleapis.com/youtube/v3/liveChat/messages"
            f"?liveChatId={live_chat_id}&part=snippet,authorDetails&key={YOUTUBE_API_KEY}"
        )
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
                    
                    # التقاط أي رسالة تحتوي على 100 بالإنجليزي أو ١٠٠ بالعربي
                    if "100" in msg_text or "١٠٠" in msg_text:
                        print(f"🎯 تم التقاط رسالة تحتوي على (100): {msg_text}")
                        send_to_telegram(msg_text)

            if time.time() - last_heartbeat > 30:
                print("📡 البوت متصل ويستمع عبر API جوجل الرسمي...")
                last_heartbeat = time.time()

            time.sleep(max(polling_interval, 2.0))

        except Exception as e:
            print(f"❌ خطأ أثناء قراءة الشات عبر API: {e}")
            time.sleep(5)

def main():
    print(f"👀 بدء مراقبة القناة عبر API الرسمي (Channel ID: {YOUTUBE_CHANNEL_ID})")
    start_time = time.time()
    max_duration = 5.5 * 3600
    processed_ids = deque(maxlen=5000)

    while (time.time() - start_time) < max_duration:
        print("🔍 جاري فحص وجود بث مباشر حقيقي عبر API الرسمية...")
        video_id, live_chat_id = get_live_video_details()
        
        if video_id and live_chat_id:
            print(f"🔴 تم العثور على بث حي ونشط! Video ID: {video_id} | Chat ID: {live_chat_id}")
            monitor_live_chat(live_chat_id, start_time + max_duration, processed_ids)
        else:
            print("⏳ لا يوجد بث مباشر حقيقي حالياً. إعادة الفحص بعد دقيقتين...")
        
        time.sleep(120)

if __name__ == "__main__":
    main()
