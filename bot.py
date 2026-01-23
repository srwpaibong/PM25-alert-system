import requests
import pandas as pd
import os
import json
import datetime
import pytz
import math
import time
import xml.etree.ElementTree as ET

# --- Configuration ---
LINE_TOKEN = os.getenv('LINE_ACCESS_TOKEN')
USER_ID = os.getenv('LINE_USER_ID')
GISTDA_KEY = os.getenv('GISTDA_API_KEY')
TMD_API_KEY = os.getenv('TMD_API_KEY') 

TIMEZONE = pytz.timezone('Asia/Bangkok')
LOG_FILE = "log.json"

# --- Mapping: จังหวัด -> รหัสสถานีอุตุฯ (WMO ID อ้างอิงจาก XML ที่คุณให้มา) ---
TMD_PROVINCE_MAP = {
    # ภาคเหนือ
    "แม่ฮ่องสอน": 48300, "เชียงใหม่": 48302, "เชียงราย": 48303, "พะเยา": 48310,
    "ลำปาง": 48328, "ลำพูน": 48329, "แพร่": 48330, "น่าน": 48331,
    "อุตรดิตถ์": 48351, "ตาก": 48376, "สุโขทัย": 48372, "พิษณุโลก": 48378,
    "เพชรบูรณ์": 48379, "กำแพงเพชร": 48380, "นครสวรรค์": 48400, "อุทัยธานี": 48410,
    
    # ภาคตะวันออกเฉียงเหนือ
    "หนองคาย": 48352, "เลย": 48353, "อุดรธานี": 48354, "สกลนคร": 48356,
    "นครพนม": 48357, "หนองบัวลำภู": 48360, "บึงกาฬ": 48363, "ขอนแก่น": 48381,
    "มุกดาหาร": 48383, "อำนาจเจริญ": 48391, "ชัยภูมิ": 48403, "ร้อยเอ็ด": 48405,
    "ยโสธร": 48406, "นครราชสีมา": 48431, "สุรินทร์": 48432, "บุรีรัมย์": 48437,
    
    # ภาคกลาง (รวม กทม. และปริมณฑล)
    "นครนายก": 48417, "สุพรรณบุรี": 48425, "ลพบุรี": 48426, "สระบุรี": 48426,
    "พระนครศรีอยุธยา": 48455, "อยุธยา": 48455, # ใช้ กทม. (ใกล้เคียง) หรือรอระบบหาจากพิกัด
    "ปทุมธานี": 48455, "นนทบุรี": 48455, 
    "กรุงเทพฯ": 48455, "กรุงเทพมหานคร": 48455, 
    "สมุทรปราการ": 48457, "สมุทรสงคราม": 48438, "สมุทรสาคร": 48438,
    "ราชบุรี": 48438, "นครปฐม": 48438, # อ้างอิงสมุทรสงคราม/กาญจนบุรี
    
    # ภาคตะวันออก
    "ปราจีนบุรี": 48430, "สระแก้ว": 48462, "ฉะเชิงเทรา": 48459,
    "ชลบุรี": 48459, "ระยอง": 48478, "จันทบุรี": 48480, "ตราด": 48501,
    
    # ภาคตะวันตก
    "กาญจนบุรี": 48450, "เพชรบุรี": 48465, "ประจวบคีรีขันธ์": 48500, "หัวหิน": 48475,
    
    # ภาคใต้
    "ชุมพร": 48517, "ระนอง": 48532, "สุราษฎร์ธานี": 48551, "นครศรีธรรมราช": 48552,
    "พังงา": 48561, "กระบี่": 48563, "ภูเก็ต": 48564, "ตรัง": 48567,
    "สตูล": 48570, "ปัตตานี": 48580, "นราธิวาส": 48583, "ยะลา": 48580
}

# --- Thai Wind Direction Mapping ---
WIND_DIR_MAP = {
    "N": "ทิศเหนือ", "NNE": "ทิศตะวันออกเฉียงเหนือ", "NE": "ทิศตะวันออกเฉียงเหนือ", "ENE": "ทิศตะวันออกเฉียงเหนือ",
    "E": "ทิศตะวันออก", "ESE": "ทิศตะวันออกเฉียงใต้", "SE": "ทิศตะวันออกเฉียงใต้", "SSE": "ทิศตะวันออกเฉียงใต้",
    "S": "ทิศใต้", "SSW": "ทิศตะวันตกเฉียงใต้", "SW": "ทิศตะวันตกเฉียงใต้", "WSW": "ทิศตะวันตกเฉียงใต้",
    "W": "ทิศตะวันตก", "WNW": "ทิศตะวันตกเฉียงเหนือ", "NW": "ทิศตะวันตกเฉียงเหนือ", "NNW": "ทิศตะวันตกเฉียงเหนือ",
    "C": "ลมสงบ", "CALM": "ลมสงบ"
}

