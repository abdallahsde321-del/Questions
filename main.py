import os
import re
import time
from collections import deque
import pytchat
import requests
import yt_dlp

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
YOUTUBE_CHANNEL_HANDLE = os.getenv("YOUTUBE_CHANNEL_HANDLE")

def get_live_video_id(channel_handle):
    """استخراج ID البث المباشر باستخدام yt-dlp والهيدرز المحمولة لتجاوز حظر السيرفرات"""
    handle = channel_handle if channel_handle.startswith("@") else f"@{channel_handle}"
    
    # محاولة أولى عبر مظهر الموبايل
    mobile_url = f"https://m.youtube.com/{handle}/live"
    headers = {
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1",
        "Accept-Language": "ar,en-US;q=0.9,en;q=0.8"
    }
    
    try:
        response = requests.get(mobile_url, headers=headers, timeout=12, allow_redirects=True)
        if "watch?v=" in response.url:
            return response.url.split("watch?v=")[1].split("&")[0]
            
        match = re.search(r'"videoId":"([^"]+)"', response.text)
        if match and ('"isLive":true' in response.text or '"isLiveNow":true' in response.text or 'LIVE' in response.text):
            return match.group(1)
    except Exception as e:
        print(f"⚠️ خطأ أثناء الفحص المباشر: {e}")

    # محاولة ثانية عبر yt-dlp
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

def main():
    print(f"👀 بدء مراقبة القناة: {YOUTUBE_CHANNEL_HANDLE}")
    
    start_time = time.time()
    max_duration = 5.5 * 3600  # 5 ساعات ونصف

    # ذاكرة لمنع تكرار إرسال نفس السؤال
    processed_msg_ids = deque(maxlen=5000)

    while (time.time() - start_time) < max_duration:
        print("🔍 جاري فحص وجود بث مباشر...")
        video_id = get_live_video_id(YOUTUBE_CHANNEL_HANDLE)
        
        if video_id:
            print(f"🔴 تم العثور على بث مباشر! Video ID: {video_id}")
            try:
                chat = pytchat.create(video_id=video_id)
                
                if not chat.is_alive():
                    print("⚠️ فشل الاتصال بشات البث (قد يكون الشات معطلاً أو مغلقاً).")
                else:
                    print("🟢 البوت متصل بالشات الآن ويقرأ الرسائل...")

                while chat.is_alive() and (time.time() - start_time) < max_duration:
                    items = chat.get().sync_items()
                    
                    for c in items:
                        # إنشاء معرف فريد للرسالة
                        msg_id = getattr(c, 'id', None) or f"{c.author.name}_{c.timestamp}_{c.message}"
                        
                        if msg_id in processed_msg_ids:
                            continue
                        
                        processed_msg_ids.append(msg_id)
                        msg = c.message.strip()
                        
                        # طباعة كل رسالة تصل للشات في السجلات للتحقق
                        print(f"💬 [شات]: {c.author.name}: {msg}")
                        
                        # التقاط أي سؤال يحتوي على علامة استفهام (إنجليزية أو عربية)
                        if "?" in msg or "؟" in msg:
                            print(f"🎯 تم التقاط سؤال: {msg}")
                            send_to_telegram(msg)
                            
                    time.sleep(1)
            except Exception as e:
                print(f"❌ انقطع الاتصال بالشات: {e}")
        else:
            print("⏳ لا يوجد بث مباشر حقيقي حالياً. إعادة الفحص بعد دقيقتين...")
            time.sleep(120)

if __name__ == "__main__":
    main()
