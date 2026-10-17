import os
import re
import time
from collections import deque
import pytchat
import requests

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
YOUTUBE_CHANNEL_HANDLE = os.getenv("YOUTUBE_CHANNEL_HANDLE")

def get_live_video_id(channel_handle):
    """التحقق الصارم من وجود بث مباشر يعمل حالياً فقط"""
    handle = channel_handle if channel_handle.startswith("@") else f"@{channel_handle}"
    url = f"https://www.youtube.com/{handle}/live"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept-Language": "ar,en-US;q=0.9,en;q=0.8",
        "Cookie": "CONSENT=YES+cb.20210328-17-p0.en+FX+667;"
    }
    
    try:
        session = requests.Session()
        response = session.get(url, headers=headers, timeout=15)
        
        # التأكد أن البث مباشر حقيقي وحالي (وليس مسجل أو قادم)
        is_live_now = '"isLiveNow":true' in response.text or ('"isLive":true' in response.text and '"isUpcoming":true' not in response.text)
        
        if is_live_now:
            match = re.search(r'"videoId":"([^"]+)"', response.text)
            if match:
                return match.group(1)
    except Exception as e:
        print(f"⚠️ خطأ أثناء الفحص: {e}")
    
    return None

def send_to_telegram(author, message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    text_content = (
        f"❓ **سؤال جديد من البث المباشر**\n\n"
        f"👤 **السائل:** {author}\n"
        f"💬 **النص:**\n{message}"
    )
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text_content,
        "parse_mode": "Markdown"
    }
    try:
        res = requests.post(url, json=payload)
        if res.status_code == 200:
            print(f"✅ تم الإرسال للتلجرام: [{author}]")
        else:
            print(f"❌ خطأ من تلجرام: {res.text}")
    except Exception as e:
        print(f"❌ خطأ في الاتصال: {e}")

def main():
    print(f"👀 بدء مراقبة القناة: {YOUTUBE_CHANNEL_HANDLE}")
    
    start_time = time.time()
    max_duration = 5.5 * 3600  # 5 ساعات ونصف

    # ذاكرة لحفظ معرّفات الرسائل المرسلة ومنع التكرار نهائياً
    processed_msg_ids = deque(maxlen=2000)

    while (time.time() - start_time) < max_duration:
        print("🔍 جاري فحص وجود بث مباشر حقيقي...")
        video_id = get_live_video_id(YOUTUBE_CHANNEL_HANDLE)
        
        if video_id:
            print(f"🔴 تم اكتشاف بث مباشر شغال الآن! ID: {video_id}")
            try:
                chat = pytchat.create(video_id=video_id)
                
                while chat.is_alive() and (time.time() - start_time) < max_duration:
                    for c in chat.get().sync_items():
                        # معرف فريد لكل رسالة
                        msg_id = getattr(c, 'id', None) or f"{c.author.name}_{c.timestamp}_{c.message}"
                        
                        # تخطي الرسالة إذا تم إرسالها من قبل
                        if msg_id in processed_msg_ids:
                            continue
                        
                        # تسجيل الرسالة لمنع تكرارها
                        processed_msg_ids.append(msg_id)
                        
                        msg = c.message.strip()
                        
                        # التقاط أي رسالة تحتوي على علامة استفهام
                        if "?" in msg or "؟" in msg:
                            print(f"🎯 سؤال جديد من [{c.author.name}]: {msg}")
                            send_to_telegram(c.author.name, msg)
                            
                    time.sleep(1)
            except Exception as e:
                print(f"❌ انقطع الاتصال بالشات: {e}")
        else:
            print("⏳ لا يوجد بث مباشر شغال حالياً. إعادة الفحص بعد دقيقتين...")
            time.sleep(120)

if __name__ == "__main__":
    main()