# --- Helper Functions ---
def haversine(lat1, lon1, lat2, lon2):
    """คำนวณระยะทางระหว่าง 2 พิกัด (km)"""
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2) * math.sin(dlat/2) + \
        math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * \
        math.sin(dlon/2) * math.sin(dlon/2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    return R * c

def calculate_bearing(lat1, lon1, lat2, lon2):
    dLon = math.radians(lon2 - lon1)
    lat1 = math.radians(lat1)
    lat2 = math.radians(lat2)
    y = math.sin(dLon) * math.cos(lat2)
    x = math.cos(lat1) * math.sin(lat2) - \
        math.sin(lat1) * math.cos(lat2) * math.cos(dLon)
    bearing = math.degrees(math.atan2(y, x))
    return (bearing + 360) % 360

def is_upwind(station_lat, station_lon, hotspot_lat, hotspot_lon, wind_deg):
    if wind_deg is None: return True
    target_bearing = calculate_bearing(station_lat, station_lon, hotspot_lat, hotspot_lon)
    diff = abs(target_bearing - wind_deg)
    diff = min(diff, 360 - diff)
    return diff <= 60

def deg_to_compass_thai(num):
    if num is None: return "ไม่ระบุ"
    try:
        val = int((float(num)/22.5)+.5)
        arr = ["ทิศเหนือ", "ทิศตะวันออกเฉียงเหนือ", "ทิศตะวันออกเฉียงเหนือ", "ทิศตะวันออกเฉียงเหนือ",
               "ทิศตะวันออก", "ทิศตะวันออกเฉียงใต้", "ทิศตะวันออกเฉียงใต้", "ทิศตะวันออกเฉียงใต้",
               "ทิศใต้", "ทิศตะวันตกเฉียงใต้", "ทิศตะวันตกเฉียงใต้", "ทิศตะวันตกเฉียงใต้",
               "ทิศตะวันตก", "ทิศตะวันตกเฉียงเหนือ", "ทิศตะวันตกเฉียงเหนือ", "ทิศตะวันตกเฉียงเหนือ"]
        return arr[(val % 16)]
    except:
        return "ไม่ระบุ"

# --- Data Fetching ---

def get_weather_from_tmd_open_api(target_lat, target_lon):
    """
    Backup 3: TMD Open API (Synoptic)
    ค้นหาสถานีที่ใกล้ที่สุดจาก XML โดยคำนวณระยะทางจากพิกัด
    """
    if not TMD_API_KEY:
        return None
        
    url = f"https://data.tmd.go.th/api/Weather3HoursBySynop/V1/?uid=api&ukey={TMD_API_KEY}&format=xml"
    
    try:
        response = requests.get(url, timeout=20)
        if response.status_code != 200:
            return None

        # แก้ไขปัญหา Encoding ถ้าจำเป็น
        response.encoding = 'utf-8'
        
        root = ET.fromstring(response.content)
        
        closest_station = None
        min_dist = 99999
        
        # วนลูป Station ทั้งหมดใน XML เพื่อหาอันที่ใกล้ที่สุด
        for station in root.findall('./Stations/Station'):
            try:
                s_lat = float(station.find('Latitude').text)
                s_lon = float(station.find('Longitude').text)
                
                dist = haversine(target_lat, target_lon, s_lat, s_lon)
                
                if dist < min_dist:
                    min_dist = dist
                    closest_station = station
            except:
                continue
        
        if closest_station is not None:
            name_th = closest_station.find('StationNameThai').text
            obs = closest_station.find('Observation')
            
            w_deg_str = obs.find('WindDirection').text
            w_deg = float(w_deg_str) if w_deg_str else None
            
            w_speed_str = obs.find('WindSpeed').text
            w_speed = float(w_speed_str) if w_speed_str else 0
            
            temp = obs.find('AirTemperature').text
            hum = obs.find('RelativeHumidity').text
            
            return {
                "source": f"กรมอุตุฯ (สถานี{name_th} {min_dist:.1f} กม.)",
                "temp": float(temp) if temp else None,
                "hum": float(hum) if hum else None,
                "wind_spd": w_speed, # XML นี้หน่วยเป็น km/h อยู่แล้ว
                "wind_deg": w_deg,
                "wind_dir": deg_to_compass_thai(w_deg)
            }
            
    except Exception as e:
        print(f"TMD Open API Error: {e}")
        return None
    
    return None

def get_weather_data(s_payload, lat, lon):
    weather = {
        "source": "สถานี คพ.", "temp": None, "hum": None, 
        "wind_spd": None, "wind_dir": None, "wind_deg": None
    }
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }

    # --- 1. Try Air4Thai History ---
    try:
        url = f"http://air4thai.com/forweb/getHistoryData.php?stationID={s_payload['stationID']}&param=PM25,WS,WD,TEMP,RH&type=hr&limit=1"
        h_res = requests.get(url, headers=headers, timeout=5).json()
        if 'stations' in h_res and len(h_res['stations']) > 0:
            latest = h_res['stations'][0]['data'][-1]
            if latest.get('TEMP') and float(latest['TEMP']) > -90: weather['temp'] = float(latest['TEMP'])
            if latest.get('RH'): weather['hum'] = float(latest['RH'])
            if latest.get('WS'): weather['wind_spd'] = float(latest['WS']) * 3.6
            if latest.get('WD'): 
                weather['wind_deg'] = float(latest['WD'])
                weather['wind_dir'] = deg_to_compass_thai(weather['wind_deg'])
    except:
        pass

    # --- 2. TMD Fallback (Private API by Province Map) ---
    if weather['wind_deg'] is None:
        try:
            full_province = s_payload['areaTH'].split(',')[-1].strip()
            province_key = full_province.replace('จ.', '').strip()
            tmd_id = TMD_PROVINCE_MAP.get(province_key)
            
            if tmd_id:
                url_tmd = f"http://122.155.135.49/api/home/site/{tmd_id}"
                t_res = None
                for attempt in range(2):
                    try:
                        resp = requests.get(url_tmd, headers=headers, timeout=15)
                        if resp.status_code == 200:
                            t_res = resp.json()
                            break
                    except:
                        time.sleep(1)

                if t_res and 'data' in t_res and 'items' in t_res['data'] and len(t_res['data']['items']) > 0:
                    item = t_res['data']['items'][0]
                    raw_dir = item.get('winddirsign', 'N/A')
                    weather['source'] = f"กรมอุตุฯ จ.{province_key}"
                    weather['temp'] = item.get('temp')
                    weather['hum'] = item.get('humidity')
                    w_speed = float(item.get('windspeed', 0))
                    if w_speed < 20: w_speed *= 3.6 
                    weather['wind_spd'] = w_speed
                    weather['wind_dir'] = WIND_DIR_MAP.get(raw_dir.upper(), raw_dir)
                    weather['wind_deg'] = float(item.get('winddir', 0))
        except:
            pass

    # --- 3. TMD Open API Fallback (Synoptic XML by Distance) ---
    if weather['wind_deg'] is None:
        synop_weather = get_weather_from_tmd_open_api(lat, lon)
        if synop_weather:
            weather = synop_weather

    if weather['source'] == "สถานี คพ." and weather['wind_deg'] is None:
         weather['source'] = "ไม่พบข้อมูลอากาศ"

    return weather

