import os
import time
from collections import deque
import pytchat
import requests
import yt_dlp

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
YOUTUBE_CHANNEL_HANDLE = os.getenv("YOUTUBE_CHANNEL_HANDLE")

def get_live_video_id(channel_handle):
    """استخراج ID البث المباشر باستخدام yt-dlp لتجاوز حظر سيرفرات GitHub Actions"""
    handle = channel_handle if channel_handle.startswith("@") else f"@{channel_handle}"
    url = f"https://www.youtube.com/{handle}/live"
    
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'skip_download': True,
        'extract_flat': False,
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            # التأكد من أن الفيديو بث مباشر شغال حالياً
            if info and (info.get('is_live') or info.get('live_status') == 'is_live'):
                return info.get('id')
    except Exception as e:
        print(f"⚠️ خطأ أثناء الفحص بـ yt-dlp: {e}")
        
    return None

def send_to_telegram(message):
    """إرسال نص السؤال فقط بدون أية إضافات"""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message
    }
    
    try:
        res = requests.post(url, json=payload, timeout=10)
        if res.status_code == 200:
            print(f"✅ تم إرسال السؤال للتلجرام: [{message}]")
        else:
            print(f"❌ خطأ من تلجرام ({res.status_code}): {res.text}")
    except Exception as e:
        print(f"❌ خطأ في الاتصال بتلجرام: {e}")

def main():
    print(f"👀 بدء مراقبة القناة: {YOUTUBE_CHANNEL_HANDLE}")
    
    start_time = time.time()
    max_duration = 5.5 * 3600  # 5 ساعات ونصف

    processed_msg_ids = deque(maxlen=5000)

    while (time.time() - start_time) < max_duration:
        print("🔍 جاري فحص وجود بث مباشر حقيقي...")
        video_id = get_live_video_id(YOUTUBE_CHANNEL_HANDLE)
        
        if video_id:
            print(f"🔴 تم اكتشاف بث مباشر حقيقي! Video ID: {video_id}")
            try:
                chat = pytchat.create(video_id=video_id)
                
                first_fetch = True
                
                while chat.is_alive() and (time.time() - start_time) < max_duration:
                    items = chat.get().sync_items()
                    
                    if first_fetch:
                        # تسخين البوت بتجاهل الرسائل القديمة
                        for c in items:
                            msg_id = getattr(c, 'id', None) or f"{c.author.name}_{c.timestamp}_{c.message}"
                            processed_msg_ids.append(msg_id)
                        first_fetch = False
                        time.sleep(1)
                        continue
                    
                    for c in items:
                        msg_id = getattr(c, 'id', None) or f"{c.author.name}_{c.timestamp}_{c.message}"
                        
                        if msg_id in processed_msg_ids:
                            continue
                        
                        processed_msg_ids.append(msg_id)
                        msg = c.message.strip()
                        
                        # التقاط أي سؤال يحتوي على علامة استفهام عربية أو إنجليزية
                        if "?" in msg or "؟" in msg:
                            print(f"🎯 سؤال جديد: {msg}")
                            send_to_telegram(msg)
                            
                    time.sleep(1)
            except Exception as e:
                print(f"❌ انقطع الاتصال بالشات: {e}")
        else:
            print("⏳ لا يوجد بث مباشر حقيقي حالياً. إعادة الفحص بعد دقيقتين...")
            time.sleep(120)

if __name__ == "__main__":
    main()
