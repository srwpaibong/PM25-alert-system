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
    """ตรวจสอบความผิดปกติย้อนหลัง 48 ชม."""
    headers = {'User-Agent': 'Mozilla/5.0'}
    url = f"http://air4thai.com/forweb/getHistory.php?stationID={s_id}&param=PM25&type=hr"
    try:
        res = requests.get(url, headers=headers, timeout=20).json()
        data = res.get('station', {}).get('data', [])
        if not data: return "⚠️ ไม่พบประวัติ", "N/A", None

        df = pd.DataFrame(data).tail(48)
        df['value'] = pd.to_numeric(df['value'], errors='coerce')
        
        v_min, v_max = df['value'].min(), df['value'].max()
        issues = []
        if df['value'].diff().abs().max() > 50: issues.append("Spike")
        if (df['value'].rolling(window=5).std() == 0).any(): issues.append("Flatline")
        if (df['value'] < 0).any(): issues.append("ติดลบ")
        if df['value'].isnull().sum() > 3: issues.append("ข้อมูลหาย")

        status = "✅ ปกติ" if not issues else f"⚠️ ผิดปกติ ({', '.join(issues)})"
        
        # หาจุดเริ่มต้นที่แดงต่อเนื่อง
        red_start = None
        for i in range(len(df)-1, -1, -1):
            if df.iloc[i]['value'] > 75: red_start = df.iloc[i]['datetime']
            else: break
        return status, f"{v_min}-{v_max}", red_start
    except:
        return "❌ ระบบประวัติขัดข้อง", "N/A", None

def main():
    now = datetime.datetime.now(TIMEZONE)
    today = now.strftime("%Y-%m-%d")
    history = load_log()
    if history.get('last_date') != today:
        history = {"last_date": today, "alerted_ids": {}}

    res = requests.get("http://air4thai.com/forweb/getAQI_JSON.php").json()
    all_red = []
    
    for s in res.get('stations', []):
        s_id = s.get('stationID')
        val = s.get('AQILast', {}).get('PM25', {}).get('value')
        if val and float(val) > 75.0 and s_id != "11t":
            status, v_range, r_start = analyze_station_integrity(s_id)
            all_red.append({
                "id": s_id, "name": s['nameTH'], "area": s['areaTH'],
                "pm25": float(val), "aqi": calculate_thai_aqi(float(val)),
                "time": s['AQILast']['PM25'].get('datetime', now.strftime("%H:%M")),
                "integrity": status, "range": v_range, "red_since": r_start or "9999"
            })

    all_red.sort(key=lambda x: x['red_since'])
    new_stations = [s for s in all_red if s['id'] not in history['alerted_ids']]

    if new_stations:
        header = (f"📊 [สรุปรายงานวิกฤต PM2.5]\n"
                  f"⏰ ตรวจสอบ: {now.strftime('%H:%M น.')}\n"
                  f"🔴 รวมสีแดง: {len(all_red)} สถานี | 🆕 ใหม่: {len(new_stations)}\n"
                  f"----------------------------")
        details = []
        for i, s in enumerate(all_red, 1):
            history['alerted_ids'][s['id']] = s['time']
            details.append(f"{i}. {s['name']} ({s['id']})\n📍 {s['area']}\n😷 AQI:{s['aqi']} | PM2.5:{s['pm25']}\n📈 48ชม:{s['range']} | 🔍:{s['integrity']}\n⏰ ข้อมูล:{s['time']}")
        
        full_msg = header + "\n" + "\n---\n".join(details)
        requests.post("https://api.line.me/v2/bot/message/push", 
                      headers={"Content-Type": "application/json", "Authorization": f"Bearer {LINE_TOKEN}"},
                      json={"to": USER_ID, "messages": [{"type": "text", "text": full_msg}]})
        with open(LOG_FILE, 'w') as f: json.dump(history, f)

if __name__ == "__main__":
    main()