def get_hotspot_data(lat, lon, wind_deg):
    url = "https://api-gateway.gistda.or.th/api/2.0/resources/features/viirs/1day?limit=1000&offset=0&ct_tn=ราชอาณาจักรไทย"
    headers = {'accept': 'application/json', 'API-Key': GISTDA_KEY}
    
    summary = {
        "upwind_total": 0, "nearby_total": 0,
        "landuse": {}, "nearest": 9999, "nearest_dir": "ไม่พบ",
        "scope_msg": "", "report_count": 0
    }
    
    try:
        res = requests.get(url, headers=headers, timeout=20).json()
        features = res.get('features', [])
        
        for f in features:
            props = f['properties']
            h_lat, h_lon = props['latitude'], props['longitude']
            dist = haversine(lat, lon, h_lat, h_lon)
            
            if dist <= 50:
                summary['nearby_total'] += 1
                if is_upwind(lat, lon, h_lat, h_lon, wind_deg):
                    summary['upwind_total'] += 1
                    lu = props.get('lu_hp_name', 'ไม่ระบุ')
                    summary['landuse'][lu] = summary['landuse'].get(lu, 0) + 1
                
                if dist < summary['nearest']:
                    summary['nearest'] = dist
                    b = calculate_bearing(lat, lon, h_lat, h_lon)
                    summary['nearest_dir'] = deg_to_compass_thai(b)

        if summary['upwind_total'] > 0:
            summary['scope_msg'] = "(รัศมี 50 กม. จากทิศที่ลมพัดมา)"
            summary['report_count'] = summary['upwind_total']
        elif summary['nearby_total'] > 0:
            summary['scope_msg'] = "(รัศมี 50 กม. รอบทิศทาง - ไม่ตรงทิศลม)"
            summary['report_count'] = summary['nearby_total']
        else:
            summary['scope_msg'] = "(รัศมี 50 กม. รอบทิศทาง)"
            summary['report_count'] = 0

    except Exception as e:
        print(f"GISTDA Error: {e}")
        return None

    return summary

