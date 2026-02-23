import requests
import pandas as pd
import os
import json
import datetime
import pytz
import math
import time

# --- Configuration ---
LINE_TOKEN = os.getenv('LINE_ACCESS_TOKEN')
USER_ID = os.getenv('LINE_USER_ID')
GISTDA_KEY = os.getenv('GISTDA_API_KEY')
TIMEZONE = pytz.timezone('Asia/Bangkok')
LOG_FILE = "log.json"

# --- Helper Functions ---

def haversine(lat1, lon1, lat2, lon2):
    """คำนวณระยะทาง (km) ระหว่าง 2 พิกัด"""
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2) * math.sin(dlat/2) + \
        math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * \
        math.sin(dlon/2) * math.sin(dlon/2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    return R * c

def calculate_bearing(lat1, lon1, lat2, lon2):
    """คำนวณทิศทาง (Degree) จากจุด 1 ไปจุด 2"""
    dLon = math.radians(lon2 - lon1)
    lat1 = math.radians(lat1)
    lat2 = math.radians(lat2)
    y = math.sin(dLon) * math.cos(lat2)
    x = math.cos(lat1) * math.sin(lat2) - \
        math.sin(lat1) * math.cos(lat2) * math.cos(dLon)
    bearing = math.degrees(math.atan2(y, x))
    return (bearing + 360) % 360

def deg_to_compass_thai(num):
    if num is None: return "ไม่ระบุ"
    try:
        val = int((float(num)/22.5)+.5)
        arr = ["ทิศเหนือ", "ทิศตะวันออกเฉียงเหนือ", "ทิศตะวันออกเฉียงเหนือ", "ทิศตะวันออกเฉียงเหนือ",
               "ทิศตะวันออก", "ทิศตะวันออกเฉียงใต้", "ทิศตะวันออกเฉียงใต้", "ทิศตะวันออกเฉียงใต้",
               "ทิศใต้", "ทิศตะวันตกเฉียงใต้", "ทิศตะวันตกเฉียงใต้", "ทิศตะวันตกเฉียงใต้",
               "ทิศตะวันตก", "ทิศตะวันตกเฉียงเหนือ", "ทิศตะวันตกเฉียงเหนือ", "ทิศตะวันตกเฉียงเหนือ"]
        return arr[(val % 16)]
    except: return "ไม่ระบุ"

def is_upwind(target_bearing, wind_deg):
    """เช็คว่าเป้าหมายอยู่ต้นลมหรือไม่ (+/- 45 องศา)"""
    if wind_deg is None: return False
    diff = abs(target_bearing - wind_deg)
    diff = min(diff, 360 - diff)
    return diff <= 45

# --- Data Fetching Functions ---

def get_all_tmd_stations():
    """ดึงข้อมูลสถานีอุตุฯ ทั้งหมดจาก API ใหม่"""
    url = "http://122.155.135.49/api/home/poi"
    try:
        res = requests.get(url, timeout=15).json()
        # ข้อมูลอยู่ใน features
        return res.get('features', [])
    except Exception as e:
        print(f"TMD POI Error: {e}")
        return []

def find_nearest_weather(lat, lon, tmd_features):
    """ค้นหาสถานีอุตุฯ ที่ใกล้ที่สุดจากพิกัด"""
    weather = {
        "source": "ไม่พบข้อมูล", "temp": None, "hum": None, 
        "wind_spd": None, "wind_dir": None, "wind_deg": None,
        "dist": 9999
    }
    
    if not tmd_features:
        return weather

    nearest_feature = None
    min_dist = 99999

    for f in tmd_features:
        try:
            props = f.get('properties', {})
            # พิกัดอยู่ใน properties หรือ geometry
            s_lat = props.get('lat')
            s_lon = props.get('lon')
            
            if s_lat is None or s_lon is None: continue
            
            dist = haversine(lat, lon, s_lat, s_lon)
            if dist < min_dist:
                min_dist = dist
                nearest_feature = props
        except: continue
    
    if nearest_feature:
        # ดึงข้อมูลจากสถานีที่ใกล้ที่สุด
        weather['dist'] = min_dist
        weather['source'] = f"สถานีอุตุฯ {nearest_feature.get('siteNameFirst', '').split(' ')[0]} (ห่าง {min_dist:.1f} กม.)"
        weather['temp'] = nearest_feature.get('temp')
        weather['hum'] = nearest_feature.get('humidity')
        
        # ลม
        w_speed = nearest_feature.get('windSpeed') # หน่วยมักเป็น m/s หรือ knots
        if w_speed is not None:
            w_speed = float(w_speed)
            if w_speed < 20: w_speed *= 3.6 # แปลงเป็น km/h
            weather['wind_spd'] = w_speed
            
        w_deg = nearest_feature.get('windDir')
        if w_deg is not None:
            weather['wind_deg'] = float(w_deg)
            weather['wind_dir'] = deg_to_compass_thai(w_deg)
            
    return weather

def get_nearest_hotspot(lat, lon, wind_deg):
    """ค้นหาจุดความร้อนที่ใกล้ที่สุด (รองรับ GeoJSON)"""
    # API GISTDA ย้อนหลัง 1 วัน (ตามที่กำหนด)
    url = "https://api-gateway.gistda.or.th/api/2.0/resources/features/viirs/1day?limit=5000&offset=0&ct_tn=ราชอาณาจักรไทย"
    headers = {'accept': 'application/json', 'API-Key': GISTDA_KEY}
    
    hotspot_info = {
        "found": False, "dist": 9999, "dir_text": "", "landuse": "",
        "is_upwind": False, "count": 0
    }
    
    try:
        res = requests.get(url, headers=headers, timeout=20).json()
        features = res.get('features', [])
        hotspot_info['count'] = len(features)
        
        for f in features:
            # GISTDA GeoJSON: coordinates = [lon, lat]
            coords = f.get('geometry', {}).get('coordinates', [])
            if len(coords) < 2: continue
            
            h_lon, h_lat = coords[0], coords[1]
            props = f.get('properties', {})
            
            dist = haversine(lat, lon, h_lat, h_lon)
            
            # เก็บจุดที่ใกล้ที่สุด
            if dist < hotspot_info['dist']:
                hotspot_info['found'] = True
                hotspot_info['dist'] = dist
                hotspot_info['landuse'] = props.get('lu_hp_name', 'ไม่ระบุ')
                
                bearing = calculate_bearing(lat, lon, h_lat, h_lon)
                hotspot_info['dir_text'] = deg_to_compass_thai(bearing)
                hotspot_info['is_upwind'] = is_upwind(bearing, wind_deg)

    except Exception as e:
        print(f"GISTDA API Error: {e}")
        return None

    return hotspot_info

def analyze_station_integrity(s_id):
    """วิเคราะห์ความสมบูรณ์ของข้อมูลย้อนหลัง 48 ชม."""
    now = datetime.datetime.now(TIMEZONE)
    edate = now.strftime("%Y-%m-%d")
    sdate = (now - datetime.timedelta(days=2)).strftime("%Y-%m-%d")
    url = f"http://air4thai.com/forweb/getHistoryData.php?stationID={s_id}&param=PM25&type=hr&sdate={sdate}&edate={edate}&stime=00&etime=23"
    
    try:
        res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=15).json()
        data = res.get('stations', [{}])[0].get('data', [])
        
        if not data: return "⚠️ ไม่พบประวัติ", "N/A"

        df = pd.DataFrame(data)
        df.rename(columns={'DATETIMEDATA': 'datetime', 'PM25': 'value'}, inplace=True)
        df['value'] = pd.to_numeric(df['value'], errors='coerce')
        
        v_min, v_max = df['value'].min(), df['value'].max()
        issues = []
        if df['value'].diff().abs().max() > 50: issues.append("Spike")
        if (df['value'].rolling(4).std() == 0).any(): issues.append("Flatline")
        if df['value'].isnull().sum() > 4: issues.append("ข้อมูลหาย")
        
        status = "✅ ปกติ" if not issues else f"⚠️ {', '.join(issues)}"
        return status, f"{v_min}-{v_max}"
    except:
        return "❌ ระบบขัดข้อง", "N/A"

