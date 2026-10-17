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
    """استخراج ID البث المباشر الحقيقي فقط بدقة عالية"""
    handle = channel_handle if channel_handle.startswith("@") else f"@{channel_handle}"
    url = f"https://www.youtube.com/{handle}/live"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept-Language": "ar,en-US;q=0.9,en;q=0.8",
        "Cookie": "CONSENT=YES+cb.20210328-17-p0.en+FX+667;"
    }
    
    try:
        session = requests.Session()
        response = session.get(url, headers=headers, timeout=15, allow_redirects=True)
        
        video_id = None
        if "watch?v=" in response.url:
            video_id = response.url.split("watch?v=")[1].split("&")[0]
        else:
            canonical_match = re.search(r'<link rel="canonical" href="https://www.youtube.com/watch\?v=([^"]+)"', response.text)
            if canonical_match:
                video_id = canonical_match.group(1)
        
        if video_id:
            is_live_now = ('"isLiveNow":true' in response.text or '"isLive":true' in response.text or '"style":"LIVE"' in response.text)
            is_upcoming = '"isUpcoming":true' in response.text
            
            if is_live_now and not is_upcoming:
                return video_id
    except Exception as e:
        print(f"⚠️ خطأ أثناء البحث عن البث: {e}")
    
    return None

def send_to_telegram(message):
    """إرسال نص السؤال فقط بدون أي إضافات أو أسماء"""
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
    max_duration = 5.5 * 3600  # 5 ساعات ونصف كحد أقصى للجلسة

    processed_msg_ids = deque(maxlen=5000)

    while (time.time() - start_time) < max_duration:
        print("🔍 جاري فحص وجود بث مباشر شغال...")
        video_id = get_live_video_id(YOUTUBE_CHANNEL_HANDLE)
        
        if video_id:
            print(f"🔴 تم اكتشاف بث مباشر حقيقي! Video ID: {video_id}")
            try:
                chat = pytchat.create(video_id=video_id)
                
                first_fetch = True
                
                while chat.is_alive() and (time.time() - start_time) < max_duration:
                    items = chat.get().sync_items()
                    
                    if first_fetch:
                        # تسخين البوت بتجاهل الشات القديم
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
                        
                        # التقاط أي سؤال يحتوي على علامة استفهام إنجليزية أو عربية
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
