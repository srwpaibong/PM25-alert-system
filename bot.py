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
LOG_FILE = "log.json"
REPORT_HOURS = [7, 8, 9, 12, 14, 15, 17, 20]

def load_log():
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, 'r') as f:
            try: return json.load(f)
            except: return {"last_date": "", "alerted_ids": []}
    return {"last_date": "", "alerted_ids": []}

def get_alert_stations():
    url = "http://air4thai.com/forweb/getAQI_JSON.php"
    print("1. ตรวจสอบค่าฝุ่นจาก Air4Thai...")
    try:
        res = requests.get(url, timeout=30).json()
        stations = []
        for s in res.get('stations', []):
            s_id = s.get('stationID')
            s_type = s.get('stationType', '').lower()
            aqi_last = s.get('AQILast', {})
            pm25_obj = aqi_last.get('PM25', {})
            try: pm25 = float(pm25_obj.get('value', 0))
            except: pm25 = 0
            
            # เกณฑ์แจ้งเตือน > 37.5 และไม่ใช่ BKK/11t
            if s_id != "11t" and s_type != "bkk" and pm25 > 37.5:
                stations.append({
                    "id": s_id, 
                    "name": s.get('nameTH', 'Unknown'), 
                    "area": s.get('areaTH', 'Unknown'), 
                    "value": pm25,
                    "time": pm25_obj.get('datetime', 'N/A')
                })
        return stations
    except Exception as e:
        print(f"❌ Error API: {e}")
        return []

def analyze_and_plot(s_id, s_name):
    print(f"   - กำลังวาดกราฟสถานี {s_id}...")
    headers = {'User-Agent': 'Mozilla/5.0'}
    url = f"http://air4thai.com/forweb/getHistory.php?stationID={s_id}&param=PM25&type=hr"
    try:
        response = requests.get(url, headers=headers, timeout=20)
        res = response.json()
        data = res.get('station', {}).get('data', [])
        if not data: 
            print(f"     ⚠️ ไม่มีข้อมูลประวัติของ {s_id}")
            return None
        
        df = pd.DataFrame(data).tail(48)
        df['value'] = pd.to_numeric(df['value'], errors='coerce')
        
        plt.figure(figsize=(10, 5))
        plt.plot(df['datetime'], df['value'], marker='o', color='#e74c3c')
        plt.title(f"Trend: {s_name}")
        plt.xticks(rotation=45)
        plt.tight_layout()
        
        filename = f"graph_{s_id}.png"
        plt.savefig(filename)
        plt.close()
        return filename
    except Exception as e:
        print(f"     ❌ วาดกราฟพลาด: {e}")
        return None

def send_line(messages):
    url = "https://api.line.me/v2/bot/message/push"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {LINE_TOKEN}"}
    payload = {"to": USER_ID, "messages": messages}
    res = requests.post(url, headers=headers, json=payload)
    print(f"   -> LINE Response: {res.status_code} {res.text}")

def main():
    now = datetime.datetime.now(TIMEZONE)
    today = now.strftime("%Y-%m-%d")
    history = load_log()
    if history.get('last_date') != today: history = {"last_date": today, "alerted_ids": []}

    stations = get_alert_stations()
    if not stations: return

    current_ids = [s['id'] for s in stations]
    new_ids = [i for i in current_ids if i not in history.get('alerted_ids', [])]
    
    # ส่งเมื่อมีสถานีใหม่ หรือถึงรอบรายงาน
    if new_ids or (now.hour in REPORT_HOURS):
        print(f"🚀 เริ่มส่งแจ้งเตือน {len(stations)} สถานี...")
        for s in stations:
            status = "🔴 สีแดง" if s['value'] > 75.0 else "🟠 สีส้ม"
            msg_text = (f"🚨 แจ้งเตือนฝุ่น ({status})\n📍 {s['name']}\n🗺️ {s['area']}\n💨 PM2.5: {s['value']} µg/m³\n⏰ ข้อมูลเมื่อ: {s['time']}")
            
            messages = [{"type": "text", "text": msg_text}]
            
            # พยายามวาดกราฟ
            img_file = analyze_and_plot(s['id'], s['name'])
            if img_file:
                ts = int(datetime.datetime.now().timestamp())
                img_url = f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/{img_file}?t={ts}"
                messages.append({"type": "image", "originalContentUrl": img_url, "previewImageUrl": img_url})
            
            # ส่ง LINE (ตอนนี้จะส่งแน่นอนอย่างน้อยคือข้อความตัวหนังสือ)
            send_line(messages)
        
        history['alerted_ids'] = list(set(history.get('alerted_ids', []) + current_ids))
        with open(LOG_FILE, 'w') as f: json.dump(history, f)
    print("✅ ดำเนินการเสร็จสิ้น")

if __name__ == "__main__":
    main()
