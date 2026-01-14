import requests
import pandas as pd
import os
import json
import datetime
import pytz

# --- Configuration ---
LINE_TOKEN = os.getenv('LINE_ACCESS_TOKEN')
USER_ID = os.getenv('LINE_USER_ID')
TIMEZONE = pytz.timezone('Asia/Bangkok')
LOG_FILE = "log.json"

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
            except: return {"last_date": "", "alerted_ids": {}}
    return {"last_date": "", "alerted_ids": {}}

def analyze_station_integrity(s_id):
    """ตรวจสอบความผิดปกติของข้อมูลรายชั่วโมงย้อนหลัง 48 ชม."""
    headers = {'User-Agent': 'Mozilla/5.0'}
    url = f"http://air4thai.com/forweb/getHistory.php?stationID={s_id}&param=PM25&type=hr"
    try:
        res = requests.get(url, headers=headers, timeout=20).json()
        data = res.get('station', {}).get('data', [])
        if not data: return "⚠️ ไม่พบข้อมูลประวัติ", "N/A - N/A", None

        df = pd.DataFrame(data).tail(48)
        df['value'] = pd.to_numeric(df['value'], errors='coerce')
        
        # 1. หาค่า Min-Max
        v_min, v_max = df['value'].min(), df['value'].max()
        
        # 2. ตรวจสอบความผิดปกติ (Flags)
        issues = []
        # Spike: เปลี่ยนแปลงเกิน 50 ใน 1 ชม.
        if df['value'].diff().abs().max() > 50: issues.append("Spike")
        # Flatline: ค่านิ่งเกิน 4 ชม.
        if (df['value'].rolling(window=5).std() == 0).any(): issues.append("Flatline")
        # Negative: ค่าติดลบ
        if (df['value'] < 0).any(): issues.append("Negative")
        # Missing: ข้อมูลขาดหาย (เช็คช่องว่างเวลา)
        if df['value'].isnull().sum() > 3: issues.append("Missing Data")

        status = "✅ ปกติ" if not issues else f"⚠️ ผิดปกติ ({', '.join(issues)})"
        
        # หาเวลาที่เริ่มแดง (Timestamp แรกที่ต่อเนื่องถึงปัจจุบันที่ > 75)
        red_start = None
        for i in range(len(df)-1, -1, -1):
            if df.iloc[i]['value'] > 75:
                red_start = df.iloc[i]['datetime']
            else:
                break
                
        return status, f"{v_min} - {v_max}", red_start
    except:
        return "❌ ระบบประวัติขัดข้อง", "N/A", None

def main():
    now = datetime.datetime.now(TIMEZONE)
    today = now.strftime("%Y-%m-%d")
    history = load_log()
    
    if history.get('last_date') != today:
        history = {"last_date": today, "alerted_ids": {}}

    res = requests.get("http://air4thai.com/forweb/getAQI_JSON.php").json()
    all_red_stations = []
    
    for s in res.get('stations', []):
        s_id = s.get('stationID')
        pm25_val = s.get('AQILast', {}).get('PM25', {}).get('value')
        
        # กรองเฉพาะสีแดง (>75) และไม่ใช่ 11t
        if pm25_val and float(pm25_val) > 75.0 and s_id != "11t":
            status, v_range, red_start = analyze_station_integrity(s_id)
            all_red_stations.append({
                "id": s_id,
                "name": s['nameTH'],
                "area": s['areaTH'],
                "pm25": float(pm25_val),
                "aqi": calculate_thai_aqi(float(pm25_val)),
                "time": s.get('AQILast', {}).get('PM25', {}).get('datetime', now.strftime("%Y-%m-%d %H:%M")),
                "integrity": status,
                "range": v_range,
                "red_since": red_start if red_start else s.get('AQILast', {}).get('PM25', {}).get('datetime', '9999-99-99')
            })

    # เรียงลำดับตามเวลาที่เริ่มแดง (ก่อนไปหลัง)
    all_red_stations.sort(key=lambda x: x['red_since'])

    # ตรวจสอบสถานีใหม่
    new_count = 0
    for s in all_red_stations:
        if s['id'] not in history['alerted_ids']:
            new_count += 1
            history['alerted_ids'][s['id']] = s['time']

    # ถ้ามีสถานีใหม่ ให้ส่งรายงานสรุปเพียงข้อความเดียว
    if new_count > 0:
        header = (f"📊 [สรุปรายงานวิกฤต PM2.5]\n"
                  f"⏰ ตรวจสอบล่าสุด: {now.strftime('%H:%M น.')}\n"
                  f"🔴 พบระดับสีแดงทั้งหมด: {len(all_red_stations)} สถานี\n"
                  f"🆕 พบสถานีใหม่ในรอบนี้: {new_count} สถานี\n"
                  f"----------------------------")
        
        details = []
        for i, s in enumerate(all_red_stations, 1):
            detail = (f"{i}. {s['name']} ({s['id']})\n"
                      f"📍 {s['area']}\n"
                      f"😷 AQI: {s['aqi']} | PM2.5: {s['pm25']}\n"
                      f"📈 48ชม: {s['range']} µg/m³\n"
                      f"🔍 สถานะ: {s['integrity']}\n"
                      f"⏰ ข้อมูล ณ: {s['time']}")
            details.append(detail)
        
        full_message = header + "\n" + "\n---\n".join(details)
        
        # ส่ง LINE
        url = "https://api.line.me/v2/bot/message/push"
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {LINE_TOKEN}"}
        payload = {"to": USER_ID, "messages": [{"type": "text", "text": full_message}]}
        requests.post(url, headers=headers, json=payload)
        
        with open(LOG_FILE, 'w') as f:
            json.dump(history, f)
            
    print(f"สแกนเสร็จสิ้น: พบ {len(all_red_stations)} สถานีแดง (แจ้งใหม่ {new_count})")

if __name__ == "__main__":
    main()
