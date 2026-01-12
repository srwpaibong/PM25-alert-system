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

def load_log():
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, 'r') as f:
            try: return json.load(f)
            except: return {"last_date": "", "alerted_ids": []}
    return {"last_date": "", "alerted_ids": []}

def get_red_stations():
    url = "http://air4thai.com/forweb/getAQI_JSON.php"
    print("--- 1. เริ่มดึงข้อมูลจาก Air4Thai ---")
    try:
        res = requests.get(url, timeout=30).json()
        red_list = []
        count_all = 0
        for s in res.get('stations', []):
            count_all += 1
            s_id = s.get('stationID')
            s_type = s.get('stationType', '').lower()
            try: pm25 = float(s['AQILast']['PM25']['value'])
            except: pm25 = 0
            
            # เงื่อนไขทดสอบ: ปรับเป็น > 0 เพื่อให้เจอทุกสถานี
            if s_id != "11t" and s_type != "bkk" and pm25 > 0:
                red_list.append({"id": s_id, "name": s['nameTH'], "area": s['areaTH'], "value": pm25})
        
        print(f"ตรวจพบทั้งหมด {count_all} สถานี")
        print(f"ผ่านเกณฑ์คัดกรอง (ไม่ใช่ 11t/BKK และ > 0) จำนวน {len(red_list)} สถานี")
        return red_list
    except Exception as e:
        print(f"Error ดึงข้อมูล: {e}")
        return []

def send_line(message, image_url):
    print(f"--- 3. กำลังส่ง LINE ไปยัง ID: {USER_ID[:5]}... ---")
    url = "https://api.line.me/v2/bot/message/push"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {LINE_TOKEN}"}
    payload = {
        "to": USER_ID,
        "messages": [
            {"type": "text", "text": message},
            {"type": "image", "originalContentUrl": image_url, "previewImageUrl": image_url}
        ]
    }
    response = requests.post(url, headers=headers, json=payload)
    print(f"LINE Response: {response.status_code} - {response.text}")

def main():
    now = datetime.datetime.now(TIMEZONE)
    print(f"เวลาปัจจุบัน: {now.strftime('%Y-%m-%d %H:%M:%S')}")
    
    red_stations = get_red_stations()
    
    if not red_stations:
        print("❌ จบการทำงาน: ไม่พบสถานีที่ตรงตามเงื่อนไข")
        return

    print(f"--- 2. เริ่มขั้นตอนการส่งข้อความ (บังคับส่ง True) ---")
    # บังคับส่งสถานีแรกที่เจอเพื่อทดสอบ
    s = red_stations[0]
    msg = f"🧪 ทดสอบระบบส่งข้อความ\n📍 {s['name']}\n💨 PM2.5: {s['value']}"
    # ใช้รูปภาพตัวอย่างจากเน็ตเพื่อทดสอบว่า LINE ยอมรับรูปไหม
    test_img = "https://www.air4thai.com/forweb/assets/img/logo_pcd_air4thai.png"
    
    send_line(msg, test_img)
    print("✅ สิ้นสุดการทำงานหลัก")

if __name__ == "__main__":
    main()
