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
GITHUB_REPO = os.getenv('GITHUB_REPOSITORY') # ดึงชื่อ User/Repo อัตโนมัติ

LOG_FILE = "log.json"
TIMEZONE = pytz.timezone('Asia/Bangkok')
REPORT_HOURS = [7, 8, 9, 12, 15, 17]

def load_log():
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, 'r') as f: return json.load(f)
    return {"last_date": "", "alerted_ids": []}

def get_red_stations():
    url = "http://air4thai.com/forweb/getAQI_JSON.php"
    res = requests.get(url).json()
    red_list = []
    for s in res['stations']:
        s_id = s['stationID']
        s_type = s.get('stationType', '').lower()
        try: pm25 = float(s['AQILast']['PM25']['value'])
        except: pm25 = 0
        
        # เงื่อนไข: ไม่เอา 11t, ไม่เอา BKK, ต้องสีแดง (> 75.1)
        if s_id != "11t" and s_type != "bkk" and pm25 > 75.1:
            red_list.append({"id": s_id, "name": s['nameTH'], "area": s['areaTH'], "value": pm25})
    return red_list

def analyze_and_plot(s_id, s_name):
    # เพิ่ม Headers เพื่อหลอกว่าเราเป็น Browser ปกติ (ป้องกันโดน Block)
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    url = f"http://air4thai.com/forweb/getHistory.php?stationID={s_id}&param=PM25&type=hr"
    
    try:
        response = requests.get(url, headers=headers, timeout=30)
        # เช็คว่าเซิร์ฟเวอร์ส่งค่าสำเร็จไหม (200 คือ OK)
        if response.status_code != 200:
            return "ตรวจสอบไม่ได้ ❓", f"เซิร์ฟเวอร์ขัดข้อง ({response.status_code})"
            
        res = response.json()
        
        # ตรวจสอบว่ามีข้อมูลส่งมาจริงไหม
        if 'station' not in res or 'data' not in res['station']:
            return "ไม่มีข้อมูลย้อนหลัง ❓", "ไม่พบประวัติ 48 ชม."

        df = pd.DataFrame(res['station']['data']).tail(48)
        # ... (โค้ดส่วนที่เหลือของการพล็อตกราฟเหมือนเดิม) ...
        # (หมายเหตุ: ตรวจสอบให้แน่ใจว่าได้ใส่ plt.close() ทุกครั้งหลัง savefig เพื่อคืนหน่วยความจำ)

def send_line(message, image_url):
    url = "https://api.line.me/v2/bot/message/push"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {LINE_TOKEN}"}
    # เพิ่ม timestamp ใน URL เพื่อป้องกัน LINE จำภาพเก่า (Cache Busting)
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
    if history['last_date'] != today: history = {"last_date": today, "alerted_ids": []}

    red_stations = get_red_stations()
    if not red_stations: return

    current_ids = [s['id'] for s in red_stations]
    new_ids = [i for i in current_ids if i not in history['alerted_ids']]
    
    # เงื่อนไขการส่ง: ถึงเวลาที่กำหนด OR มีสถานีใหม่
    if new_ids or (now.hour in REPORT_HOURS):
        for s in red_stations:
            status, img_file = analyze_and_plot(s['id'], s['name'])
            # สร้าง Link รูปภาพจาก GitHub Raw
            image_link = f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/{img_file}"
            
            msg = f"🚨 แจ้งเตือนฝุ่นสีแดง\n📍 {s['name']}\n🗺️ {s['area']}\n💨 24ชม.: {s['value']} µg/m³\n🔍 ตรวจสอบ: {status}"
            send_line(msg, image_link)
        
        history['alerted_ids'] = list(set(history['alerted_ids'] + current_ids))
        with open(LOG_FILE, 'w') as f: json.dump(history, f)

if __name__ == "__main__":
    main()
