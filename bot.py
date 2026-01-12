import requests
import pandas as pd
import matplotlib.pyplot as plt
import os
import json
import datetime
import pytz

# --- Configuration ---
LINE_TOKEN = os.getenv('LINE_ACCESS_TOKEN')
USER_ID = os.getenv('LINE_USER_ID')
GITHUB_REPO = os.getenv('GITHUB_REPOSITORY')
TIMEZONE = pytz.timezone('Asia/Bangkok')

def get_red_stations():
    url = "http://air4thai.com/forweb/getAQI_JSON.php"
    print("1. กำลังตรวจสอบค่าฝุ่น (เฉพาะพื้นที่สีแดง)...")
    try:
        res = requests.get(url, timeout=30).json()
        red_list = []
        for s in res.get('stations', []):
            aqi_last = s.get('AQILast', {})
            pm25_obj = aqi_last.get('PM25', {})
            
            # ดึงค่า PM2.5 และ AQI
            try: 
                pm25 = float(pm25_obj.get('value', 0))
                aqi_val = s.get('AQILast', {}).get('AQI', {}).get('value', 'N/A')
            except: 
                continue
            
            # เงื่อนไข: สีแดง (> 75.0), ไม่ใช่ BKK, ไม่ใช่ 11t
            if s.get('stationID') != "11t" and s.get('stationType', '').lower() != 'bkk' and pm25 > 75.0:
                red_list.append({
                    "id": s.get('stationID'),
                    "name": s.get('nameTH'),
                    "area": s.get('areaTH'),
                    "pm25": pm25,
                    "aqi": aqi_val,
                    "time": pm25_obj.get('datetime', datetime.datetime.now(TIMEZONE).strftime('%Y-%m-%d %H:%M'))
                })
        print(f"พบสถานีสีแดง {len(red_list)} สถานี")
        return red_list
    except Exception as e:
        print(f"Error ดึงข้อมูล: {e}")
        return []

def verify_data_trend(s_id, s_name):
    """ดึงข้อมูลย้อนหลัง 24 ชม. เพื่อวิเคราะห์ Trend และตรวจสอบความผิดปกติ"""
    url = f"http://air4thai.com/forweb/getHistory.php?stationID={s_id}&param=PM25&type=hr"
    try:
        res = requests.get(url, timeout=30).json()
        data = res.get('station', {}).get('data', [])
        if not data:
            return "ไม่พบข้อมูลประวัติย้อนหลัง", None

        df = pd.DataFrame(data).tail(24) # วิเคราะห์ย้อนหลัง 24 ชั่วโมง
        df['value'] = pd.to_numeric(df['value'], errors='coerce')
        
        # --- ตรรกะตรวจสอบความถูกต้อง (Verification Logic) ---
        # 1. เช็คการกระโดดของค่า (Spike)
        max_diff = df['value'].diff().abs().max()
        # 2. เช็คความต่อเนื่อง (ต้องแดงต่อเนื่องเกิน 2 ชม.)
        is_steady_red = (df['value'].tail(2) > 75.0).all()
        
        verify_msg = ""
        if max_diff > 60:
            verify_msg = f"⚠️ เฝ้าระวัง: พบค่าพุ่งสูงผิดปกติ ({max_diff} µg/m³ ใน 1 ชม.) อาจเป็นความผิดปกติของสถานี"
        elif is_steady_red:
            verify_msg = "✅ ยืนยัน: ค่าฝุ่นสูงต่อเนื่อง (เป็นแนวโน้มสถานการณ์จริง)"
        else:
            verify_msg = "🔍 ตรวจสอบ: ค่าเพิ่งพุ่งสูงขึ้น (เริ่มเข้าเกณฑ์วิกฤต)"

        # --- วาดกราฟ Trend ---
        plt.figure(figsize=(10, 5))
        plt.plot(df['datetime'].str[-5:], df['value'], marker='o', color='#c0392b', linewidth=2)
        plt.axhline(y=75.0, color='black', linestyle='--', alpha=0.5)
        plt.title(f"PM2.5 Trend (24h): {s_name}", fontsize=12)
        plt.ylabel("µg/m³")
        plt.grid(True, alpha=0.3)
        plt.xticks(rotation=45)
        plt.tight_layout()
        
        img_name = f"trend_{s_id}.png"
        plt.savefig(img_name)
        plt.close()
        return verify_msg, img_name
    except:
        return "ไม่สามารถดึงข้อมูล Trend ได้", None

def send_line(s, verify_msg, img_file):
    url = "https://api.line.me/v2/bot/message/push"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_TOKEN}"
    }
    
    text_msg = (f"🚨 แจ้งเตือน: พื้นที่สีแดง (อันตราย)\n"
                f"📍 สถานี: {s['name']}\n"
                f"🗺️ {s['area']}\n"
                f"😷 AQI: {s['aqi']}\n"
                f"💨 PM2.5: {s['pm25']} µg/m³\n"
                f"⏰ ข้อมูล ณ เวลา: {s['time']}\n"
                f"🧐 วิเคราะห์: {verify_msg}")

    messages = [{"type": "text", "text": text_msg}]
    
    if img_file:
        ts = int(datetime.datetime.now().timestamp())
        img_url = f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/{img_file}?t={ts}"
        messages.append({
            "type": "image",
            "originalContentUrl": img_url,
            "previewImageUrl": img_url
        })

    payload = {"to": USER_ID, "messages": messages}
    res = requests.post(url, headers=headers, json=payload)
    print(f"ผลการส่ง {s['name']}: {res.status_code}")

def main():
    red_stations = get_red_stations()
    if not red_stations:
        print("ไม่พบสถานีสีแดงในพื้นที่ที่กำหนด")
        return

    for s in red_stations:
        verify_msg, img_file = verify_data_trend(s['id'], s['name'])
        send_line(s, verify_msg, img_file)

if __name__ == "__main__":
    main()