def analyze_situation(pm25, wind_spd, h_info):
    analysis = ""
    factors = []
    
    if wind_spd is not None and wind_spd < 4: factors.append("สภาพอากาศปิด/ลมนิ่ง")
    if h_info['found']:
        if h_info['dist'] < 20: factors.append(f"จุดความร้อนระยะประชิด ({h_info['dist']:.1f} กม.)")
        elif h_info['is_upwind'] and h_info['dist'] < 100: factors.append("ลมพัดควันเข้ามาสะสม")
    
    if pm25 > 75:
        if factors: analysis = f"✅ สถานการณ์จริง: สอดคล้องกับ {', '.join(factors)}"
        else: analysis = "⚠️ เฝ้าระวัง: ค่าฝุ่นสูงโดยไม่พบปัจจัยแวดล้อมชัดเจน"
    
    return analysis

def load_log():
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, 'r') as f:
            try: return json.load(f)
            except: return {"last_date": "", "alerted_ids": []}
    return {"last_date": "", "alerted_ids": []}

def calculate_thai_aqi(pm25):
    if pm25 <= 15.0: xi, xj, ii, ij = 0, 15.0, 0, 25
    elif pm25 <= 25.0: xi, xj, ii, ij = 15.1, 25.0, 26, 50
    elif pm25 <= 37.5: xi, xj, ii, ij = 25.1, 37.5, 51, 100
    elif pm25 <= 75.0: xi, xj, ii, ij = 37.6, 75.0, 101, 200
    else: xi, xj, ii, ij = 75.1, 500.0, 201, 500
    return int(round(((ij - ii) / (xj - xi)) * (pm25 - xi) + ii))

