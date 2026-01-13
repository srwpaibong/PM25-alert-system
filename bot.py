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

# กำหนดเวลาการรายงานหลัก (จะตรวจสอบทุกครั้งที่รัน แต่จะส่งสรุปตามรอบนี้)
REPORT_HOURS = [7, 9, 12, 17]

def calculate_thai_aqi(pm25):
    """คำนวณ AQI ตามเกณฑ์ คพ."""
    if pm25 <= 15.0: xi, xj, ii, ij = 0, 15.0, 0, 25
    elif pm25 <= 25.0: xi, xj, ii, ij = 15.1, 25.0, 26, 50
    elif pm25 <= 37.5: xi, xj, ii, ij = 25.1, 37.5, 51, 100
    elif pm25 <= 75.0: xi, xj, ii, ij = 37.6, 75.0, 101, 200
    else: xi, xj, ii, ij = 75.1, 500.0, 201, 500
    return int(round(((ij - ii) / (xj - xi)) * (pm25 - xi) + ii))

def load_log():
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, 'r') as f:
            try: return json.load(f)
            except: return {"last_date": "", "alerted_ids": []}
    return {"last_date": "", "alerted_ids": []}

def verify_and_plot(s_id, s_name):
    """วิเคราะห์ Trend และตรวจสอบความผิดปกติเพื่อช่วยเจ้าหน้าที่"""
    headers = {'User-Agent': 'Mozilla/5.0'}
    url = f"http://air4thai.com/forweb/getHistory.php?stationID={s_id}&param=PM25&type=hr"
    try:
        response = requests.get(url, headers=headers, timeout=20)
        res = response.json()
        data = res.get('station', {}).get('data', [])
        if not data: return "🔍 ไม่พบข้อมูลย้อนหลัง (ตรวจสอบรายพื้นที่)", None

        df = pd.DataFrame(data).tail(12)
        df['value'] = pd.to_numeric(df['value'], errors='coerce')
        
        # ตรวจสอบความถูกต้อง (Verification)
        spike = df['value'].diff().abs().max()
        is_steady = (df['value'].tail(2) > 75.0).all()
        
        status = "✅ ยืนยัน: แดงต่อเนื่อง (ของจริง)" if is_steady else "📈 แนวโน้ม: เพิ่งเริ่มพุ่งสูง"
        if spike > 60: status = f"⚠️ เฝ้าระวัง: ค่าแกว่งผิดปกติ ({spike:.1f})"

        # สร้างกราฟ
        plt.figure(figsize=(10, 4))
        plt.plot(df['datetime'].str[-5:], df['value'], marker='o', color='#c0392b')
        plt.axhline(y=75.0, color='black', linestyle='--', alpha=0.5)
        plt.title(f"Trend 12h: {s_name}")
        plt.grid(True, alpha=0.2)
        plt.tight_layout()
        
        filename = f"trend_{s_id}.png"
        plt.savefig(filename)
        plt.close()
        return status, filename
    except:
        return "❌ ระบบประวัติขัดข้องชั่วคราว", None

def send_alert(s, analysis, img_file):
    url = "https://api.line.me/v2/bot/message/push"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {LINE_TOKEN}"}
    
    aqi = calculate_thai_aqi(s['pm25'])
    msg = (f"🚨 [รายงานเฝ้าระวังวิกฤตฝุ่นละออง]\n"
           f"📍 สถานี: {s['name']}\n"
           f"🗺️ {s['area']}\n"
           f"😷 AQI (คำนวณ): {aqi} (สีแดง-อันตราย)\n"
           f"💨 PM2.5: {s['pm25']} µg/m³\n"
           f"⏰ ข้อมูล ณ: {s['time']}\n"
           f"📊 ผลวิเคราะห์ Trend: {analysis}")

    messages = [{"type": "text", "text": msg}]
    if img_file:
        ts = int(datetime.datetime.now().timestamp())
        img_url = f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/{img_file}?t={ts}"
        messages.append({"type": "image", "originalContentUrl": img_url, "previewImageUrl": img_url})

    requests.post(url, headers=headers, json={"to": USER_ID, "messages": messages})

def main():
    now = datetime.datetime.now(TIMEZONE)
    today = now.strftime("%Y-%m-%d")
    history = load_log()
    
    # รีเซ็ต log ทุกวันใหม่
    if history.get('last_date') != today:
        history = {"last_date": today, "alerted_ids": []}

    res = requests.get("http://air4thai.com/forweb/getAQI_JSON.php").json()
    current_red_stations = []
    
    for s in res.get('stations', []):
        pm25_val = s.get('AQILast', {}).get('PM25', {}).get('value')
        if pm25_val and float(pm25_val) > 75.0 and s.get('stationID') != "11t":
            current_red_stations.append({
                "id": s['stationID'], "name": s['nameTH'], "area": s['areaTH'],
                "pm25": float(pm25_val), "time": s['AQILast']['PM25'].get('datetime', 'N/A')
            })

    # ตรวจสอบเงื่อนไขการส่ง: เป็นเวลาที่กำหนด หรือ มีสถานีแดงใหม่ที่ยังไม่เคยแจ้งในวันนี้
    new_stations = [s for s in current_red_stations if s['id'] not in history['alerted_ids']]
    is_scheduled = now.hour in REPORT_HOURS and now.minute < 15 # เผื่อเวลารัน 15 นาที

    if new_stations or (is_scheduled and current_red_stations):
        # กรณีพบสถานีใหม่: แจ้งเฉพาะสถานีใหม่ทันที
        # กรณีถึงรอบเวลา: แจ้งสถานีสีแดงที่ยังไม่เคยแจ้งในรอบก่อนๆ ของวันนี้
        for s in new_stations:
            analysis, img = verify_and_plot(s['id'], s['name'])
            send_alert(s, analysis, img)
            history['alerted_ids'].append(s['id'])
            
        with open(LOG_FILE, 'w') as f:
            json.dump(history, f)

if __name__ == "__main__":
    main()
