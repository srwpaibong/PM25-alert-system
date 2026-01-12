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
REPORT_HOURS = [7, 8, 9, 12, 15, 17]

def load_log():
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, 'r') as f:
            try: return json.load(f)
            except: return {"last_date": "", "alerted_ids": []}
    return {"last_date": "", "alerted_ids": []}

def get_red_stations():
    url = "http://air4thai.com/forweb/getAQI_JSON.php"
    try:
        res = requests.get(url, timeout=30).json()
        red_list = []
        for s in res.get('stations', []):
            s_id = s.get('stationID')
            s_type = s.get('stationType', '').lower()
            try: pm25 = float(s['AQILast']['PM25']['value'])
            except: pm25 = 0
            
            if s_id != "11t" and s_type != "bkk" and pm25 > 0:
                red_list.append({"id": s_id, "name": s['nameTH'], "area": s['areaTH'], "value": pm25})
        return red_list
    except:
        return []

def analyze_and_plot(s_id, s_name):
    headers = {'User-Agent': 'Mozilla/5.0'}
    url = f"http://air4thai.com/forweb/getHistory.php?stationID={s_id}&param=PM25&type=hr"
    
    try:
        response = requests.get(url, headers=headers, timeout=30)
        # ป้องกัน JSONDecodeError ถ้า API ส่งค่าว่างมา
        if not response.text or response.status_code != 200:
            return "เซิร์ฟเวอร์ Air4Thai ไม่ตอบสนอง ❓", "ดึงข้อมูลประวัติไม่ได้", None
            
        res = response.json()
        if 'station' not in res or 'data' not in res['station']:
            return "ไม่มีข้อมูลย้อนหลัง ❓", "ไม่พบประวัติ 48 ชม.", None

        df = pd.DataFrame(res['station']['data']).tail(48)
        df['value'] = pd.to_numeric(df['value'], errors='coerce')
        
        missing = df['value'].isna().sum()
        max_diff = df['value'].diff().abs().max()
        status, detail = "ปกติ ✅", "ข้อมูลมีความต่อเนื่อง"
        
        if missing > 12: status, detail = "ผิดปกติ ⚠️", "ข้อมูลขาดหายเกิน 25%"
        elif max_diff > 50: status, detail = "ผิดปกติ ⚠️", f"พบค่า Spike {max_diff} µg/m³"

        plt.figure(figsize=(10, 4))
        plt.plot(df['datetime'], df['value'], marker='o', color='red', linewidth=2)
        plt.axhline(y=75.1, color='gray', linestyle='--')
        plt.title(f"48h Trend: {s_name} ({s_id})")
        plt.grid(True, alpha=0.3)
        plt.xticks(rotation=45)
        plt.tight_layout()
        
        filename = f"graph_{s_id}.png"
        plt.savefig(filename)
        plt.close()
        return status, detail, filename
    except Exception as e:
        print(f"Plot Error: {e}")
        return "ตรวจสอบไม่ได้ ❓", "เกิดข้อผิดพลาดในการประมวลผล", None

def send_line(message, image_url):
    url = "https://api.line.me/v2/bot/message/push"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {LINE_TOKEN}"}
    ts = datetime.datetime.now().timestamp()
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

    red_stations = get_red_stations()
    if not red_stations:
        with open(LOG_FILE, 'w') as f: json.dump(history, f)
        return

    current_ids = [s['id'] for s in red_stations]
    new_ids = [i for i in current_ids if i not in history.get('alerted_ids', [])]
    
    # เงื่อนไข: ส่งเมื่อถึงเวลาที่กำหนด หรือ มีสถานีใหม่แดงขึ้นมา
    if new_ids or (now.hour in REPORT_HOURS):
        for s in red_stations:
            status, detail, img_file = analyze_and_plot(s['id'], s['name'])
            if img_file:
                image_link = f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/{img_file}"
                msg = f"🚨 แจ้งเตือนฝุ่นสีแดง\n📍 {s['name']}\n🗺️ {s['area']}\n💨 24ชม.: {s['value']} µg/m³\n🔍 ตรวจสอบ: {status}\n📝 {detail}"
                send_line(msg, image_link)
        
        history['alerted_ids'] = list(set(history.get('alerted_ids', []) + current_ids))
        with open(LOG_FILE, 'w') as f: json.dump(history, f)

if __name__ == "__main__":
    main()
