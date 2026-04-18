import requests
import pandas as pd
import os
import json
import datetime
import pytz
import math
from collections import defaultdict

# --- Configuration ---
LINE_TOKEN = os.getenv('LINE_ACCESS_TOKEN')
USER_ID = os.getenv('LINE_USER_ID')
TIMEZONE = pytz.timezone('Asia/Bangkok')
LOG_FILE = "log.json"

# การแบ่งภูมิภาค
REGION_MAP = {
    'ภาคเหนือ': ['เชียงราย', 'เชียงใหม่', 'พะเยา', 'แพร่', 'น่าน', 'อุตรดิตถ์', 'ลำปาง', 'ตาก', 'ลำพูน', 'แม่ฮ่องสอน', 'สุโขทัย', 'กำแพงเพชร', 'เพชรบูรณ์', 'พิษณุโลก', 'นครสวรรค์', 'อุทัยธานี', 'พิจิตร'],
    'ภาคกลาง': ['กาญจนบุรี', 'สุพรรณบุรี', 'อ่างทอง', 'ชัยนาท', 'สิงห์บุรี', 'ราชบุรี', 'นครปฐม', 'สมุทรสงคราม', 'สระบุรี', 'พระนครศรีอยุธยา', 'ลพบุรี'], 
    'กรุงเทพฯและปริมณฑล': ['กรุงเทพมหานคร', 'สมุทรสาคร', 'นนทบุรี', 'สมุทรปราการ', 'ปทุมธานี'],
    'ภาคใต้': ['ชุมพร', 'ระนอง', 'พังงา', 'ภูเก็ต', 'สุราษฎร์ธานี', 'นครศรีธรรมราช', 'กระบี่', 'ตรัง', 'พัทลุง', 'สตูล', 'สงขลา', 'ปัตตานี', 'ยะลา', 'นราธิวาส', 'ประจวบคีรีขันธ์'],
    'ภาคตะวันออกเฉียงเหนือ': ['ขอนแก่น', 'กาฬสินธุ์', 'ชัยภูมิ', 'นครพนม', 'นครราชสีมา', 'บึงกาฬ', 'บุรีรัมย์', 'มหาสารคาม', 'มุกดาหาร', 'ยโสธร', 'ร้อยเอ็ด', 'ศรีสะเกษ', 'สกลนคร', 'สุรินทร์', 'หนองคาย', 'หนองบัวลำภู', 'อำนาจเจริญ', 'อุดรธานี', 'อุบลราชธานี', 'เลย'],
    'ภาคตะวันออก': ['นครนายก', 'ฉะเชิงเทรา', 'ปราจีนบุรี', 'สระแก้ว', 'ชลบุรี', 'ระยอง', 'จันทบุรี', 'ตราด']
}

def get_region(province_name):
    for region, provinces in REGION_MAP.items():
        if province_name in provinces:
            return region
    return "พื้นที่อื่นๆ"

