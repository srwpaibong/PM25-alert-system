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

def get_red_stations():
    url = "http://air4thai.com/forweb/getAQI_JSON.php"
    try:
        res = requests.get(url, timeout=30).json()
        red_list = []
        for s in res.get('stations', []):
            aqi_last = s.get('AQILast', {})
            pm25_obj = aqi_last.get('PM25', {})
            aqi_val = aqi_last.get('AQI', {}).get('value', 'N/A')
            
            try: pm25 = float(pm25_obj.get('value', 0))
            except: pm25 = 0
            
            # เงื่อนไข: เฉพาะสีแดง (> 75.0) และไม่ใช่ BKK/11t
            if s.get('stationID') != "11t" and s.get('stationType', '').lower() != 'bkk' and pm25 > 75.0:
                red_list.append({
                    "id": s.get('stationID'),
                    "name": s.get('nameTH'),
                    "area": s.get('areaTH'),
                    "pm25": pm25,
                    "aqi": aqi_val,
                    "time": pm25_obj.get('datetime', 'N/A')
                })
        return red_list
    except: return []

def verify_and_plot(s_id, s_name):
    """ตรวจสอบความผิดปกติและวาดกราฟ"""
    url = f"http://air4thai.com/forweb/getHistory.php?stationID={s_id}&param=PM25&type=hr"
    try:
        res = requests.get(url, timeout=30).json()
        data = res.get('station', {}).get('data', [])
        if not data: return "ไม่พบข้อมูลประวัติ", None
        
        df = pd.DataFrame(data).tail(12) # ดูย้อนหลัง 12 ชั่วโมง
        df['value'] = pd.to_numeric(df['value'], errors='coerce')
        
        # 1. เช็คค่ากระโดด (Spike Check)
        diff = df['value'].diff().abs().max()
        
        # 2. เช็คความเสถียร (เสถียรคือแดงต่อเนื่อง 3 ชม. ขึ้นไป)
        is_persistent = (df['value'].tail(3) > 75.0).all()
        
        verification_msg = ""
        if diff > 60:
            verification_msg = "⚠️ พบค่าพุ่งสูงผิดปกติ (อาจเป็น Error)"
        elif is_persistent:
            verification_msg = "✅ ข้อมูลมีความต่อเนื่อง (แนวโน้มแดงจริง)"
        else:
            verification_msg = "🔍 อยู่ในช่วงเริ่มวิกฤต (เฝ้าระวัง)"

        # วาดกราฟ
        plt.figure(figsize=(10, 5))
        plt.plot(df['datetime'], df['value'], marker='o', color='#c0392b')
        plt.axhline(y=75.0, color='gray', linestyle='--')
        plt.title(f"Trend 12h: {s_name}")
        plt.xticks(rotation=45, fontsize=8)
        plt.tight_layout()
        
        filename = f"graph_{s_id}.png"
        plt.savefig(filename)
        plt.close()
        return verification_msg, filename
    except:
        return "ไม่สามารถตรวจสอบประวัติได้", None

def send_line_red_alert(s, verify_msg, img_file):
    url = "https://api.line.me/v2/bot/message/push"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {LINE_TOKEN}"}
    
    msg_text = (f"🚨 แจ้งเตือนด่วน! พื้นที่สีแดง\n"
                f"📍 สถานี: {s['name']}\n"
                f"🗺️ {s['area']}\n"
                f"😷 AQI: {s['aqi']}\n"
                f"💨 PM2.5: {s['pm25']} µg/m³\n"
                f"⏰ ข้อมูลล่าสุด: {s['time']}\n"
                f"🧐 ผลการตรวจสอบ: {verify_msg}")

    messages = [{"type": "text", "text": msg_text}]
    
    if img_file:
        ts = int(datetime.datetime.now().timestamp())
        img_url = f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/{img_file}?t={ts}"
        messages.append({"type": "image", "originalContentUrl": img_url, "previewImageUrl": img_url})

    requests.post(url, headers=headers, json=payload={"to": USER_ID, "messages": messages})

def main():
    print("--- เริ่มตรวจสอบสถานีสีแดง ---")
    red_stations = get_red_stations()
    if not red_stations:
        print("ขณะนี้ไม่มีสถานีสีแดง (นอกเขต BKK)")
        return

    for s in red_stations:
        verify_msg, img_file = verify_and_plot(s['id'], s['name'])
        send_line_red_alert(s, verify_msg, img_file)
        print(f"ส่งแจ้งเตือนสถานี {s['name']} เรียบร้อย")

if __name__ == "__main__":
    main()
