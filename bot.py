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
    """คำนวณ AQI ตามสูตรเส้นตรง (Interpolation) และเกณฑ์ คพ."""
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
    """วิเคราะห์ Trend 24 ชม. เพื่อลดภาระเจ้าหน้าที่ในการตรวจสอบข้อมูลซ้ำ"""
    url = f"http://air4thai.com/forweb/getHistory.php?stationID={s_id}&param=PM25&type=hr"
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        res = requests.get(url, headers=headers, timeout=20).json()
        data = res.get('station', {}).get('data', [])
        if not data: return "⚠️ ไม่พบข้อมูลประวัติ (โปรดตรวจสอบสถานีรายพื้นที่)", None

        df = pd.DataFrame(data).tail(24)
        df['value'] = pd.to_numeric(df['value'], errors='coerce')
        
        # ตรวจสอบความผิดปกติ (Data Verification)
        spike = df['value'].diff().abs().max()
        steady_red = (df['value'].tail(2) > 75.0).all() # แดงต่อเนื่อง 2 ชม.
        
        analysis = "✅ ยืนยัน: ค่าสูงต่อเนื่อง (สถานการณ์จริง)" if steady_red else "🔍 เฝ้าระวัง: ค่าเพิ่งเริ่มพุ่งสูง"
        if spike > 50: analysis = f"⚠️ แจ้งเตือน: ค่าแกว่งผิดปกติ ({spike:.1f} µg/m³) อาจเป็น Error เฉพาะจุด"

        # วาดกราฟ Trend
        plt.figure(figsize=(10, 5))
        plt.plot(df['datetime'].str[-5:], df['value'], marker='o', color='#c0392b', linewidth=2)
        plt.axhline(y=75.0, color='black', linestyle='--', alpha=0.5, label='Red Line')
        plt.title(f"PM2.5 Analysis 24h: {s_name}", fontsize=12)
        plt.grid(True, alpha=0.3)
        plt.tight_layout()
        
        filename = f"trend_{s_id}.png"
        plt.savefig(filename)
        plt.close()
        return analysis, filename
    except:
        return "❌ ระบบประวัติขัดข้องชั่วคราว", None

def send_official_alert(s, analysis, img_file):
    url = "https://api.line.me/v2/bot/message/push"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {LINE_TOKEN}"}
    
    calc_aqi = calculate_thai_aqi(s['pm25'])
    
    text = (f"🚨 [รายงานเฝ้าระวังวิกฤตฝุ่นละออง]\n"
            f"📍 สถานี: {s['name']}\n"
            f"🗺️ {s['area']}\n"
            f"😷 AQI (คำนวณ): {calc_aqi} (สีแดง-อันตราย)\n"
            f"💨 PM2.5: {s['pm25']} µg/m³\n"
            f"⏰ ข้อมูล ณ: {s['time']}\n"
            f"📊 ผลวิเคราะห์ Trend: {analysis}\n"
            f"🆘 ข้อแนะนำ: ประชาชนงดกิจกรรมกลางแจ้งเด็ดขาด เจ้าหน้าที่พื้นที่เตรียมแผนเผชิญเหตุ")

    messages = [{"type": "text", "text": text}]
    if img_file:
        ts = int(datetime.datetime.now().timestamp())
        img_url = f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/{img_file}?t={ts}"
        messages.append({"type": "image", "originalContentUrl": img_url, "previewImageUrl": img_url})

    requests.post(url, headers=headers, json={"to": USER_ID, "messages": messages})

def main():
    api_url = "http://air4thai.com/forweb/getAQI_JSON.php"
    try:
        res = requests.get(api_url).json()
        for s in res.get('stations', []):
            # ดึงข้อมูลแบบปลอดภัย (Safe Access) เพื่อแก้ KeyError
            aqi_last = s.get('AQILast', {})
            pm25_obj = aqi_last.get('PM25', {})
            pm25_val = pm25_obj.get('value')
            
            # ตรวจสอบเงื่อนไขแจ้งเตือนเฉพาะพื้นที่สีแดง (> 75.0)
            if pm25_val and float(pm25_val) > 75.0 and s.get('stationID') != "11t":
                data = {
                    "id": s.get('stationID'),
                    "name": s.get('nameTH'),
                    "area": s.get('areaTH'),
                    "pm25": float(pm25_val),
                    "time": pm25_obj.get('datetime', datetime.datetime.now(TIMEZONE).strftime('%Y-%m-%d %H:%M'))
                }
                analysis, img = verify_and_analyze(data['id'], data['name'])
                send_official_alert(data, analysis, img)
    except Exception as e:
        print(f"Main Loop Error: {e}")

if __name__ == "__main__":
    main()
