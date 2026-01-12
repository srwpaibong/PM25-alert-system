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
API_KEY = os.getenv('AIR4THAI_KEY')
GITHUB_REPO = os.getenv('GITHUB_REPOSITORY')

LOG_FILE = "log.json"
TIMEZONE = pytz.timezone('Asia/Bangkok')
REPORT_HOURS = [7, 8, 9, 12, 14, 15, 17, 20]

def load_log():
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, 'r') as f:
            try: return json.load(f)
            except: return {"last_date": "", "alerted_ids": []}
    return {"last_date": "", "alerted_ids": []}

def get_alert_stations():
    url = "http://air4thai.com/forweb/getAQI_JSON.php"
    print("1. กำลังตรวจสอบค่าฝุ่นจาก Air4Thai...")
    try:
        res = requests.get(url, timeout=30).json()
        stations = []
        for s in res.get('stations', []):
            s_id = s.get('stationID')
            s_type = s.get('stationType', '').lower()
            
            # ดึงค่า PM2.5 แบบปลอดภัย
            aqi_last = s.get('AQILast', {})
            pm25_obj = aqi_last.get('PM25', {})
            try: 
                pm25 = float(pm25_obj.get('value', 0))
            except: 
                pm25 = 0
            
            # ดึงเวลาแบบปลอดภัย (ถ้าไม่มี datetime ให้ใช้เวลาจากช่องอื่น หรือใช้เวลาปัจจุบัน)
            time_val = pm25_obj.get('datetime')
            if not time_val:
                time_val = f"{aqi_last.get('date', '')} {aqi_last.get('time', '')}".strip()
            if not time_val:
                time_val = datetime.datetime.now(TIMEZONE).strftime('%Y-%m-%d %H:%M')

            # เงื่อนไข: ไม่เอา 11t, ไม่เอา BKK, เกณฑ์ > 37.5
            if s_id != "11t" and s_type != "bkk" and pm25 > 37.5:
                stations.append({
                    "id": s_id, 
                    "name": s.get('nameTH', 'ไม่ระบุชื่อ'), 
                    "area": s.get('areaTH', 'ไม่ระบุพื้นที่'), 
                    "value": pm25,
                    "time": time_val
                })
        print(f"พบสถานีเข้าเกณฑ์ {len(stations)} สถานี")
        return stations
    except Exception as e:
        print(f"❌ Error ในการประมวลผลข้อมูล: {e}")
        return []

def analyze_and_plot(s_id, s_name):
    headers = {'User-Agent': 'Mozilla/5.0'}
    url = f"http://air4thai.com/forweb/getHistory.php?stationID={s_id}&param=PM25&type=hr"
    try:
        response = requests.get(url, headers=headers, timeout=30)
        if response.status_code != 200: return None
        res = response.json()
        
        data = res.get('station', {}).get('data', [])
        if not data: return None
        
        df = pd.DataFrame(data).tail(48)
        df['value'] = pd.to_numeric(df['value'], errors='coerce')
        
        plt.figure(figsize=(10, 5))
        plt.plot(df['datetime'], df['value'], marker='o', color='#e74c3c', linewidth=2)
        plt.axhline(y=37.5, color='#f39c12', linestyle='--', label='Orange')
        plt.axhline(y=75.0, color='#c0392b', linestyle='--', label='Red')
        plt.title(f"Trend 48 Hours: {s_name}", fontsize=12)
        plt.grid(True, alpha=0.3)
        plt.xticks(rotation=45, fontsize=8)
        plt.tight_layout()
        
        filename = f"graph_{s_id}.png"
        plt.savefig(filename)
        plt.close()
        return filename
    except:
        return None

def send_line(message, image_url):
    url = "https://api.line.me/v2/bot/message/push"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {LINE_TOKEN}"}
    ts = int(datetime.datetime.now().timestamp())
    full_image_url = f"{image_url}?t={ts}"
    
    payload = {
        "to": USER_ID,
        "messages": [
            {"type": "text", "text": message},
            {"type": "image", "originalContentUrl": full_image_url, "previewImageUrl": full_image_url}
        ]
    }
    requests.post(url, headers=headers, json=payload)

def main():
    now = datetime.datetime.now(TIMEZONE)
    today = now.strftime("%Y-%m-%d")
    history = load_log()
    
    if history.get('last_date') != today:
        history = {"last_date": today, "alerted_ids": []}

    stations = get_alert_stations()
    if not stations:
        print("💡 ไม่พบสถานีที่เข้าเกณฑ์ในขณะนี้")
        return

    current_ids = [s['id'] for s in stations]
    new_ids = [i for i in current_ids if i not in history.get('alerted_ids', [])]
    
    # ส่งเมื่อมีสถานีใหม่ หรือ ถึงรอบรายงาน
    if new_ids or (now.hour in REPORT_HOURS):
        print(f"🚀 เริ่มส่งแจ้งเตือน {len(stations)} สถานี...")
        for s in stations:
            img_file = analyze_and_plot(s['id'], s['name'])
            if img_file:
                image_link = f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/{img_file}"
                status = "🔴 สีแดง" if s['value'] > 75.0 else "🟠 สีส้ม"
                msg = (f"🚨 แจ้งเตือนฝุ่น ({status})\n"
                       f"📍 สถานี: {s['name']}\n"
                       f"🗺️ พื้นที่: {s['area']}\n"
                       f"💨 PM2.5: {s['value']} µg/m³\n"
                       f"⏰ ข้อมูลเมื่อ: {s['time']}")
                send_line(msg, image_link)
        
        history['alerted_ids'] = list(set(history.get('alerted_ids', []) + current_ids))
        with open(LOG_FILE, 'w') as f: json.dump(history, f)
        print("✅ ดำเนินการเสร็จสิ้น")

if __name__ == "__main__":
    main()
