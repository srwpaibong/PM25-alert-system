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

def analyze_station_integrity(s_id):
    """วิเคราะห์ข้อมูลย้อนหลัง 48 ชม. ด้วย API ใหม่"""
    now = datetime.datetime.now(TIMEZONE)
    edate = now.strftime("%Y-%m-%d")
    sdate = (now - datetime.timedelta(days=2)).strftime("%Y-%m-%d")
    
    url = f"http://air4thai.com/forweb/getHistoryData.php?stationID={s_id}&param=PM25&type=hr&sdate={sdate}&edate={edate}&stime=00&etime=23"
    headers = {'User-Agent': 'Mozilla/5.0'}
    
    try:
        res = requests.get(url, headers=headers, timeout=25).json()
        # ข้อมูลอยู่ภายใต้ stations[0]['data']
        data = res.get('stations', [{}])[0].get('data', [])
        if not data: return "⚠️ ไม่พบประวัติ", "N/A", "ไม่ทราบเวลา"

        df = pd.DataFrame(data)
        # เปลี่ยนชื่อ column ให้จัดการง่ายขึ้น
        df.rename(columns={'DATETIMEDATA': 'datetime', 'PM25': 'value'}, inplace=True)
        df['value'] = pd.to_numeric(df['value'], errors='coerce')
        
        # 1. วิเคราะห์ Min-Max
        v_min, v_max = df['value'].min(), df['value'].max()
        
        # 2. ตรวจสอบความผิดปกติ (Integrity Checks)
        issues = []
        if df['value'].diff().abs().max() > 50: issues.append("Spike")
        if (df['value'].rolling(window=5).std() == 0).any(): issues.append("Flatline")
        if (df['value'] < 0).any(): issues.append("ค่าติดลบ")
        if df['value'].isnull().sum() > 3: issues.append("ข้อมูลหาย")
        
        integrity_status = "✅ ปกติ" if not issues else f"⚠️ {', '.join(issues)}"
        
        # 3. หาเวลาที่เริ่มแดง (Red Since)
        # ไล่จากล่าสุดย้อนกลับไป หาจุดที่ค่าต่ำกว่า 75.1 ครั้งแรก
        red_start_time = "แดงต่อเนื่องเกิน 48 ชม."
        for i in range(len(df)-1, -1, -1):
            if df.iloc[i]['value'] <= 75.0:
                if i < len(df)-1:
                    red_start_time = df.iloc[i+1]['datetime']
                break
        elif len(df) > 0 and df.iloc[0]['value'] > 75.0:
            red_start_time = df.iloc[0]['datetime']

        return integrity_status, f"{v_min}-{v_max}", red_start_time
    except Exception as e:
        return f"❌ ระบบขัดข้อง ({str(e)[:10]})", "N/A", "N/A"

def load_log():
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, 'r') as f:
            try: return json.load(f)
            except: return {"last_date": "", "alerted_ids": {}}
    return {"last_date": "", "alerted_ids": {}}

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
            integrity, v_range, red_since = analyze_station_integrity(s_id)
            all_red.append({
                "id": s_id, "name": s['nameTH'], "area": s['areaTH'],
                "pm25": float(val), "aqi": calculate_thai_aqi(float(val)),
                "time": s['AQILast']['PM25'].get('datetime', now.strftime("%H:%M")),
                "integrity": integrity, "range": v_range, "red_since": red_since
            })

    # เรียงลำดับตามสถานีที่แดงก่อน (red_since)
    all_red.sort(key=lambda x: x['red_since'])

    new_stations = [s for s in all_red if s['id'] not in history['alerted_ids']]

    if new_stations:
        # ส่วนสรุปตอนหัวข้อ
        header = (f"📊 *[สรุปรายงานวิกฤต PM2.5]*\n"
                  f"⏰ ตรวจสอบล่าสุด: {now.strftime('%H:%M น.')}\n"
                  f"🔴 รวมระดับสีแดง: {len(all_red)} สถานี\n"
                  f"🆕 พบสถานีแดงใหม่รอบนี้: {len(new_stations)} สถานี\n"
                  f"----------------------------")
        
        details = []
        for i, s in enumerate(all_red, 1):
            history['alerted_ids'][s['id']] = s['time']
            # ปรับเป็นตัวหนาตามคำแนะนำ
            item = (f"{i}. *{s['name']}* ({s['id']})\n"
                    f"📍 {s['area']}\n"
                    f"😷 *AQI:* {s['aqi']} | *PM2.5:* {s['pm25']} µg/m³\n"
                    f"📈 *48ชม:* {s['range']} | 🔍 *สถานะ:* {s['integrity']}\n"
                    f"🚩 *เริ่มแดงตั้งแต่:* {s['red_since']}\n"
                    f"🕒 ข้อมูล ณ: {s['time']}")
            details.append(item)
        
        full_message = header + "\n" + "\n---\n".join(details)
        
        # ส่ง LINE Message
        url = "https://api.line.me/v2/bot/message/push"
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {LINE_TOKEN}"}
        payload = {"to": USER_ID, "messages": [{"type": "text", "text": full_message}]}
        requests.post(url, headers=headers, json=payload)
        
        with open(LOG_FILE, 'w') as f:
            json.dump(history, f)
            
    print(f"สแกนเสร็จสิ้น: พบ {len(all_red)} สถานีแดง (แจ้งใหม่ {len(new_stations)})")

if __name__ == "__main__":
    main()
