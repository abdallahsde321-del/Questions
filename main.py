import os
import re
import time
import pytchat
import requests

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
YOUTUBE_CHANNEL_HANDLE = os.getenv("YOUTUBE_CHANNEL_HANDLE")

def get_live_video_id(channel_handle):
    """استخراج ID البث المباشر وتجاوز قيود يوتيوب"""
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
        
        match = re.search(r'"videoId":"([^"]+)"', response.text)
        if match:
            video_id = match.group(1)
            if '"isLive":true' in response.text or 'LIVE' in response.text or '"style":"LIVE"' in response.text:
                return video_id
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
            print(f"✅ تم الإرسال بنجاح للتلجرام: [{author}]")
        else:
            print(f"❌ خطأ من تلجرام (رمز {res.status_code}): {res.text}")
    except Exception as e:
        print(f"❌ خطأ في الاتصال بتلجرام: {e}")

def main():
    print(f"👀 بدء مراقبة القناة: {YOUTUBE_CHANNEL_HANDLE}")
    
    start_time = time.time()
    max_duration = 5.5 * 3600  # 5 ساعات ونصف

    while (time.time() - start_time) < max_duration:
        print("🔍 جاري فحص البث المباشر...")
        video_id = get_live_video_id(YOUTUBE_CHANNEL_HANDLE)
        
        if video_id:
            print(f"🔴 تم اكتشاف بث مباشر! Video ID: {video_id}")
            try:
                chat = pytchat.create(video_id=video_id)
                while chat.is_alive() and (time.time() - start_time) < max_duration:
                    for c in chat.get().sync_items():
                        msg = c.message.strip()
                        
                        # التقاط أي رسالة تحتوي على علامة استفهام عربية (؟) أو إنجليزية (?)
                        if "?" in msg or "؟" in msg:
                            print(f"🎯 التقاط سؤال من [{c.author.name}]: {msg}")
                            send_to_telegram(c.author.name, msg)
                            
                    time.sleep(1)
            except Exception as e:
                print(f"❌ انقطع الاتصال بالشات: {e}")
        else:
            print("⏳ لم يتم العثور على بث مباشر حالياً. إعادة الفحص بعد دقيقتين...")
            time.sleep(120)

if __name__ == "__main__":
    main()
