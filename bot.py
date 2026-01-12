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

def calculate_thai_aqi(pm25):
    """คำนวณ AQI ตามตารางและสูตรที่กำหนด"""
    if pm25 <= 15.0:
        xi, xj, ii, ij = 0, 15.0, 0, 25
    elif pm25 <= 25.0:
        xi, xj, ii, ij = 15.1, 25.0, 26, 50
    elif pm25 <= 37.5:
        xi, xj, ii, ij = 25.1, 37.5, 51, 100
    elif pm25 <= 75.0:
        xi, xj, ii, ij = 37.6, 75.0, 101, 200
    else: # 75.1 ขึ้นไป
        xi, xj, ii, ij = 75.1, 500.0, 201, 500
        
    aqi = ((ij - ii) / (xj - xi)) * (pm25 - xi) + ii
    return int(round(aqi))

def verify_and_analyze(s_id, s_name):
    """ตรวจสอบความผิดปกติและดึงข้อมูลย้อนหลังเพื่อวิเคราะห์ Trend"""
    url = f"http://air4thai.com/forweb/getHistory.php?stationID={s_id}&param=PM25&type=hr"
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        res = requests.get(url, headers=headers, timeout=20).json()
        data = res.get('station', {}).get('data', [])
        if not data: return "⚠️ ไม่พบข้อมูลย้อนหลัง", None

        df = pd.DataFrame(data).tail(24)
        df['value'] = pd.to_numeric(df['value'], errors='coerce')
        
        # เช็คอัตราการเปลี่ยนค่า (Rate of Change)
        spike = df['value'].diff().abs().max()
        # เช็คความต่อเนื่อง (Persistence)
        steady_red = (df['value'].tail(3) > 75.0).all()
        
        analysis = "✅ ยืนยัน: แดงต่อเนื่อง (สถานการณ์จริง)" if steady_red else "🔍 ตรวจสอบ: ค่าเพิ่งพุ่งสูงขึ้น"
        if spike > 50: analysis = f"⚠️ เฝ้าระวัง: ค่าแกว่งผิดปกติ ({spike:.1f} µg/m³)"

        # วาดกราฟ Trend 24 ชม.
        plt.figure(figsize=(10, 5))
        plt.plot(df['datetime'].str[-5:], df['value'], marker='o', color='#c0392b', linewidth=2)
        plt.axhline(y=75.0, color='black', linestyle='--', alpha=0.5, label='Red Threshold')
        plt.title(f"PM2.5 Analysis 24h: {s_name}", fontsize=12)
        plt.grid(True, alpha=0.3)
        plt.tight_layout()
        
        filename = f"trend_{s_id}.png"
        plt.savefig(filename)
        plt.close()
        return analysis, filename
    except:
        return "❌ ระบบประวัติขัดข้อง", None

def send_official_alert(s, analysis, img_file):
    url = "https://api.line.me/v2/bot/message/push"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {LINE_TOKEN}"}
    
    # คำนวณ AQI เองเพื่อให้ได้ข้อมูลที่ถูกต้องแม่นยำ
    calc_aqi = calculate_thai_aqi(s['pm25'])
    
    text = (f"🚨 [รายงานเฝ้าระวังระดับวิกฤต]\n"
            f"📍 สถานี: {s['name']}\n"
            f"🗺️ {s['area']}\n"
            f"😷 AQI: {calc_aqi} (สีแดง)\n"
            f"💨 PM2.5: {s['pm25']} µg/m³\n"
            f"⏰ ข้อมูลล่าสุด: {s['time']}\n"
            f"📊 ผลวิเคราะห์: {analysis}\n"
            f"📢 ข้อเสนอแนะ: เจ้าหน้าที่พื้นที่ควรลงตรวจสอบจุดความร้อน (Hotspot) รอบสถานี")

    messages = [{"type": "text", "text": text}]
    if img_file:
        ts = int(datetime.datetime.now().timestamp())
        img_url = f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/{img_file}?t={ts}"
        messages.append({"type": "image", "originalContentUrl": img_url, "previewImageUrl": img_url})

    requests.post(url, headers=headers, json={"to": USER_ID, "messages": messages})

def main():
    api_url = "http://air4thai.com/forweb/getAQI_JSON.php"
    res = requests.get(api_url).json()
    
    for s in res.get('stations', []):
        pm25_val = s.get('AQILast', {}).get('PM25', {}).get('value')
        if pm25_val and float(pm25_val) > 75.0 and s['stationID'] != "11t":
            data = {
                "id": s['stationID'], "name": s['nameTH'], "area": s['areaTH'],
                "pm25": float(pm25_val), "time": s['AQILast']['PM25']['datetime']
            }
            analysis, img = verify_and_analyze(data['id'], data['name'])
            send_official_alert(data, analysis, img)

if __name__ == "__main__":
    main()