def analyze_situation(pm25_now, pm25_24, wind_spd, hotspot_data, integrity, wind_dir_thai):
    analysis = ""
    hotspot_count = hotspot_data['report_count'] if hotspot_data else 0
    
    if "Spike" in integrity: return "⚠️ ข้อมูลผิดปกติ (Spike) โปรดตรวจสอบ"
    if "ขาดหาย" in integrity: return "⚠️ ข้อมูลไม่ครบถ้วน (Missing)"

    factors = []
    # เกณฑ์ลมสงบ < 5 km/h
    if wind_spd is not None and wind_spd < 5: factors.append("ลมนิ่ง")
    if hotspot_count > 5: factors.append("จุดความร้อนมาก")
    
    if pm25_now > 75:
        if hotspot_count > 0 and "ลมนิ่ง" in str(factors):
            analysis = "✅ **สถานการณ์จริง:** ค่าฝุ่นสูงวิกฤตสอดคล้องกับสภาพอากาศปิดและมีจุดความร้อนในพื้นที่"
        elif hotspot_data and hotspot_data['upwind_total'] > 0:
            analysis = f"✅ **สถานการณ์จริง:** ลมพัดพาฝุ่นจากการเผาไหม้ทาง{wind_dir_thai}เข้ามาสะสม"
        elif "ลมนิ่ง" in str(factors):
            analysis = "⚠️ **เฝ้าระวัง:** ไม่พบจุดเผาใกล้เคียง แต่ค่าฝุ่นสูงจากสภาพอากาศปิด (อาจเป็นฝุ่นสะสม)"
        else:
            analysis = "⚠️ **เฝ้าระวัง:** ค่าฝุ่นสูงโดยไม่พบปัจจัยแวดล้อมชัดเจน อาจเกิดจากแหล่งกำเนิดเฉพาะจุด"
            
    return analysis

def load_log():
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, 'r') as f:
            try: return json.load(f)
            except: return {"last_date": "", "alerted_ids": []}
    return {"last_date": "", "alerted_ids": []}