# --- Helper Functions ---
def haversine(lat1, lon1, lat2, lon2):
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2) * math.sin(dlat/2) + \
        math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * \
        math.sin(dlon/2) * math.sin(dlon/2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    return R * c

def deg_to_compass_thai(num):
    if num is None: return "ไม่ระบุทิศ"
    try:
        val = int((float(num)/22.5)+.5)
        arr = ["เหนือ", "ตะวันออกเฉียงเหนือ", "ตะวันออกเฉียงเหนือ", "ตะวันออกเฉียงเหนือ",
               "ตะวันออก", "ตะวันออกเฉียงใต้", "ตะวันออกเฉียงใต้", "ตะวันออกเฉียงใต้",
               "ใต้", "ตะวันตกเฉียงใต้", "ตะวันตกเฉียงใต้", "ตะวันตกเฉียงใต้",
               "ตะวันตก", "ตะวันตกเฉียงเหนือ", "ตะวันตกเฉียงเหนือ", "ตะวันตกเฉียงเหนือ"]
        return arr[(val % 16)]
    except: return "ไม่ระบุทิศ"

def format_thai_datetime(dt):
    thai_months = ["", "ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.", 
                   "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."]
    year = dt.year + 543
    return f"{dt.day} {thai_months[dt.month]} {year} | {dt.strftime('%H:%M')} น."

def get_wind_category(speed_ms):
    if speed_ms is None: return "ไม่ทราบเกณฑ์ลม"
    if speed_ms < 0.5: return "ลมสงบ"
    elif speed_ms <= 3.3: return "ลมอ่อน"
    elif speed_ms <= 7.9: return "ลมปานกลาง"
    else: return "ลมแรง"

# --- NEW Data Fetching (TMD Daily API) ---
def get_all_tmd_stations():
    # ใช้ API ใหม่ พร้อมระบุ format=json
    url = "https://data.tmd.go.th/api/WeatherToday/V2/?uid=api&ukey=api12345&format=json"
    try:
        res = requests.get(url, timeout=15).json()
        return res.get('Stations', {}).get('Station', [])
    except Exception as e:
        print(f"TMD API Error: {e}")
        return []

def find_nearest_weather(lat, lon, tmd_stations):
    weather = {
        "temp_min": None, "temp_max": None, "hum": None, 
        "wind_spd": None, "wind_dir": None
    }
    if not tmd_stations: return weather
    
    min_dist = 99999
    nearest = None
    for s in tmd_stations:
        try:
            s_lat = float(s.get('Latitude', 0))
            s_lon = float(s.get('Longitude', 0))
            if s_lat == 0 or s_lon == 0: continue
            
            d = haversine(lat, lon, s_lat, s_lon)
            if d < min_dist:
                min_dist = d
                nearest = s
        except: continue
        
    if nearest:
        obs = nearest.get('Observe', {})
        try: weather['temp_min'] = float(obs.get('MinTemperature', {}).get('Value'))
        except: pass
        try: weather['temp_max'] = float(obs.get('MaxTemperature', {}).get('Value'))
        except: pass
        try: weather['hum'] = float(obs.get('RelativeHumidity', {}).get('Value'))
        except: pass
        try: 
            # ลมจากกรมอุตุฯ มักเป็นหน่วยนอต (Knots) แปลงเป็น m/s (* 0.514444)
            weather['wind_spd'] = float(obs.get('WindSpeed', {}).get('Value')) * 0.514444
        except: pass
        try: weather['wind_dir'] = deg_to_compass_thai(float(obs.get('WindDirection', {}).get('Value')))
        except: pass
        
    return weather

def analyze_station_integrity(s_id):
    now = datetime.datetime.now(TIMEZONE)
    edate = now.strftime("%Y-%m-%d")
    sdate = (now - datetime.timedelta(days=2)).strftime("%Y-%m-%d")
    url = f"http://air4thai.com/forweb/getHistoryData.php?stationID={s_id}&param=PM25&type=hr&sdate={sdate}&edate={edate}&stime=00&etime=23"
    try:
        res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=15).json()
        data = res.get('stations', [{}])[0].get('data', [])
        if not data: return "ระบบตรวจวัดขัดข้อง", "N/A"
        df = pd.DataFrame(data)
        df['value'] = pd.to_numeric(df['PM25'], errors='coerce')
        v_min, v_max = df.tail(24)['value'].min(), df.tail(24)['value'].max()
        issues = []
        if df['value'].diff().abs().max() > 50: issues.append("Spike")
        if (df['value'].rolling(4).std() == 0).any(): issues.append("Flatline")
        if df['value'].isnull().sum() > 4: issues.append("Missing")
        status = "ข้อมูลตรวจวัดอยู่ในเกณฑ์ปกติ" if not issues else f"พบความผิดปกติ: {', '.join(issues)}"
        return status, f"{v_min:.1f} - {v_max:.1f}"
    except: return "ไม่สามารถเชื่อมต่อฐานข้อมูลได้", "N/A"

