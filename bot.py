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

# รอบเวลาการรายงานหลัก
REPORT_HOURS = [7, 9, 12, 17]

def calculate_thai_aqi(pm25):
    """คำนวณ AQI ตามเกณฑ์วิชาการ คพ."""
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
    """วิเคราะห์ Trend 24 ชม. เพื่อยืนยันความถูกต้องของข้อมูล"""
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    url = f"http://air4thai.com/forweb/getHistory.php?stationID={s_id}&param=PM25&type=hr"
    try:
        # ลองดึงข้อมูล (Retry logic)
        for _ in range(2):
            response = requests.get(url, headers=headers, timeout=25)
            if response.status_code == 200 and response.text: break
        
        res = response.json()
        data = res.get('station', {}).get('data', [])
        if not data: return "🔍 ไม่พบประวัติย้อนหลัง (โปรดเช็คหน้าสถานี)", None

        df = pd.DataFrame(data).tail(24)
        df['value'] = pd.to_numeric(df['value'], errors='coerce')
        
        # ตรรกะยืนยันผล (Verification)
        spike = df['value'].diff().abs().max()
        is_steady = (df['value'].tail(3) > 75.0).all()
        
        status = "✅ ยืนยัน: แดงต่อเนื่อง (สถานการณ์จริง)" if is_steady else "📈 แนวโน้ม: เพิ่งเริ่มพุ่งสูง"
        if spike > 60: status = f"⚠️ เฝ้าระวัง: ค่าแกว่งผิดปกติ ({spike:.1f} µg/m³)"

        # วาดกราฟ Trend
        plt.figure(figsize=(10, 4))
        plt.plot(df['datetime'].str[-5:], df['value'], marker='o', color='#c0392b', linewidth=2)
        plt.axhline(y=75.0, color='black', linestyle='--', alpha=0.5)
        plt.title(f"24h Trend Analysis: {s_name}")
        plt.grid(True, alpha=0.2)
        plt.tight_layout()
        
        filename = f"trend_{s_id}.png"
        plt.savefig(filename)
        plt.close()
        return status, filename
    except:
        return "❌ ระบบประวัติขัดข้อง (เซิร์ฟเวอร์ไม่ตอบสนอง)", None

def send_official_alert(s, analysis, img_file):
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
    
    if history.get('last_date') != today:
        history = {"last_date": today, "alerted_ids": []}

    res = requests.get("http://air4thai.com/forweb/getAQI_JSON.php").json()
    current_red_stations = []
    
    for s in res.get('stations', []):
        aqi_last = s.get('AQILast', {})
        pm25_obj = aqi_last.get('PM25', {})
        pm25_val = pm25_obj.get('value')
        
        if pm25_val and float(pm25_val) > 75.0 and s.get('stationID') != "11t":
            # แก้ปัญหาเวลา N/A (Safe Access)
            time_val = pm25_obj.get('datetime')
            if not time_val:
                time_val = f"{aqi_last.get('date', '')} {aqi_last.get('time', '')}".strip()
            if not time_val or time_val == "":
                time_val = now.strftime("%Y-%m-%d %H:%M")

            current_red_stations.append({
                "id": s['stationID'], "name": s['nameTH'], "area": s['areaTH'],
                "pm25": float(pm25_val), "time": time_val
            })

    # เงื่อนไขการส่ง: เป็นเวลาหลัก หรือ มีสถานีแดงใหม่เพิ่มขึ้นมา
    new_stations = [s for s in current_red_stations if s['id'] not in history['alerted_ids']]
    is_scheduled = now.hour in REPORT_HOURS and now.minute < 30 # รันในช่วง 30 นาทีแรกของชั่วโมง

    if new_stations or (is_scheduled and current_red_stations):
        for s in current_red_stations:
            # ส่งเฉพาะสถานีที่ยังไม่เคยแจ้ง "หรือ" ส่งทุกสถานีถ้าถึงรอบเวลาหลัก
            if s['id'] in new_stations or is_scheduled:
                analysis, img = verify_and_plot(s['id'], s['name'])
                send_official_alert(s, analysis, img)
                if s['id'] not in history['alerted_ids']:
                    history['alerted_ids'].append(s['id'])
            
        with open(LOG_FILE, 'w') as f:
            json.dump(history, f)

if __name__ == "__main__":
    main()
