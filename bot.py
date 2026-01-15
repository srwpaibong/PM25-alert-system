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
    if pm25 <= 15.0: xi, xj, ii, ij = 0, 15.0, 0, 25
    elif pm25 <= 25.0: xi, xj, ii, ij = 15.1, 25.0, 26, 50
    elif pm25 <= 37.5: xi, xj, ii, ij = 25.1, 37.5, 51, 100
    elif pm25 <= 75.0: xi, xj, ii, ij = 37.6, 75.0, 101, 200
    else: xi, xj, ii, ij = 75.1, 500.0, 201, 500
    return int(round(((ij - ii) / (xj - xi)) * (pm25 - xi) + ii))

def analyze_station_integrity(s_id):
    now = datetime.datetime.now(TIMEZONE)
    edate = now.strftime("%Y-%m-%d")
    sdate = (now - datetime.timedelta(days=2)).strftime("%Y-%m-%d")
    url = f"http://air4thai.com/forweb/getHistoryData.php?stationID={s_id}&param=PM25&type=hr&sdate={sdate}&edate={edate}&stime=00&etime=23"
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        res = requests.get(url, headers=headers, timeout=20).json()
        data = res.get('stations', [{}])[0].get('data', [])
        if not data: return "⚠️ ไม่พบประวัติ", "N/A", "ไม่ทราบเวลา"
        df = pd.DataFrame(data)
        df.rename(columns={'DATETIMEDATA': 'datetime', 'PM25': 'value'}, inplace=True)
        df['value'] = pd.to_numeric(df['value'], errors='coerce')
        v_min, v_max = df['value'].min(), df['value'].max()
        issues = []
        if df['value'].diff().abs().max() > 50: issues.append("Spike")
        if (df['value'].rolling(window=4).std() == 0).any(): issues.append("Flatline")
        if (df['value'] < 0).any(): issues.append("ติดลบ")
        if df['value'].isnull().sum() > 3: issues.append("ข้อมูลหาย")
        status = "✅ ปกติ" if not issues else f"⚠️ {', '.join(issues)}"
        red_start = "แดงต่อเนื่อง > 48 ชม."
        for i in range(len(df)-1, -1, -1):
            if df.iloc[i]['value'] <= 75.0:
                red_start = df.iloc[i+1]['datetime'] if i < len(df)-1 else "เพิ่งเริ่มแดง"
                break
        return status, f"{v_min}-{v_max}", red_start
    except: return "❌ ระบบขัดข้อง", "N/A", "N/A"

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
    if history.get('last_date') != today: history = {"last_date": today, "alerted_ids": {}}

    res = requests.get("http://air4thai.com/forweb/getAQI_JSON.php").json()
    all_stations = []
    for s in res.get('stations', []):
        s_id = s.get('stationID')
        val = s.get('AQILast', {}).get('PM25', {}).get('value')
        if val and float(val) > 75.0 and s_id != "11t":
            integrity, v_range, red_since = analyze_station_integrity(s_id)
            province = s['areaTH'].split(',')[-1].strip()
            all_stations.append({
                "id": s_id, "name": s['nameTH'], "area": s['areaTH'], "province": province,
                "pm25": float(val), "aqi": calculate_thai_aqi(float(val)),
                "time": s['AQILast']['PM25'].get('datetime', now.strftime("%Y-%m-%d %H:%M")),
                "integrity": integrity, "range": v_range, "red_since": red_since
            })

    # แยกสถานีใหม่ และสถานีเดิม
    new_list = [s for s in all_stations if s['id'] not in history['alerted_ids']]
    existing_list = [s for s in all_stations if s['id'] in history['alerted_ids']]
    
    # เรียงลำดับสถานีใหม่: ล่าสุดขึ้นก่อน
    new_list.sort(key=lambda x: x['time'], reverse=True)

    if new_list:
        msg = f"📊 *[สรุปรายงานวิกฤต PM2.5]*\n⏰ ตรวจสอบ: {now.strftime('%H:%M น.')}\n🔴 ทั้งหมด: {len(all_stations)} | 🆕 ใหม่: {len(new_list)}\n"
        
        def format_group(title, stations):
            if not stations: return ""
            section = f"\n{title}\n----------------------------\n"
            # จัดกลุ่มตามจังหวัด
            provinces = sorted(list(set([s['province'] for s in stations])))
            idx = 1
            for p in provinces:
                section += f"📍 *จังหวัด {p}*\n"
                for s in [st for st in stations if st['province'] == p]:
                    section += (f"{idx}. *{s['name']}* ({s['id']})\n"
                                f"😷 *AQI:* {s['aqi']} | *PM2.5:* {s['pm25']}\n"
                                f"📈 *48ชม:* {s['range']} | 🔍 *สถานะ:* {s['integrity']}\n"
                                f"🚩 *เริ่มแดงตั้งแต่:* {s['red_since']}\n"
                                f"🕒 ข้อมูล ณ: {s['time']}\n---\n")
                    history['alerted_ids'][s['id']] = s['time']
                    idx += 1
            return section

        full_msg = msg + format_group("🆕 *สถานีที่ตรวจพบใหม่ในรอบนี้*", new_list)
        if existing_list:
            full_msg += format_group("🔴 *สถานีสีแดงที่ยังวิกฤตต่อเนื่อง*", existing_list)

        requests.post("https://api.line.me/v2/bot/message/push", 
                      headers={"Content-Type":"application/json","Authorization":f"Bearer {LINE_TOKEN}"},
                      json={"to":USER_ID,"messages":[{"type":"text","text":full_msg}]})
        with open(LOG_FILE, 'w') as f: json.dump(history, f)

if __name__ == "__main__":
    main()
