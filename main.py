import os
import re
import time
import requests
import pytchat

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
YOUTUBE_CHANNEL_HANDLE = os.getenv("YOUTUBE_CHANNEL_HANDLE") or os.getenv("YOUTUBE_CHANNEL_ID")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "ar,en-US;q=0.9,en;q=0.8"
}

def fetch_video_id(target):
    """جلب معرف البث المباشر (تعمل لديك بنجاح)"""
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

def send_to_telegram(message):
    """إرسال النص إلى تلجرام"""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message}
    try:
        requests.post(url, json=payload, timeout=10)
        print(f"🚀 تم الإرسال للتلجرام بنجاح: [{message}]")
    except Exception as e:
        print(f"❌ خطأ اتصال بتلجرام: {e}")

def main():
    print("👀 جاري تشغيل النظام الموثوق (Pytchat)...")
    start_time = time.time()
    max_duration = 5.5 * 3600 # العمل لمدة 5 ساعات ونصف

    while (time.time() - start_time) < max_duration:
        target = YOUTUBE_CHANNEL_HANDLE
        if not target:
            print("❌ يرجى إضافة YOUTUBE_CHANNEL_HANDLE في الـ Secrets.")
            time.sleep(60)
            continue

        video_id = fetch_video_id(target)
        
        if video_id:
            print(f"🎯 تم التقاط البث: {video_id}")
            try:
                # استخدام Pytchat للاتصال بالشات مباشرة وبدون تعقيدات
                chat = pytchat.create(video_id=video_id)
                
                if chat.is_alive():
                    print(f"🟢 متصل بشات البث ({video_id}) بنجاح! جاري مراقبة الرقم 100...")
                    
                    while chat.is_alive() and (time.time() - start_time) < max_duration:
                        for c in chat.get().sync_items():
                            msg_text = c.message
                            author = c.author.name
                            print(f"💬 [شات]: {author}: {msg_text}")
                            
                            if "100" in msg_text or "١٠٠" in msg_text:
                                print(f"🎯 تم التقاط (100): {msg_text}")
                                send_to_telegram(msg_text)
                        
                        time.sleep(2) # راحة لتخفيف الضغط
                else:
                    print("⚠️ الشات غير متاح لهذا الفيديو (قد يكون مغلقاً أو الفيديو ليس بثاً مباشراً يعمل الآن).")
            
            except Exception as e:
                print(f"❌ خطأ في قراءة الشات: {e}")
        else:
            print("⏳ لا يوجد بث مباشر حالياً. إعادة الفحص بعد دقيقة...")
            
        time.sleep(60) # الانتظار دقيقة قبل المحاولة مرة أخرى

if __name__ == "__main__":
    main()
