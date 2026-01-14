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

def calculate_thai_aqi(pm25):
    """คำนวณ AQI ตามสูตรเส้นตรงและเกณฑ์ คพ."""
    if pm25 <= 15.0: xi, xj, ii, ij = 0, 15.0, 0, 25
    elif pm25 <= 25.0: xi, xj, ii, ij = 15.1, 25.0, 26, 50
    elif pm25 <= 37.5: xi, xj, ii, ij = 25.1, 37.5, 51, 100
    elif pm25 <= 75.0: xi, xj, ii, ij = 37.6, 75.0, 101, 200
    else: xi, xj, ii, ij = 75.1, 500.0, 201, 500
    
    aqi = ((ij - ii) / (xj - xi)) * (pm25 - xi) + ii
    return int(round(aqi))

def load_log():
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, 'r') as f:
            try: return json.load(f)
            except: return {"last_date": "", "alerted_ids": []}
    return {"last_date": "", "alerted_ids": []}

def verify_and_plot(s_id, s_name):
    """ดึงข้อมูล 24 ชม. เพื่อยืนยันความถูกต้องและวิเคราะห์แนวโน้ม"""
    headers = {'User-Agent': 'Mozilla/5.0'}
    url = f"http://air4thai.com/forweb/getHistory.php?stationID={s_id}&param=PM25&type=hr"
    try:
        response = requests.get(url, headers=headers, timeout=25)
        res = response.json()
        data = res.get('station', {}).get('data', [])
        if not data: return "🔍 ไม่พบประวัติย้อนหลัง", None

        df = pd.DataFrame(data).tail(24)
        df['value'] = pd.to_numeric(df['value'], errors='coerce')
        
        # วิเคราะห์ความผิดปกติ (Anomaly Detection)
        spike = df['value'].diff().abs().max()
        steady_red = (df['value'].tail(2) > 75.0).all()
        
        analysis = "✅ ยืนยัน: แดงต่อเนื่อง (สถานการณ์จริง)" if steady_red else "📈 แนวโน้ม: เพิ่งเริ่มพุ่งสูง"
        if spike > 60: analysis = f"⚠️ เฝ้าระวัง: ค่าแกว่งผิดปกติ ({spike:.1f} µg/m³)"

        plt.figure(figsize=(10, 4))
        plt.plot(df['datetime'].str[-5:], df['value'], marker='o', color='#c0392b', linewidth=2)
        plt.axhline(y=75.0, color='black', linestyle='--', alpha=0.5)
        plt.title(f"24h Trend Analysis: {s_name}")
        plt.grid(True, alpha=0.2)
        plt.tight_layout()
        
        filename = f"trend_{s_id}.png"
        plt.savefig(filename)
        plt.close()
        return analysis, filename
    except:
        return "❌ ระบบประวัติขัดข้องชั่วคราว", None

def send_alert(s, analysis, img_file):
    url = "https://api.line.me/v2/bot/message/push"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {LINE_TOKEN}"}
    
    aqi = calculate_thai_aqi(s['pm25'])
    msg = (f"🚨 [รายงานเฝ้าระวังวิกฤตฝุ่นละออง]\n"
           f"📍 สถานี: {s['name']}\n"
           f"🗺️ {s['area']}\n"
           f"😷 AQI (คำนวณ): {aqi} (สีแดง)\n"
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
    
    # รีเซ็ต Log เมื่อขึ้นวันใหม่
    if history.get('last_date') != today:
        history = {"last_date": today, "alerted_ids": []}

    api_url = "http://air4thai.com/forweb/getAQI_JSON.php"
    res = requests.get(api_url).json()
    
    for s in res.get('stations', []):
        s_id = s.get('stationID')
        pm25_val = s.get('AQILast', {}).get('PM25', {}).get('value')
        
        # เงื่อนไข: สีแดง (>75.0), ยกเว้นสถานี 11t, และยังไม่ได้แจ้งในวันนี้
        if pm25_val and float(pm25_val) > 75.0 and s_id != "11t":
            if s_id not in history['alerted_ids']:
                # จัดการเรื่องเวลาแบบปลอดภัย
                time_val = s.get('AQILast', {}).get('PM25', {}).get('datetime')
                if not time_val:
                    time_val = now.strftime("%Y-%m-%d %H:%M")

                data = {
                    "id": s_id, "name": s['nameTH'], "area": s['areaTH'],
                    "pm25": float(pm25_val), "time": time_val
                }
                
                analysis, img = verify_and_plot(data['id'], data['name'])
                send_alert(data, analysis, img)
                
                # บันทึกสถานีที่แจ้งไปแล้ว
                history['alerted_ids'].append(s_id)
            
    with open(LOG_FILE, 'w') as f:
        json.dump(history, f)

if __name__ == "__main__":
    main()