def main():
    now = datetime.datetime.now(TIMEZONE)
    today_str = now.strftime("%Y-%m-%d")
    
    # --- 1. โหลดและเช็ค Log เพื่อรีเซ็ตวันใหม่ ---
    history = load_log()
    if history.get('last_date') != today_str:
        history = {"last_date": today_str, "alerted_ids": []}

    try:
        res = requests.get("http://air4thai.com/forweb/getAQI_JSON.php", timeout=30).json()
    except:
        print("API Error")
        return

    current_red_stations = []

    for s in res.get('stations', []):
        val = s.get('AQILast', {}).get('PM25', {}).get('value')
        s_id = s['stationID']
        
        if val and float(val) > 50.0 and s_id != "11t":
            lat, lon = float(s['lat']), float(s['long'])
            
            # History Data
            edate = now.strftime("%Y-%m-%d")
            sdate = (now - datetime.timedelta(days=2)).strftime("%Y-%m-%d")
            hist_url = f"http://air4thai.com/forweb/getHistoryData.php?stationID={s_id}&param=PM25&type=hr&sdate={sdate}&edate={edate}&stime=00&etime=23"
            try:
                h_res = requests.get(hist_url, timeout=10).json()
                if 'stations' in h_res and len(h_res['stations']) > 0:
                    data = h_res['stations'][0]['data']
                    df = pd.DataFrame(data)
                    df['PM25'] = pd.to_numeric(df['PM25'], errors='coerce')
                    pm25_now, pm25_24h = float(val), df.tail(24)['PM25'].mean()
                    v_min, v_max = df['PM25'].min(), df['PM25'].max()
                    
                    issues = []
                    if df['PM25'].diff().abs().max() > 50: issues.append("Spike")
                    if (df['PM25'].rolling(4).std() == 0).any(): issues.append("Flatline")
                    if df['PM25'].isnull().sum() > 4: issues.append("ขาดหาย > 4ชม.")
                    integrity = "✅ ปกติ" if not issues else f"⚠️ {','.join(issues)}"
                else: raise ValueError("Empty")
            except:
                pm25_24h, v_min, v_max, integrity = 0, 0, 0, "❌ ดึงประวัติไม่ได้"

            weather = get_weather_data(s, lat, lon)
            hotspot = get_hotspot_data(lat, lon, weather['wind_deg'])
            w_dir_th = weather['wind_dir'] if weather['wind_dir'] else "ทิศเหนือลม"
            analysis_text = analyze_situation(pm25_now, pm25_24h, weather['wind_spd'], hotspot, integrity, w_dir_th)

            current_red_stations.append({
                "info": s,
                "stats": {"now": pm25_now, "avg24": pm25_24h, "min": v_min, "max": v_max, "status": integrity},
                "weather": weather,
                "hotspot": hotspot,
                "analysis": analysis_text
            })

    # --- เงื่อนไขหลัก: คัดกรองสถานีใหม่ ---
    new_stations = [s for s in current_red_stations if s['info']['stationID'] not in history['alerted_ids']]
    
    if new_stations:
        print(f"พบสถานีใหม่ {len(new_stations)} แห่ง ส่งรายงาน...")
        for s in new_stations:
            history['alerted_ids'].append(s['info']['stationID'])
        
        msg = f"📊 *[รายงานเฝ้าระวัง PM2.5 ระดับวิกฤต]*\n⏰ ข้อมูล: {now.strftime('%d %b %H:%M น.')}\n🔴 พื้นที่สีแดง: *{len(current_red_stations)}* (🆕 เพิ่มใหม่ {len(new_stations)})\n"
        msg += "--------------------------------\n"
        
        # แสดงรายการ (เอาของใหม่ไว้บนสุด)
        display_list = new_stations + [s for s in current_red_stations if s not in new_stations]
        
        for item in display_list:
            s = item['info']
            st = item['stats']
            w = item['weather']
            h = item['hotspot']
            new_tag = "🆕 " if s['stationID'] in [n['info']['stationID'] for n in new_stations] else ""
            
            w_text = f"*(แหล่งข้อมูล: {w['source']})*\n"
            if w['temp']: w_text += f"• *อุณหภูมิ:* {w['temp']}°C | *ความชื้น:* {w['hum']}%\n"
            if w['wind_dir']: w_text += f"• *ลม:* พัดจาก *{w['wind_dir']}* | *ความเร็ว:* {w['wind_spd']:.1f} กม./ชม."
            else: w_text += "• *ลม:* ไม่มีข้อมูล"

            h_text = ""
            if h and h['report_count'] > 0:
                top_lu = max(h['landuse'], key=h['landuse'].get) if h['landuse'] else "-"
                h_text = (f"*{h['scope_msg']}*\n"
                          f"• *พบทั้งหมด:* {h['report_count']} จุด (สะสม 24ชม.)\n"
                          f"• *พื้นที่หลัก:* {top_lu} ({h['landuse'].get(top_lu,0)})\n"
                          f"• *ระยะใกล้สุด:* {h['nearest']:.1f} กม. ทาง*{h['nearest_dir']}*")
            else:
                h_text = "• ไม่พบจุดความร้อนในรัศมี 50 กม."

            msg += (f"\n{new_tag}📍 *{s['nameTH']} ({s['stationID']})*\n"
                    f"จังหวัด: {s['areaTH'].split(',')[-1].strip()}\n\n"
                    f"💨 *1. ข้อมูลฝุ่น PM2.5*\n"
                    f"• *รายชั่วโมง:* {st['now']} µg/m³ (🔴 วิกฤต)\n"
                    f"• *เฉลี่ย 24 ชม:* {st['avg24']:.1f} µg/m³\n"
                    f"• *พิสัย 48 ชม:* {st['min']} - {st['max']} µg/m³\n"
                    f"• *สถานะข้อมูล:* {st['status']}\n\n"
                    f"🌦️ *2. ข้อมูลอุตุนิยมวิทยา*\n{w_text}\n\n"
                    f"🔥 *3. ข้อมูลจุดความร้อน (Hotspot)*\n{h_text}\n\n"
                    f"📝 *4. ผลการวิเคราะห์*\n{item['analysis']}\n"
                    f"================================\n")

        requests.post("https://api.line.me/v2/bot/message/push", 
                      headers={"Content-Type": "application/json", "Authorization": f"Bearer {LINE_TOKEN}"},
                      json={"to": USER_ID, "messages": [{"type": "text", "text": msg}]})
        
        with open(LOG_FILE, 'w') as f:
            json.dump(history, f)
    else:
        print("ไม่มีสถานีแดงใหม่ ไม่ส่งรายงาน")

if __name__ == "__main__":
    main()