def main():
    now = datetime.datetime.now(TIMEZONE)
    today_str = now.strftime("%Y-%m-%d")
    history = load_log()
    
    if history.get('last_date') != today_str:
        history = {"last_date": today_str, "alerted_ids": []}

    try:
        # 1. โหลดข้อมูลสถานีอุตุฯ ทั้งหมดเตรียมไว้
        tmd_features = get_all_tmd_stations()
        
        # 2. โหลดข้อมูลฝุ่น
        res = requests.get("http://air4thai.com/forweb/getAQI_JSON.php", timeout=30).json()
    except Exception as e:
        print(f"API Error: {e}")
        return

    current_red_stations = []

    for s in res.get('stations', []):
        val = s.get('AQILast', {}).get('PM25', {}).get('value')
        s_id = s['stationID']
        
        # เงื่อนไข: สีแดง (>75) และไม่ใช่ 11t
        if val and float(val) > 75.0 and s_id != "11t":
            lat, lon = float(s['lat']), float(s['long'])
            pm25_now = float(val)
            
            # Integrity Check
            integrity, v_range = analyze_station_integrity(s_id)
            
            # Weather (Smart Search)
            weather = find_nearest_weather(lat, lon, tmd_features)
            
            # Hotspot
            h_info = get_nearest_hotspot(lat, lon, weather['wind_deg'])
            
            # Analysis
            analysis = analyze_situation(pm25_now, weather['wind_spd'], h_info)

            current_red_stations.append({
                "info": s,
                "stats": {"now": pm25_now, "range": v_range, "status": integrity},
                "weather": weather,
                "hotspot": h_info,
                "analysis": analysis
            })

    # คัดกรองเฉพาะสถานีใหม่
    new_stations = [s for s in current_red_stations if s['info']['stationID'] not in history['alerted_ids']]
    
    if new_stations:
        print(f"พบสถานีใหม่ {len(new_stations)} แห่ง")
        
        # อัปเดต Log
        for s in new_stations:
            history['alerted_ids'].append(s['info']['stationID'])
            
        msg = f"📊 [รายงานเฝ้าระวัง PM2.5 ระดับวิกฤต]\n⏰ ข้อมูล: {now.strftime('%d %b %H:%M น.')}\n🔴 พื้นที่สีแดง: {len(current_red_stations)} (🆕 เพิ่มใหม่ {len(new_stations)})\n"
        msg += "--------------------------------\n"
        
        # เอาสถานีใหม่ขึ้นก่อน
        display_list = new_stations + [s for s in current_red_stations if s not in new_stations]
        
        for item in display_list:
            s = item['info']
            st = item['stats']
            w = item['weather']
            h = item['hotspot']
            
            new_tag = "🆕 " if s['stationID'] in [n['info']['stationID'] for n in new_stations] else ""
            aqi = calculate_thai_aqi(st['now'])
            
            # Weather Block
            w_text = f"(แหล่งข้อมูล: {w['source']})\n"
            if w['temp']: w_text += f"• อุณหภูมิ: {w['temp']}°C | ความชื้น: {w['hum']}%\n"
            if w['wind_dir']: w_text += f"• ลม: พัดจาก {w['wind_dir']} | ความเร็ว: {w['wind_spd']:.1f} กม./ชม."
            else: w_text += "• ลม: ไม่พบข้อมูลในพื้นที่ใกล้เคียง"

            # Hotspot Block
            if h['found']:
                h_text = f"(จุดที่ใกล้ที่สุด)\n• ระยะห่าง: {h['dist']:.1f} กม. ทาง{h['dir_text']}\n• พื้นที่: {h['landuse']}\n"
                if h['is_upwind']: h_text += "• 🌬️ [อยู่ต้นลม] ความเสี่ยงสูง"
                else: h_text += "• 💨 [อยู่ท้ายลม/ข้างลม] ความเสี่ยงต่ำ"
            else:
                h_text = "• ไม่พบข้อมูลจุดความร้อน (ข้อมูลย้อนหลัง 24 ชม.)"

            msg += (f"\n{new_tag}📍 {s['nameTH']} ({s['stationID']})\n"
                    f"จังหวัด: {s['areaTH'].split(',')[-1].strip()}\n\n"
                    f"💨 1. ข้อมูลฝุ่น PM2.5\n"
                    f"• รายชั่วโมง: {st['now']} µg/m³ (🔴 วิกฤต)\n"
                    f"• AQI (คำนวณ): {aqi}\n"
                    f"• พิสัย 48 ชม: {st['range']} µg/m³\n"
                    f"• สถานะข้อมูล: {st['status']}\n\n"
                    f"🌦️ 2. ข้อมูลอุตุนิยมวิทยา\n{w_text}\n\n"
                    f"🔥 3. ข้อมูลจุดความร้อน (Hotspot)\n{h_text}\n\n"
                    f"📝 4. ผลการวิเคราะห์\n{item['analysis']}\n"
                    f"================================\n")

        requests.post("https://api.line.me/v2/bot/message/push", 
                      headers={"Content-Type": "application/json", "Authorization": f"Bearer {LINE_TOKEN}"},
                      json={"to": USER_ID, "messages": [{"type": "text", "text": msg}]})
        
        with open(LOG_FILE, 'w') as f:
            json.dump(history, f)
    else:
        print("ไม่มีสถานีแดงใหม่")

if __name__ == "__main__":
    main()