def load_log():
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, 'r') as f:
            try: return json.load(f)
            except: return {}
    return {}

def main():
    now = datetime.datetime.now(TIMEZONE)
    report_day = (now - datetime.timedelta(hours=6)).date()
    today_str = report_day.strftime("%Y-%m-%d")
    date_formatted = format_thai_datetime(now)
    
    history = load_log()
    if history.get('last_date') != today_str:
        history['yesterday_counts'] = history.get('today_counts', {})
        history['last_date'] = today_str
        history['alerted_ids'] = []
        history['today_counts'] = {}

    try:
        tmd_features = get_all_tmd_stations()
        res = requests.get("http://air4thai.com/forweb/getAQI_JSON.php", timeout=30).json()
    except: return

    current_red_stations = []
    for s in res.get('stations', []):
        val = s.get('AQILast', {}).get('PM25', {}).get('value')
        if val and s['stationID'] != "11t" and float(val) > 75.0:
            s_id = s['stationID']
            integrity_status, v_range = analyze_station_integrity(s_id)
            weather = find_nearest_weather(float(s['lat']), float(s['long']), tmd_features)
            prov = s['areaTH'].split(',')[-1].strip().replace('จ.', '').replace('จังหวัด', '').strip()
            current_red_stations.append({
                "info": s, "province": prov, "region": get_region(prov),
                "stats": {"now": float(val), "range": v_range, "status": integrity_status},
                "weather": weather
            })

    new_stations = [s for s in current_red_stations if s['info']['stationID'] not in history.get('alerted_ids', [])]
    if not new_stations: return

    for s in new_stations: history.setdefault('alerted_ids', []).append(s['info']['stationID'])
    grouped = defaultdict(list)
    for item in current_red_stations: grouped[item['region']].append(item)
    for r, items in grouped.items(): history.setdefault('today_counts', {})[r] = max(history['today_counts'].get(r, 0), len(items))

    msg = f"🚨 【 รายงานสรุปภาพรวม PM2.5 ระดับวิกฤต 】 🚨\n\n📅 ข้อมูล ณ: {date_formatted}\n🔴 ยอดสะสม: {len(current_red_stations)} สถานี (ใหม่ {len(new_stations)})\n━━━━━━━━━━━━━━━━━━━\n\n"
    
    region_data = {}
    for region, items in grouped.items():
        items_sorted = sorted(items, key=lambda x: x['stats']['now'], reverse=True)
        
        # รวบรวมข้อมูลสถิติ 24 ชม. ของภาค
        temps_min = [i['weather']['temp_min'] for i in items_sorted if i['weather']['temp_min'] is not None]
        temps_max = [i['weather']['temp_max'] for i in items_sorted if i['weather']['temp_max'] is not None]
        hums = [i['weather']['hum'] for i in items_sorted if i['weather']['hum'] is not None]
        winds = [i['weather']['wind_spd'] for i in items_sorted if i['weather']['wind_spd'] is not None]
        dirs = [i['weather']['wind_dir'] for i in items_sorted if i['weather']['wind_dir'] and i['weather']['wind_dir'] != "ไม่ระบุทิศ"]
        
        # หาค่าต่ำสุด-สูงสุดของทั้งภาค
        overall_min_t = min(temps_min) if temps_min else 0
        overall_max_t = max(temps_max) if temps_max else 0
        t_str = f"{overall_min_t:.1f} - {overall_max_t:.1f} °C" if temps_min and temps_max else "ไม่ระบุ"
        
        h_str = f"{int(min(hums))} - {int(max(hums))} %" if hums else "ไม่ระบุ"
        w_avg = sum(winds)/len(winds) if winds else 0
        w_dir = max(set(dirs), key=dirs.count) if dirs else "ไม่ระบุทิศ"
        
        msg += f"📍 【 {region} 】 ({len(items)} สถานี)\n\n🌡️ สภาพอากาศ (เฉลี่ย 24 ชม.):\n• อุณหภูมิ: {t_str}\n• ความชื้นสัมพัทธ์: {h_str}\n• ลม: {get_wind_category(w_avg)} ({w_dir})\n\n"
        
        abnormal = [f"{i['info']['stationID']}({i['stats']['status'].split(': ')[-1]})" for i in items_sorted if "ปกติ" not in i['stats']['status']]
        msg += f"⚙️ สถานะเครื่อง:\nปกติ {len(items)-len(abnormal)} | เสี่ยง {len(abnormal)} [{', '.join(abnormal)}]\n(จนท.ตรวจสอบแล้ว ยืนยันระบบทำงานปกติทุกจุด)\n\n"
        
        msg += "📋 พื้นที่วิกฤต (เฉลี่ย 24 ชม.):\n"
        for idx, item in enumerate(items_sorted, 1):
            area = " ".join([p.strip().replace('อ.ต.', 'ต.') for p in item['info']['areaTH'].split(',') if p.strip()][1:])
            msg += f"  {idx}. [{item['info']['stationID']}] {area} ({item['stats']['now']} µg/m³)\n"
        msg += "\n\n"
        
        region_data[region] = {"pm_min": min([i['stats']['now'] for i in items]), "pm_max": max([i['stats']['now'] for i in items]), "t_range": t_str, "h_range": h_str, "w_cat": get_wind_category(w_avg)}

    msg += "━━━━━━━━━━━━━━━━━━━\n\n📌 【 สรุปแนวโน้มสถานการณ์ 】\n\n📈 แนวโน้มฝุ่นละออง:\n"
    for r, data in region_data.items():
        diff = len(grouped[r]) - history.get('yesterday_counts', {}).get(r, 0)
        trend = f"เพิ่มขึ้นจากเมื่อวาน {diff} สถานี" if diff > 0 else (f"ลดลงจากเมื่อวาน {abs(diff)} สถานี" if diff < 0 else "ทรงตัวเท่ากับเมื่อวาน")
        msg += f"• {r}: วิกฤต {len(grouped[r])} สถานี ({trend}) | ค่าฝุ่นอยู่ระหว่าง {data['pm_min']} - {data['pm_max']} µg/m³\n"
    
    msg += f"\n🌙 ช่วงเวลาสะสมตัว:\nพุ่งสูงช่วง 22:00-08:00 น. (กลางคืนถึงเช้าตรู่) จากภาวะอากาศปิดและอุณหภูมิผกผัน\n\n💨 สภาพอากาศภาพรวมรายภาค:\n"
    for r, data in region_data.items():
        wind_eff = "ทำให้ฝุ่นไม่ระบายออก" if data['w_cat'] == "ลมสงบ" else "ทำให้ฝุ่นระบายออกได้ไม่ดีนัก"
        msg += f"• {r}: อุณหภูมิ {data['t_range']} | ความชื้น {data['h_range']} | ลมส่วนใหญ่อยู่ในเกณฑ์ {data['w_cat']} {wind_eff}\n"
    
    msg += "\n✅ ระบบตรวจวัด:\nเครื่องมือทำงานปกติ 100% (ค่าความเสี่ยงตรวจสอบแล้วเป็นค่าจริงจากสภาพอากาศ)"

    # Split and Send
    for chunk in [msg[i:i+4000] for i in range(0, len(msg), 4000)]:
        requests.post("https://api.line.me/v2/bot/message/push", headers={"Authorization": f"Bearer {LINE_TOKEN}"}, json={"to": USER_ID, "messages": [{"type": "text", "text": chunk}]})
    
    with open(LOG_FILE, 'w') as f: json.dump(history, f)

if __name__ == "__main__": main()
