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
# ช่วงเวลาที่จะให้สรุปรายงานประจำชั่วโมง (แม้จะเคยเตือนไปแล้ว)
REPORT_HOURS = [7, 8, 9, 12, 15, 17, 20]

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
            
            # เงื่อนไขใช้งานจริง: ไม่เอา 11t, ไม่เอา BKK, ต้องสีแดง (> 75.0)
            if s_id != "11t" and s_type != "bkk" and pm25 > 75.0:
                red_list.append({
                    "id": s_id, 
                    "name": s['nameTH'], 
                    "area": s['areaTH'], 
                    "value": pm25,
                    "time": s['AQILast']['PM25']['datetime']
                })
        return red_list
    except:
        return []

def analyze_and_plot(s_id, s_name):
    headers = {'User-Agent': 'Mozilla/5.0'}
    url = f"http://air4thai.com/forweb/getHistory.php?stationID={s_id}&param=PM25&type=hr"
    try:
        response = requests.get(url, headers=headers, timeout=30)
        if not response.text or response.status_code != 200: return "N/A", "Data Error", None
        res = response.json()
        df = pd.DataFrame(res['station']['data']).tail(48)
        df['value'] = pd.to_numeric(df['value'], errors='coerce')
        
        # วิเคราะห์ความต่อเนื่องของข้อมูล
        max_diff = df['value'].diff().abs().max()
        status = "ปกติ ✅" if max_diff < 50 else "ผิดปกติ ⚠️ (พบค่ากระโดด)"

        plt.figure(figsize=(10, 5))
        plt.plot(df['datetime'], df['value'], marker='o', color='#e74c3c', linewidth=2)
        plt.axhline(y=75.0, color='#2c3e50', linestyle='--', label='Red Line')
        plt.title(f"Trend 48 Hours: {s_name}", fontsize=14)
        plt.grid(True, alpha=0.3)
        plt.xticks(rotation=45)
        plt.tight_layout()
        
        filename = f"graph_{s_id}.png"
        plt.savefig(filename)
        plt.close()
        return status, f"Spike: {max_diff:.1f}", filename
    except:
        return "Error", "Connection Fail", None

def send_line(message, image_url):
    url = "https://api.line.me/v2/bot/message/push"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {LINE_TOKEN}"}
    ts = datetime.datetime.now().timestamp()
    # ป้องกัน LINE จำภาพเก่าด้วยการเติมตัวแปรเวลา
    full_image_url = f"{image_url}?t={int(ts)}"
    
    payload = {
        "to": USER_ID,
        "messages": [
            {"type": "text", "text": message},
            {
                "type": "image", 
                "originalContentUrl": full_image_url, 
                "previewImageUrl": full_image_url
            }
        ]
    }
    requests.post(url, headers=headers, json=payload)

def main():
    now = datetime.datetime.now(TIMEZONE)
    today = now.strftime("%Y-%m-%d")
    history = load_log()
    
    # ล้างค่า Log เมื่อขึ้นวันใหม่
    if history.get('last_date') != today:
        history = {"last_date": today, "alerted_ids": []}

    red_stations = get_red_stations()
    if not red_stations:
        with open(LOG_FILE, 'w') as f: json.dump(history, f)
        return

    current_ids = [s['id'] for s in red_stations]
    new_ids = [i for i in current_ids if i not in history.get('alerted_ids', [])]
    
    # ส่งแจ้งเตือนถ้า: 1. มีสถานีแดงใหม่ หรือ 2. ถึงเวลาสรุปประจำชั่วโมง
    if new_ids or (now.hour in REPORT_HOURS):
        for s in red_stations:
            status, detail, img_file = analyze_and_plot(s['id'], s['name'])
            
            if img_file:
                image_link = f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/{img_file}"
                msg = (f"🚨 แจ้งเตือนฝุ่นสีแดง ({now.strftime('%H:%M')}น.)\n"
                       f"📍 สถานี: {s['name']}\n"
                       f"🗺️ พื้นที่: {s['area']}\n"
                       f"💨 PM2.5: {s['value']} µg/m³\n"
                       f"⏰ ข้อมูลเมื่อ: {s['time']}\n"
                       f"🔍 วิเคราะห์กราฟ: {status}")
                
                send_line(msg, image_link)
        
        # บันทึกสถานีที่แจ้งไปแล้วเพื่อไม่ให้ส่งซ้ำทุกนาที
        history['alerted_ids'] = list(set(history.get('alerted_ids', []) + current_ids))
        with open(LOG_FILE, 'w') as f: json.dump(history, f)

if __name__ == "__main__":
    main()
