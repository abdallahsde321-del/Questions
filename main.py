import os
import time
import pytchat
import requests

# قراءة البيانات الآمنة من الـ Secrets
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
YOUTUBE_CHANNEL_HANDLE = os.getenv("YOUTUBE_CHANNEL_HANDLE")

def get_live_video_id(channel_handle):
    """فحص القناة واستخراج معرف البث المباشر إن وجد"""
    handle = channel_handle if channel_handle.startswith("@") else f"@{channel_handle}"
    url = f"https://www.youtube.com/{handle}/live"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9"
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        if "watch?v=" in response.url and ('"isLive":true' in response.text or 'LIVE' in response.text):
            video_id = response.url.split("watch?v=")[1].split("&")[0]
            return video_id
    except Exception as e:
        print(f"⚠️ خطأ أثناء الفحص عن البث: {e}")
    
    return None

def send_to_telegram(author, message):
    """إرسال السؤال المكتشف إلى قناة التلجرام"""
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
        print(f"❌ خطأ اتصال: {e}")

def main():
    print(f"👀 بدء مراقبة القناة: {YOUTUBE_CHANNEL_HANDLE}")
    
    # حد أقصى للتشغيل 5.5 ساعة ليتوافق مع حدود GitHub Actions ويجدد نفسه تلقائياً
    start_time = time.time()
    max_duration = 5.5 * 3600 

    while (time.time() - start_time) < max_duration:
        print("🔍 فحص وجود بث مباشر...")
        video_id = get_live_video_id(YOUTUBE_CHANNEL_HANDLE)
        
        if video_id:
            print(f"🔴 يوجد بث مباشر شغال الآن! ID: {video_id}")
            try:
                chat = pytchat.create(video_id=video_id)
                while chat.is_alive() and (time.time() - start_time) < max_duration:
                    for c in chat.get().sync_items():
                        msg = c.message.strip()
                        # شرط التقاط السؤال: انتهائه بـ ???
                        if msg.endswith("???"):
                            print(f"🎯 سؤال من [{c.author.name}]: {msg}")
                            send_to_telegram(c.author.name, msg)
                    time.sleep(1)
            except Exception as e:
                print(f"❌ انقطع البث: {e}")
        else:
            print("⏳ لا يوجد بث حالياً. إعادة الفحص بعد دقيقتين...")
            time.sleep(120)

    print("⏰ انتهت الجولة الحالية وسيعيد GitHub Actions تشغيل السكربت تلقائياً.")

if __name__ == "__main__":
    main()
